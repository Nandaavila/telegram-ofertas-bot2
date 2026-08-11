"""
scheduler/pipeline.py
=======================
Este é o "maestro": une todas as peças (coletores, filtros, IA,
publisher) em dois fluxos principais:

1. tarefa_buscar_ofertas()  -> roda a cada X minutos, só ALIMENTA o banco
2. tarefa_publicar_oferta() -> roda nos horários programados, PEGA uma
   oferta pronta do banco e publica

Separar "buscar" de "publicar" é importante: assim você pode acumular um
estoque de boas ofertas e controlar a FREQUÊNCIA de posts
independentemente da frequência de coleta.
"""

import asyncio
from datetime import datetime, timedelta
from telegram.error import TelegramError
from database.db import get_session, produto_ja_existe, salvar_produto, registrar_log
from database.models import Produto, Publicacao
from processing.filters import oferta_vale_a_pena, calcular_metricas_desconto, categoria_esta_ativa
from ai.text_generator import gerar_texto_oferta
from creative.image_generator import gerar_imagem_promocional
from publisher.telegram_publisher import TelegramPublisher
from collectors.mercado_livre import MercadoLivreCollector
from collectors.shopee import ShopeeCollector
import config
import os

# Lista de coletores ativos. Adicionar um novo marketplace = adicionar
# uma linha aqui (depois de implementar a classe collector correspondente).
#
# CORREÇÃO: a Shopee estava desativada aqui (commit "temp: desativa Shopee,
# foco em Mercado Livre por enquanto") e nunca foi reativada — por isso
# nenhuma oferta da Shopee era buscada. Reativamos o coletor; se
# SHOPEE_APP_ID/SHOPEE_APP_SECRET não estiverem configurados no .env, o
# próprio ShopeeCollector detecta isso e simplesmente não retorna ofertas
# (ver collectors/shopee.py), sem quebrar o restante do pipeline.
COLETORES = [
    MercadoLivreCollector(),
    ShopeeCollector(),
    # AmazonCollector(),
    # FeedAfiliadosCollector(nome_marketplace="magalu", feed_url="..."),
]


def tarefa_buscar_ofertas():
    """
    Passo 1: percorre cada coletor ativo e cada categoria habilitada,
    filtra o que vale a pena, e salva no banco como status='novo'.
    """
    registrar_log("INFO", "pipeline", "Iniciando busca de ofertas...")

    total_por_marketplace: dict[str, int] = {c.nome_marketplace: 0 for c in COLETORES}
    total_aprovados = 0

    for collector in COLETORES:
        for categoria, ativa in config.CATEGORIAS_ATIVAS.items():
            if not ativa:
                continue
            try:
                ofertas_brutas = collector.buscar_ofertas(categoria)
            except Exception as e:
                # Log completo (não silencioso): guarda o tipo da exceção e
                # a mensagem, para diferenciar erro de rede, erro de auth,
                # resposta inesperada da API, etc.
                registrar_log(
                    "ERROR", f"collector.{collector.nome_marketplace}",
                    f"Falha ao buscar ofertas em '{categoria}': {type(e).__name__}: {e}",
                )
                continue

            total_por_marketplace[collector.nome_marketplace] += len(ofertas_brutas)

            aprovados_nesta_categoria = 0
            with get_session() as session:
                for oferta in ofertas_brutas:
                    # 1) evita duplicados
                    if produto_ja_existe(session, oferta["id_externo"], oferta["marketplace"]):
                        continue
                    # 2) valida se o desconto é real e satisfatório
                    if not oferta_vale_a_pena(oferta["preco_atual"], oferta["preco_anterior"]):
                        continue

                    metricas = calcular_metricas_desconto(oferta["preco_atual"], oferta["preco_anterior"])
                    oferta.update(metricas)
                    oferta["status"] = "pendente_aprovacao" if config.REQUER_APROVACAO_MANUAL else "aprovado"

                    salvar_produto(session, oferta)
                    aprovados_nesta_categoria += 1

            total_aprovados += aprovados_nesta_categoria
            registrar_log(
                "INFO", "pipeline",
                f"{collector.nome_marketplace}: {len(ofertas_brutas)} ofertas encontradas em '{categoria}', "
                f"{aprovados_nesta_categoria} aprovadas após filtros.",
            )

    for marketplace, total in total_por_marketplace.items():
        registrar_log("INFO", "pipeline", f"{marketplace}: {total} ofertas encontradas no total.")

    registrar_log("INFO", "pipeline", f"{total_aprovados} produtos aprovados após filtros nesta rodada de busca.")


def _buscar_candidato_repostagem(session, collectors_por_marketplace: dict) -> Produto | None:
    """
    Quando não há nenhuma oferta NOVA aprovada esperando para publicar,
    procuramos entre as ofertas JÁ PUBLICADAS uma boa candidata a
    repostagem: um desconto muito bom, publicado há tempo suficiente, e
    que ainda não bateu o limite de repostagens permitido.

    IMPORTANTE: antes de repostar, SEMPRE revalidamos a oferta com o
    marketplace de origem. Repostar uma oferta que já expirou seria pior
    do que não postar nada — quebra a confiança do seguidor no canal.
    """
    limite_tempo = datetime.utcnow() - timedelta(hours=config.REPOSTAGEM_INTERVALO_HORAS)

    candidato = (
        session.query(Produto)
        .filter(Produto.status == "publicado")
        .filter(Produto.percentual_desconto >= config.REPOSTAGEM_DESCONTO_MINIMO)
        .filter(Produto.publicado_em <= limite_tempo)
        .filter(Produto.vezes_publicado < config.REPOSTAGEM_MAX_VEZES)
        .order_by(Produto.percentual_desconto.desc())
        .first()
    )

    if not candidato:
        return None

    collector = collectors_por_marketplace.get(candidato.marketplace)
    if not collector:
        # Sem collector disponível para revalidar -> por segurança, não
        # repostamos algo que não conseguimos confirmar que ainda vale.
        return None

    resultado = collector.verificar_oferta_atual(candidato.id_externo)
    if resultado is None:
        # Não conseguimos verificar agora — mais seguro não repostar
        # nesta rodada do que arriscar repostar uma oferta expirada.
        return None

    if not resultado.get("disponivel", True):
        candidato.status = "expirado"
        candidato.expirado_em = datetime.utcnow()
        registrar_log("INFO", "pipeline", f"Candidato a repostagem (produto {candidato.id}) na verdade já expirou.")
        return None

    preco_atual_novo = resultado.get("preco_atual")
    if preco_atual_novo and candidato.preco_anterior:
        novo_desconto = calcular_metricas_desconto(preco_atual_novo, candidato.preco_anterior)["percentual_desconto"]
        if novo_desconto < config.DESCONTO_MINIMO_PERCENTUAL:
            candidato.status = "expirado"
            candidato.expirado_em = datetime.utcnow()
            registrar_log("INFO", "pipeline", f"Candidato a repostagem (produto {candidato.id}) não tem mais desconto suficiente.")
            return None

        # Atualiza os valores para refletir o preço/desconto reais de agora
        candidato.preco_atual = preco_atual_novo
        candidato.percentual_desconto = novo_desconto

    return candidato


async def tarefa_publicar_oferta():
    """
    Passo 2: pega a melhor oferta 'aprovada' ainda não publicada,
    gera um link rastreável (quando disponível), gera o texto com IA
    e publica no Telegram.

    Se não houver nenhuma oferta nova, e a repostagem automática estiver
    ativa (config.REPOSTAGEM_AUTOMATICA_ATIVA), tenta repostar uma das
    melhores ofertas já publicadas, revalidando-a antes.
    """
    # Monta um dicionário {nome_marketplace: instancia_do_collector} para
    # conseguir achar rapidamente qual collector "pertence" a cada produto
    # e chamar os métodos dele (short link, verificação de expiração).
    collectors_por_marketplace = {c.nome_marketplace: c for c in COLETORES}

    with get_session() as session:
        produto = (
            session.query(Produto)
            .filter(Produto.status == "aprovado")
            .order_by(Produto.percentual_desconto.desc())  # prioriza o maior desconto
            .first()
        )

        veio_de_repostagem = False
        if not produto and config.REPOSTAGEM_AUTOMATICA_ATIVA:
            produto = _buscar_candidato_repostagem(session, collectors_por_marketplace)
            veio_de_repostagem = produto is not None

        if not produto:
            registrar_log("INFO", "pipeline", "Nenhuma oferta pronta para publicar (nem para repostar) no momento.")
            return

        # -----------------------------------------------------------
        # 1) Gera um sub_id único para esta publicação. Isso é o que
        #    depois vai permitir, ao ler o relatório de conversões da
        #    Shopee (ou de outra rede que suporte), casar cada clique
        #    exatamente com esta postagem específica do Telegram.
        # -----------------------------------------------------------
        agora = datetime.utcnow()
        sub_id = f"tg_{produto.id}_{agora.strftime('%Y%m%d%H%M')}"

        link_final = produto.url_afiliado  # fallback: link de afiliado normal
        link_rastreado = None

        collector = collectors_por_marketplace.get(produto.marketplace)
        if collector:
            try:
                link_rastreado = collector.gerar_short_link_com_subid(produto.url_afiliado, sub_id)
            except Exception as e:
                # Se o short link falhar por qualquer motivo, NÃO travamos
                # a publicação por causa disso — degradamos graciosamente
                # para o link de afiliado normal e seguimos publicando.
                registrar_log("WARNING", "pipeline", f"Falha ao gerar short link para produto {produto.id}: {e}")

        if link_rastreado:
            link_final = link_rastreado
            registrar_log("INFO", "pipeline", f"Short link rastreável gerado para produto {produto.id} (sub_id={sub_id})")

        produto_dict = {
            "titulo": produto.titulo,
            "categoria": produto.categoria,
            "preco_anterior": produto.preco_anterior,
            "preco_atual": produto.preco_atual,
            "valor_economizado": produto.valor_economizado,
            "percentual_desconto": produto.percentual_desconto,
            "frete_gratis": produto.frete_gratis,
            "avaliacao": produto.avaliacao,
            "parcelamento": produto.parcelamento,
            "url_afiliado": link_final,  # usa o link rastreado quando disponível
        }

        registrar_log("INFO", "pipeline", "Preparando publicação...")

        try:
            texto = gerar_texto_oferta(produto_dict)
        except Exception as e:
            # CORREÇÃO: antes, uma falha aqui (ex: ANTHROPIC_API_KEY ausente
            # ou inválida) subia sem tratamento até o executor do
            # APScheduler — o job era abortado e o erro só aparecia no log
            # interno do agendador, não no sistema de log da aplicação
            # (registrar_log/tabela LogEvento), e por isso nunca aparecia
            # no painel admin nem era fácil de encontrar. Agora o erro é
            # sempre registrado de forma explícita, com o tipo da exceção
            # e a mensagem original da API.
            registrar_log(
                "ERROR", "pipeline",
                f"Falha ao gerar texto da oferta (produto {produto.id}) via Anthropic: "
                f"{type(e).__name__}: {e}",
            )
            return

        if veio_de_repostagem:
            # Deixamos claro para quem já viu esse produto antes que a
            # oferta continua de pé — isso é mais transparente do que
            # simplesmente reenviar o mesmo texto como se fosse inédito.
            texto = f"🔁 <b>ESSA OFERTA AINDA ESTÁ VALENDO!</b>\n\n{texto}"
        produto.texto_gerado = texto

        # -----------------------------------------------------------
        # 2) Gera o card promocional (Pillow) combinando a foto do
        #    produto com preço, desconto e a marca do canal. Se, por
        #    qualquer motivo, a geração falhar (ex: falha ao baixar a
        #    foto do produto), caímos de volta para a foto crua do
        #    marketplace — nunca deixamos uma falha aqui bloquear a
        #    publicação inteira.
        # -----------------------------------------------------------
        caminho_imagem = os.path.join(config.PASTA_IMAGENS_GERADAS, f"produto_{produto.id}.png")
        try:
            imagem_final = gerar_imagem_promocional({**produto_dict, "url_imagem": produto.url_imagem}, caminho_imagem)
        except Exception as e:
            registrar_log("WARNING", "pipeline", f"Falha ao gerar card promocional do produto {produto.id}: {e}")
            imagem_final = produto.url_imagem  # fallback: foto crua do marketplace

        registrar_log("INFO", "pipeline", f"Enviando oferta para o Telegram (produto {produto.id})...")

        try:
            publisher = TelegramPublisher()
            message_id = await publisher.publicar_oferta(texto, imagem_final)
        except TelegramError as e:
            # CORREÇÃO: antes, um erro do Telegram (token inválido, bot sem
            # permissão de admin no canal, chat_id incorreto, etc.) subia
            # sem tratamento e o job inteiro era abortado silenciosamente
            # do ponto de vista da aplicação. Agora capturamos
            # especificamente TelegramError e logamos os detalhes que a
            # biblioteca python-telegram-bot expõe (código/mensagem
            # retornados pela API do Telegram), no formato pedido:
            # [ERROR] Falha ao publicar no Telegram / [ERROR] Resposta da API: ...
            registrar_log("ERROR", "pipeline", "Falha ao publicar no Telegram")
            registrar_log(
                "ERROR", "pipeline",
                f"Tipo do erro: {type(e).__name__} | Resposta da API: {e.message if hasattr(e, 'message') else e}",
            )
            return
        except Exception as e:
            registrar_log(
                "ERROR", "pipeline",
                f"Falha inesperada ao publicar no Telegram (produto {produto.id}): {type(e).__name__}: {e}",
            )
            return

        produto.status = "publicado"
        produto.publicado_em = agora
        produto.vezes_publicado = (produto.vezes_publicado or 0) + 1

        session.add(Publicacao(
            produto_id=produto.id,
            mensagem_id_telegram=message_id,
            sub_id=sub_id,
            link_rastreado=link_rastreado,
        ))

        acao = "repostado" if veio_de_repostagem else "publicado"
        # "SUCCESS" é um nível de log customizado registrado em
        # database/db.py (entre INFO e WARNING), para destacar claramente
        # no console/arquivo de log e na tabela LogEvento quando uma
        # oferta é publicada com sucesso — em vez de se misturar com as
        # demais mensagens [INFO].
        registrar_log(
            "SUCCESS", "pipeline",
            f"Oferta publicada no canal — produto '{produto.titulo}' {acao} com sucesso "
            f"(vezes_publicado={produto.vezes_publicado}, message_id={message_id}).",
        )

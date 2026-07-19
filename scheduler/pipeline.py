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
COLETORES = [
    MercadoLivreCollector(),
    # ShopeeCollector(),
    # AmazonCollector(),
    # FeedAfiliadosCollector(nome_marketplace="magalu", feed_url="..."),
]


def tarefa_buscar_ofertas():
    """
    Passo 1: percorre cada coletor ativo e cada categoria habilitada,
    filtra o que vale a pena, e salva no banco como status='novo'.
    """
    for collector in COLETORES:
        for categoria, ativa in config.CATEGORIAS_ATIVAS.items():
            if not ativa:
                continue
            try:
                ofertas_brutas = collector.buscar_ofertas(categoria)
            except Exception as e:
                registrar_log("ERROR", f"collector.{collector.nome_marketplace}", str(e))
                continue

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

            registrar_log("INFO", "pipeline", f"{len(ofertas_brutas)} ofertas avaliadas em '{categoria}' ({collector.nome_marketplace})")


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

        texto = gerar_texto_oferta(produto_dict)
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

        publisher = TelegramPublisher()
        message_id = await publisher.publicar_oferta(texto, imagem_final)

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
        registrar_log("INFO", "pipeline", f"Produto '{produto.titulo}' {acao} com sucesso (vezes_publicado={produto.vezes_publicado}).")

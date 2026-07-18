"""
processing/expiracao.py
=========================
Job que revisita ofertas JÁ PUBLICADAS e verifica se elas ainda são
válidas: o produto ainda está disponível? O desconto ainda é bom o
suficiente? Se não, marcamos a oferta como "expirada" e atualizamos o
post no Telegram.

Por que isso importa na prática?
Um seguidor que clica num post de 3 dias atrás e encontra o produto sem
desconto (ou esgotado) perde confiança no canal. Marcar visualmente o
post como expirado é mais honesto e profissional do que deixá-lo lá
"prometendo" um preço que não existe mais.

Este job roda separado do job de publicação (scheduler/pipeline.py),
com sua própria frequência, configurável em config.py.
"""

from datetime import datetime, timedelta

from database.db import get_session, registrar_log
from database.models import Produto, Publicacao
from processing.filters import calcular_metricas_desconto
from publisher.telegram_publisher import TelegramPublisher
import config

# Reaproveitamos a MESMA lista de coletores já configurada no pipeline de
# publicação, para não duplicar a definição de "quais marketplaces estão
# ativos" em dois lugares diferentes do projeto.
from scheduler.pipeline import COLETORES

COLETORES_POR_MARKETPLACE = {c.nome_marketplace: c for c in COLETORES}


def _buscar_ultima_publicacao(session, produto_id: int) -> Publicacao | None:
    """Busca o registro de Publicacao mais recente de um produto (para pegar o message_id do Telegram)."""
    return (
        session.query(Publicacao)
        .filter(Publicacao.produto_id == produto_id)
        .order_by(Publicacao.publicado_em.desc())
        .first()
    )


async def _marcar_produto_como_expirado(session, produto: Produto, publisher: TelegramPublisher):
    """
    Executa as duas partes de marcar uma oferta como expirada:
    1) Atualiza o registro no banco (status + timestamp).
    2) Reflete essa mudança visualmente no post do Telegram, conforme a
       ação configurada em config.ACAO_AO_EXPIRAR ("editar" ou "apagar").
    """
    produto.status = "expirado"
    produto.expirado_em = datetime.utcnow()

    ultima_publicacao = _buscar_ultima_publicacao(session, produto.id)
    if not ultima_publicacao or not ultima_publicacao.mensagem_id_telegram:
        # Não temos o id da mensagem para editar/apagar — ainda assim o
        # status no banco já foi corrigido, o que é o mais importante
        # (evita reaproveitar essa oferta numa repostagem, por exemplo).
        registrar_log("WARNING", "expiracao", f"Produto {produto.id} marcado como expirado, mas sem message_id para atualizar o post.")
        return

    try:
        if config.ACAO_AO_EXPIRAR == "apagar":
            await publisher.apagar_mensagem(ultima_publicacao.mensagem_id_telegram)
        else:
            await publisher.marcar_como_expirada(
                ultima_publicacao.mensagem_id_telegram,
                produto.texto_gerado or produto.titulo,
                tinha_foto=True,  # nossos posts quase sempre têm o card gerado; ver telegram_publisher para o fallback
            )
    except Exception as e:
        # Se a edição/remoção no Telegram falhar (ex: post já foi apagado
        # manualmente por você), o status no banco já está correto, então
        # só registramos o problema sem interromper o restante do job.
        registrar_log("WARNING", "expiracao", f"Não foi possível atualizar o post do produto {produto.id} no Telegram: {e}")


async def tarefa_verificar_ofertas_expiradas():
    """
    Função principal do job. Roda periodicamente (ver scheduler.py) e:

    1. Seleciona produtos com status='publicado', publicados há mais
       tempo que o mínimo configurado (não faz sentido checar uma oferta
       publicada há poucos minutos).
    2. Para cada um, pergunta ao collector do marketplace de origem se a
       oferta ainda está disponível e com bom desconto.
    3. Marca como expirada as que não passam mais no critério.
    """
    limite_idade = datetime.utcnow() - timedelta(hours=config.VERIFICACAO_EXPIRACAO_IDADE_MINIMA_HORAS)
    publisher = TelegramPublisher()
    total_verificados = 0
    total_expirados = 0

    with get_session() as session:
        candidatos = (
            session.query(Produto)
            .filter(Produto.status == "publicado")
            .filter(Produto.publicado_em <= limite_idade)
            .all()
        )

        for produto in candidatos:
            collector = COLETORES_POR_MARKETPLACE.get(produto.marketplace)
            if not collector:
                continue  # marketplace sem collector ativo no momento — nada a verificar

            resultado = collector.verificar_oferta_atual(produto.id_externo)
            total_verificados += 1

            if resultado is None:
                # Não conseguimos verificar desta vez (ver docstring em
                # BaseCollector.verificar_oferta_atual) — deixamos como
                # está e tentamos de novo na próxima rodada do job.
                continue

            if not resultado.get("disponivel", True):
                await _marcar_produto_como_expirado(session, produto, publisher)
                total_expirados += 1
                continue

            preco_atual_novo = resultado.get("preco_atual")
            if preco_atual_novo and produto.preco_anterior:
                novo_desconto = calcular_metricas_desconto(preco_atual_novo, produto.preco_anterior)["percentual_desconto"]

                if novo_desconto < config.DESCONTO_MINIMO_PERCENTUAL:
                    await _marcar_produto_como_expirado(session, produto, publisher)
                    total_expirados += 1
                    continue

                # Oferta ainda vale a pena, mas o preço/desconto mudaram
                # um pouco — atualizamos os valores para refletir a
                # realidade atual (importante para uma eventual repostagem
                # usar números corretos).
                produto.preco_atual = preco_atual_novo
                produto.percentual_desconto = novo_desconto

    registrar_log(
        "INFO", "expiracao",
        f"Verificação concluída: {total_verificados} ofertas checadas, {total_expirados} marcadas como expiradas.",
    )

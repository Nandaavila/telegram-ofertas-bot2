"""
processing/sincronizar_conversoes.py
======================================
Fecha o ciclo de rastreamento: pega o relatório de conversões (vendas)
da Shopee Affiliate Open API e casa cada venda com a publicação exata
do Telegram que a originou, usando o sub_id embutido no short link
(gerado em collectors/shopee.py e conectado ao pipeline em
scheduler/pipeline.py).

------------------------------------------------------------------
LIMITAÇÃO IMPORTANTE — leia antes de confiar cegamente nos números
------------------------------------------------------------------
A Shopee Affiliate Open API NÃO expõe um contador de "cliques brutos"
(pessoas que clicaram mas não compraram). O endpoint `conversionReport`
só retorna cliques que geraram pelo menos o início de uma conversão.

Ou seja: o campo `cliques` que preenchemos aqui, na prática, mede
"cliques que converteram em venda", não o total de pessoas que
clicaram no seu link. Isso ainda é extremamente útil (é literalmente a
métrica que te paga!), mas não confunda com uma taxa de cliques real.

Se você quiser o número de cliques BRUTOS (convertendo ou não), a única
forma é ter seu PRÓPRIO redirecionador de link — uma rota tipo
seudominio.com/r/<id> que registra o clique no seu banco e só DEPOIS
redireciona para o link de afiliado. Isso está listado como evolução
futura no README.
"""

import time
from datetime import datetime, timedelta

from database.db import get_session, registrar_log
from database.models import Publicacao, ConversaoProcessada
from collectors.shopee import ShopeeCollector
import config


def _buscar_todas_conversoes(collector: ShopeeCollector, dias_retroativos: int) -> list[dict]:
    """
    Pagina o relatório de conversões da Shopee usando scrollId, coletando
    todas as páginas disponíveis para o período retroativo pedido.

    Atenção ao scrollId: segundo a documentação (não-oficial, mas
    consistente entre implementações), o cursor de uma página só é
    válido por ~30 segundos. Por isso encadeamos as chamadas em sequência
    rápida, sem pausas artificiais entre elas.
    """
    agora = int(time.time())
    inicio = agora - (dias_retroativos * 86400)

    todas_conversoes = []
    scroll_id = None

    while True:
        try:
            dados = collector.buscar_relatorio_conversoes(inicio, agora, scroll_id=scroll_id)
        except RuntimeError as e:
            registrar_log("ERROR", "sincronizacao_conversoes", f"Falha ao consultar conversionReport: {e}")
            break

        bloco = dados.get("conversionReport", {})
        nodes = bloco.get("nodes", [])
        todas_conversoes.extend(nodes)

        page_info = bloco.get("pageInfo", {}) or {}
        if not page_info.get("hasNextPage") or not page_info.get("scrollId"):
            break
        scroll_id = page_info["scrollId"]

    return todas_conversoes


def _casar_conversao_com_publicacao(utm_content: str, publicacoes_por_sub_id: dict):
    """
    Tenta achar qual publicação do Telegram gerou uma determinada
    conversão, procurando o sub_id dela dentro do campo utmContent.

    Usamos correspondência por "contém" (substring) em vez de igualdade
    exata porque não temos garantia de como a Shopee formata o
    utmContent internamente quando múltiplos sub_ids estão envolvidos.
    Como nosso sub_id segue um formato bem específico e improvável de
    colidir por acaso ("tg_<produto_id>_<timestamp>"), esse método é
    seguro na prática.
    """
    if not utm_content:
        return None

    for sub_id, publicacao in publicacoes_por_sub_id.items():
        if sub_id in utm_content:
            return publicacao
    return None


def tarefa_sincronizar_conversoes_shopee():
    """
    Função principal do job. Busca as conversões dos últimos N dias
    (configurável) e atualiza cliques/pedidos/comissão de cada
    Publicacao correspondente.
    """
    collector = ShopeeCollector()
    if not collector.credenciais_ok():
        # Antes, isso quebrava com AttributeError (config.SHOPEE_APP_ID
        # não existia). Agora a variável existe (mesmo que vazia) e este
        # guard evita rodar o job inteiro sem credenciais configuradas.
        registrar_log(
            "INFO", "sincronizacao_conversoes",
            "SHOPEE_APP_ID/SHOPEE_APP_SECRET não configurados — sincronização pulada.",
        )
        return

    dias_retroativos = config.SINCRONIZACAO_CONVERSOES_DIAS_RETROATIVOS

    conversoes = _buscar_todas_conversoes(collector, dias_retroativos)
    if not conversoes:
        registrar_log("INFO", "sincronizacao_conversoes", "Nenhuma conversão retornada pela Shopee no período verificado.")
        return

    total_casadas = 0

    with get_session() as session:
        # Carregamos em memória as publicações candidatas (com sub_id
        # preenchido, dentro da mesma janela de tempo), para evitar uma
        # query no banco por conversão individual.
        limite = datetime.utcnow() - timedelta(days=dias_retroativos + 1)
        publicacoes = (
            session.query(Publicacao)
            .filter(Publicacao.sub_id.isnot(None))
            .filter(Publicacao.publicado_em >= limite)
            .all()
        )
        publicacoes_por_sub_id = {p.sub_id: p for p in publicacoes if p.sub_id}

        # Carregamos também o conjunto de conversion_ids já processados
        # em execuções anteriores, para pular exatamente essas.
        ids_ja_processados = {
            c.conversion_id for c in session.query(ConversaoProcessada.conversion_id).all()
        }

        for conversao in conversoes:
            conversion_id = conversao.get("conversionId")

            # Sem conversion_id não temos como deduplicar com segurança;
            # por precaução, pulamos em vez de arriscar contar errado.
            if not conversion_id or conversion_id in ids_ja_processados:
                continue

            publicacao = _casar_conversao_com_publicacao(
                conversao.get("utmContent", ""), publicacoes_por_sub_id
            )
            if not publicacao:
                continue

            pedidos = conversao.get("orders") or []
            comissao = conversao.get("totalCommission") or 0

            publicacao.cliques = (publicacao.cliques or 0) + 1
            publicacao.pedidos = (publicacao.pedidos or 0) + len(pedidos)
            publicacao.comissao_estimada = round((publicacao.comissao_estimada or 0.0) + float(comissao), 2)

            # Marca esta conversão como processada, para nunca mais somá-la
            session.add(ConversaoProcessada(conversion_id=conversion_id))
            ids_ja_processados.add(conversion_id)

            total_casadas += 1

    registrar_log(
        "INFO", "sincronizacao_conversoes",
        f"{total_casadas} de {len(conversoes)} conversões novas casadas com publicações do Telegram.",
    )

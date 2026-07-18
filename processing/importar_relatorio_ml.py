"""
processing/importar_relatorio_ml.py
=====================================
Importa o relatório de cliques/vendas/comissões exportado manualmente
do painel de afiliados do Mercado Livre.

------------------------------------------------------------------
POR QUE ISSO É DIFERENTE DO JOB DA SHOPEE — LEIA ANTES DE USAR
------------------------------------------------------------------
Diferente da Shopee, o Programa de Afiliados do Mercado Livre NÃO
disponibiliza uma API pública de relatórios de cliques, conversões ou
comissões. A API de Developers do Mercado Livre (developers.mercadolivre
.com.br) cobre catálogo, pedidos, envios e faturamento de VENDEDOR — não
o painel de afiliados, que é uma ferramenta separada, acessível apenas
pelo navegador em mercadolivre.com.br/afiliados.

Ou seja: aqui NÃO existe o mesmo job 100% automático e silencioso que
implementamos para a Shopee. A alternativa realista (e honesta) é:

1. Você exporta manualmente o relatório em CSV pelo painel de afiliados
   do Mercado Livre (aba "Relatórios" → exportar).
2. Roda este importador apontando para o arquivo baixado — seja via
   linha de comando, seja pelo botão de upload no painel administrativo
   (veja admin/app.py).
3. Ele casa cada linha do relatório com o produto certo usando o código
   do anúncio (MLB...), que já guardamos como id_externo, e atualiza
   cliques/pedidos/comissão da publicação correspondente no Telegram.

Se no futuro você quiser automatizar até o passo de baixar o CSV, a
única forma seria automatizar o LOGIN NO PAINEL (ex: Playwright/Selenium
navegando como você mesma navegaria) — isso já seria automação de
interface, não uso de API pública, com os riscos normais de UI scraping
(quebra se o Mercado Livre mudar o layout; deve respeitar os Termos de
Uso do programa de afiliados). Por segurança e estabilidade, não
implementamos esse caminho aqui.

------------------------------------------------------------------
SOBRE O MAPEAMENTO DE COLUNAS DO CSV
------------------------------------------------------------------
Não temos certeza absoluta dos nomes EXATOS das colunas que o Mercado
Livre usa no arquivo exportado (o layout pode até mudar com o tempo).
Por isso, o mapeamento de colunas fica centralizado em
config.COLUNAS_RELATORIO_ML — abra o CSV exportado de verdade UMA VEZ,
confira os cabeçalhos reais, e ajuste esse dicionário para bater
exatamente antes de confiar nos resultados.

------------------------------------------------------------------
SOBRE ACUMULAÇÃO DE VALORES (evite contar errado)
------------------------------------------------------------------
Assumimos que o relatório exportado traz TOTAIS ACUMULADOS para o
período selecionado no painel (diferente da Shopee, que retorna eventos
individuais). Por isso, esta função SOBRESCREVE os valores de
cliques/pedidos/comissão da publicação mais recente do produto, em vez
de somar. Para evitar contagem duplicada ou perdida, sempre exporte o
MESMO período de referência a cada importação (ex: sempre "desde o
início"), em vez de janelas que mudam ou se sobrepõem parcialmente.
"""

import csv
import re

from database.db import get_session, registrar_log
from database.models import Produto, Publicacao
import config

# Reconhece códigos de anúncio do Mercado Livre em qualquer formato:
# "MLB123456789", "MLB-123456789", dentro de uma URL completa, etc.
REGEX_CODIGO_MLB = re.compile(r"(MLB-?\d+)")


def _extrair_codigo_mlb(texto: str) -> str | None:
    """
    Extrai o código do anúncio (MLBxxxxxxxx) de uma célula do CSV, que
    pode conter o código puro, um link completo do produto, ou um texto
    livre com o código embutido em algum lugar.
    """
    if not texto:
        return None
    resultado = REGEX_CODIGO_MLB.search(texto.upper())
    if not resultado:
        return None
    return resultado.group(1).replace("-", "")


def _converter_valor_monetario(texto: str) -> float:
    """
    Converte um valor monetário no formato brasileiro (ex: "R$ 1.234,56")
    para float (1234.56). Planilhas exportadas no Brasil costumam usar
    ponto como separador de milhar e vírgula como decimal — o oposto do
    padrão que o Python espera nativamente.
    """
    if not texto:
        return 0.0
    limpo = texto.replace("R$", "").strip().replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return 0.0


def importar_relatorio_csv_mercadolivre(caminho_csv: str) -> dict:
    """
    Lê o CSV exportado do painel de afiliados do Mercado Livre e
    atualiza os registros de Publicacao correspondentes.

    Retorna um resumo: {"processadas": int, "casadas": int, "sem_match": int}
    útil para exibir feedback de sucesso/erro para quem fez o upload.
    """
    mapeamento = config.COLUNAS_RELATORIO_ML
    processadas = 0
    casadas = 0
    sem_match = 0

    with get_session() as session:
        with open(caminho_csv, newline="", encoding="utf-8-sig") as arquivo:
            leitor = csv.DictReader(arquivo)

            colunas_faltando = [c for c in mapeamento.values() if c not in (leitor.fieldnames or [])]
            if colunas_faltando:
                registrar_log(
                    "ERROR", "importar_relatorio_ml",
                    f"Colunas esperadas não encontradas no CSV: {colunas_faltando}. "
                    f"Cabeçalhos reais do arquivo: {leitor.fieldnames}. "
                    f"Ajuste config.COLUNAS_RELATORIO_ML.",
                )
                return {"processadas": 0, "casadas": 0, "sem_match": 0, "erro": "colunas_incompativeis"}

            for linha in leitor:
                processadas += 1

                valor_identificacao = linha.get(mapeamento["identificador_produto"], "")
                codigo_mlb = _extrair_codigo_mlb(valor_identificacao)

                if not codigo_mlb:
                    sem_match += 1
                    continue

                produto = (
                    session.query(Produto)
                    .filter(Produto.marketplace == "mercadolivre")
                    .filter(Produto.id_externo == codigo_mlb)
                    .order_by(Produto.coletado_em.desc())
                    .first()
                )
                if not produto:
                    # O relatório tem um produto que não está no nosso banco
                    # (ex: foi divulgado manualmente, fora da automação).
                    sem_match += 1
                    continue

                publicacao = (
                    session.query(Publicacao)
                    .filter(Publicacao.produto_id == produto.id)
                    .order_by(Publicacao.publicado_em.desc())
                    .first()
                )
                if not publicacao:
                    # Produto existe no banco, mas nunca chegou a ser
                    # publicado de fato no Telegram por esta automação.
                    sem_match += 1
                    continue

                try:
                    publicacao.cliques = int(float(linha.get(mapeamento["cliques"], 0) or 0))
                    publicacao.pedidos = int(float(linha.get(mapeamento["pedidos"], 0) or 0))
                    publicacao.comissao_estimada = _converter_valor_monetario(linha.get(mapeamento["comissao"], "0"))
                except (ValueError, TypeError):
                    registrar_log("WARNING", "importar_relatorio_ml", f"Linha com valores inválidos para o produto {codigo_mlb}, pulando.")
                    sem_match += 1
                    continue

                casadas += 1

    resumo = {"processadas": processadas, "casadas": casadas, "sem_match": sem_match}
    registrar_log(
        "INFO", "importar_relatorio_ml",
        f"Importação concluída: {casadas} de {processadas} linhas casadas com publicações "
        f"({sem_match} sem correspondência).",
    )
    return resumo

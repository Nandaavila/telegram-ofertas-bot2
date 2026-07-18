"""
collectors/shopee.py
======================
Coletor de ofertas da Shopee usando a Shopee Affiliate Open API (oficial),
que expõe um endpoint GraphQL autenticado por assinatura HMAC-SHA256.

Isso NÃO é scraping: é a API que a própria Shopee disponibiliza para
afiliados aprovados. Endpoint, autenticação e campos abaixo foram
confirmados na documentação oficial (affiliate.shopee.com.br) e em
integrações públicas de referência.

------------------------------------------------------------------
COMO OBTER AS CREDENCIAIS (pré-requisito)
------------------------------------------------------------------
1. Cadastre-se em https://affiliate.shopee.com.br (aprovação manual,
   costuma levar de 5 a 15 dias).
2. Após aprovado, acesse a seção "Open API" no seu painel de afiliado.
3. Copie o App ID (numérico) e o App Secret (string longa).
4. Coloque-os no seu .env como SHOPEE_APP_ID e SHOPEE_APP_SECRET.

------------------------------------------------------------------
COMO FUNCIONA A AUTENTICAÇÃO (a parte mais delicada da integração)
------------------------------------------------------------------
Toda requisição precisa de um cabeçalho Authorization no formato:

    Authorization: SHA256 Credential={appId}, Timestamp={timestamp}, Signature={signature}

Onde:
    timestamp = hora atual em segundos Unix (não milissegundos!)
    signature = SHA256( appId + timestamp + payload_json_exato + secret )

O ponto mais importante — e que mais gera erro "Invalid Signature" em
quem implementa isso pela primeira vez — é que o `payload_json_exato`
usado para calcular a assinatura TEM que ser BYTE A BYTE idêntico ao
JSON que você realmente envia no corpo da requisição. Se você montar a
string de um jeito para assinar e enviar o dict serializado de outro
jeito (ex: com espaços diferentes), a assinatura não bate.
Por isso, no código abaixo, serializamos o payload UMA ÚNICA VEZ com
`json.dumps` e reaproveitamos essa mesma string tanto para assinar
quanto para enviar.
"""

import hashlib
import json
import time
import requests
from collectors.base_collector import BaseCollector
from database.db import registrar_log
import config

# A Shopee organiza por "keyword" (palavra-chave) na busca de ofertas,
# não por um category_id fixo e simples de usar via productOfferV2.
# Por isso mapeamos nossas categorias internas para termos de busca.
MAPA_CATEGORIAS = {
    "casa": "casa",
    "eletronicos": "eletronicos",
    "moda_feminina": "moda feminina",
    "moda_masculina": "moda masculina",
    "beleza": "beleza",
    "informatica": "informatica",
}

# Código de erro de rate limit retornado pela Shopee Open API.
CODIGO_ERRO_RATE_LIMIT = 10030


class ShopeeCollector(BaseCollector):
    nome_marketplace = "shopee"

    def __init__(self):
        self.endpoint = "https://open-api.affiliate.shopee.com.br/graphql"
        self.app_id = config.SHOPEE_APP_ID
        self.app_secret = config.SHOPEE_APP_SECRET

    # -----------------------------------------------------------------
    # AUTENTICAÇÃO
    # -----------------------------------------------------------------
    def _montar_headers_assinados(self, payload_str: str) -> dict:
        """
        Gera o cabeçalho Authorization exigido pela Shopee, a partir do
        payload (string JSON) que será enviado no corpo da requisição.
        """
        timestamp = int(time.time())

        # A "fórmula" oficial de assinatura: concatenação simples (sem
        # separadores) de appId + timestamp + payload + secret, depois
        # hash SHA256 em hexadecimal.
        base_assinatura = f"{self.app_id}{timestamp}{payload_str}{self.app_secret}"
        assinatura = hashlib.sha256(base_assinatura.encode("utf-8")).hexdigest()

        return {
            "Content-Type": "application/json",
            "Authorization": (
                f"SHA256 Credential={self.app_id}, "
                f"Timestamp={timestamp}, "
                f"Signature={assinatura}"
            ),
        }

    def _executar_query(self, query: str, variables: dict, max_tentativas: int = 3) -> dict:
        """
        Envia uma query GraphQL já assinada para a Shopee Affiliate API,
        com retry automático em caso de rate limit (erro 10030).
        """
        corpo = {"query": query, "variables": variables}

        # IMPORTANTE: serializamos uma única vez e usamos essa MESMA
        # string tanto para calcular a assinatura quanto para enviar.
        payload_str = json.dumps(corpo, separators=(",", ":"))

        tentativa = 0
        while tentativa < max_tentativas:
            headers = self._montar_headers_assinados(payload_str)
            resposta = requests.post(
                self.endpoint, data=payload_str, headers=headers, timeout=20
            )
            dados = resposta.json()

            erros = dados.get("errors")
            if erros:
                codigo = erros[0].get("extensions", {}).get("code")
                if codigo == CODIGO_ERRO_RATE_LIMIT:
                    # Backoff exponencial: espera mais a cada nova tentativa.
                    espera = 2 ** (tentativa + 1)
                    registrar_log(
                        "WARNING", "collector.shopee",
                        f"Rate limit atingido, aguardando {espera}s (tentativa {tentativa + 1})",
                    )
                    time.sleep(espera)
                    tentativa += 1
                    continue
                # Outro tipo de erro (ex: credenciais inválidas) -> falha direto,
                # não adianta tentar de novo.
                raise RuntimeError(f"Erro da API Shopee: {erros}")

            return dados.get("data", {})

        raise RuntimeError("Falha ao consultar a API da Shopee após múltiplas tentativas (rate limit).")

    # -----------------------------------------------------------------
    # BUSCA DE OFERTAS
    # -----------------------------------------------------------------
    def buscar_ofertas(self, categoria: str, paginas: int = 2) -> list[dict]:
        """
        Busca ofertas por palavra-chave usando productOfferV2.
        Percorre algumas páginas (cada página traz até 50 itens).
        """
        termo_busca = MAPA_CATEGORIAS.get(categoria, categoria)

        query = """
        query BuscarOfertas($keyword: String, $page: Int, $limit: Int, $sortType: Int) {
            productOfferV2(
                keyword: $keyword,
                page: $page,
                limit: $limit,
                sortType: $sortType
            ) {
                nodes {
                    itemId
                    shopId
                    productName
                    imageUrl
                    price
                    priceMin
                    priceMax
                    priceDiscountRate
                    ratingStar
                    sales
                    commissionRate
                    commission
                    productLink
                    offerLink
                }
            }
        }
        """

        todas_ofertas = []
        for pagina in range(paginas):
            variables = {
                "keyword": termo_busca,
                "page": pagina,
                "limit": 50,
                "sortType": 2,  # 2 = ordenar por maior comissão/relevância de oferta
            }

            try:
                dados = self._executar_query(query, variables)
            except RuntimeError as e:
                registrar_log("ERROR", "collector.shopee", str(e))
                break

            nodes = dados.get("productOfferV2", {}).get("nodes", [])
            if not nodes:
                break  # não há mais páginas com resultado

            for item in nodes:
                oferta = self._converter_item(item, categoria)
                if oferta:
                    todas_ofertas.append(oferta)

        return todas_ofertas

    def _converter_item(self, item: dict, categoria: str) -> dict | None:
        """
        Converte um item retornado pela Shopee no formato padrão usado
        pelo resto do sistema (o mesmo "contrato" de BaseCollector).

        Detalhe importante: a Open API da Shopee NÃO retorna um campo de
        "preço anterior" pronto. Ela retorna `priceDiscountRate` (o
        percentual de desconto). Por isso calculamos o preço anterior a
        partir da fórmula:
            preco_anterior = preco_atual / (1 - desconto/100)
        """
        preco_atual = item.get("price")
        desconto_rate = item.get("priceDiscountRate")  # ex: 35 (=35%)

        if not preco_atual or not desconto_rate or desconto_rate <= 0:
            return None

        try:
            preco_atual = float(preco_atual)
            desconto_rate = float(desconto_rate)
            preco_anterior = round(preco_atual / (1 - desconto_rate / 100), 2)
        except (TypeError, ValueError, ZeroDivisionError):
            return None

        return {
            "id_externo": f"{item.get('shopId')}_{item.get('itemId')}",
            "marketplace": self.nome_marketplace,
            "categoria": categoria,
            "titulo": item.get("productName"),
            "url_produto": item.get("productLink"),
            # offerLink já vem com o tracking do SEU app_id embutido —
            # não precisamos (nem devemos) montar esse link manualmente.
            "url_afiliado": item.get("offerLink") or item.get("productLink"),
            "url_imagem": item.get("imageUrl"),
            "preco_atual": preco_atual,
            "preco_anterior": preco_anterior,
            "frete_gratis": False,  # a Open API não informa frete por item; refine via shopOfferV2 se precisar
            "parcelamento": None,
            "avaliacao": item.get("ratingStar"),
        }

    # -----------------------------------------------------------------
    # SHORT LINKS RASTREÁVEIS (opcional, mas recomendado)
    # -----------------------------------------------------------------
    def gerar_short_link_com_subid(self, url_longa: str, sub_id: str) -> str | None:
        """
        Gera um link curto rastreável para uma oferta específica, usando
        um sub_id (ex: "telegram_canal1_20260701") para depois conseguir
        cruzar cliques com a publicação exata no seu painel admin.

        Isso é o que possibilita estatísticas de cliques REAIS por post,
        em vez de estimativas.
        """
        query = """
        mutation GerarLink($input: ShortLinkInput!) {
            generateShortLink(input: $input) {
                shortLink
            }
        }
        """
        variables = {
            "input": {
                "originUrl": url_longa,
                "subIds": [sub_id],
            }
        }

        try:
            dados = self._executar_query(query, variables)
            return dados.get("generateShortLink", {}).get("shortLink")
        except RuntimeError as e:
            registrar_log("ERROR", "collector.shopee", f"Falha ao gerar short link: {e}")
            return None

    # -----------------------------------------------------------------
    # VERIFICAÇÃO DE OFERTA ATIVA (para o job de detecção de expiração)
    # -----------------------------------------------------------------
    def verificar_oferta_atual(self, id_externo: str) -> dict | None:
        """
        Consulta se um item específico ainda está com a oferta ativa,
        filtrando o productOfferV2 pelo itemId em vez de por palavra-chave.

        Nosso id_externo é salvo no formato "{shopId}_{itemId}" (veja
        _converter_item), então primeiro separamos essas duas partes.

        Observação importante: o filtro direto por itemId no
        productOfferV2 pode não estar disponível em todas as versões do
        schema da Open API, dependendo do seu nível de acesso. Se a
        consulta falhar por esse motivo, retornamos None (não sabemos
        dizer) em vez de arriscar marcar uma oferta válida como expirada
        por um erro de compatibilidade de API.
        """
        try:
            _, item_id = id_externo.split("_", 1)
        except ValueError:
            return None

        query = """
        query VerificarItem($itemId: Int64) {
            productOfferV2(itemId: $itemId, limit: 1) {
                nodes {
                    price
                    priceDiscountRate
                }
            }
        }
        """

        try:
            dados = self._executar_query(query, {"itemId": int(item_id)})
        except (RuntimeError, ValueError):
            return None

        nodes = dados.get("productOfferV2", {}).get("nodes", [])
        if not nodes:
            # A Shopee não retornou mais esse item -> oferta indisponível
            return {"disponivel": False, "preco_atual": None}

        try:
            preco_atual = float(nodes[0]["price"])
        except (TypeError, ValueError, KeyError):
            return None

        return {"disponivel": True, "preco_atual": preco_atual}

    # -----------------------------------------------------------------
    # RELATÓRIO DE CONVERSÕES (para sincronizar cliques/vendas)
    # -----------------------------------------------------------------
    def buscar_relatorio_conversoes(self, purchase_time_start: int, purchase_time_end: int,
                                      scroll_id: str | None = None, limit: int = 50) -> dict:
        """
        Consulta o relatório de conversões (vendas geradas pelos seus
        links de afiliado) num intervalo de tempo.

        ⚠️ AVISO IMPORTANTE sobre os nomes exatos dos campos abaixo:
        a Shopee não publica uma documentação oficial completa e
        versionada da Open API (o que existe é documentação de
        terceiros/comunidade). A estrutura usada aqui — em especial os
        nomes dentro de "pageInfo" (scrollId/hasNextPage) — é a mais
        consistente com o padrão de paginação Relay/GraphQL e com
        implementações de referência encontradas publicamente, mas
        RECOMENDO fortemente rodar uma introspecção do schema (ou testar
        no Playground de afiliados da Shopee) assim que suas credenciais
        forem aprovadas, para confirmar os nomes exatos antes de colocar
        isso em produção. Se algum campo não existir, a API retornará um
        erro claro em vez de dado incorreto — então é seguro testar.

        Parâmetros de tempo são timestamps Unix (segundos), não milissegundos.
        """
        query = """
        query RelatorioConversoes($inicio: Int!, $fim: Int!, $scrollId: String, $limit: Int) {
            conversionReport(
                purchaseTimeStart: $inicio,
                purchaseTimeEnd: $fim,
                scrollId: $scrollId,
                limit: $limit
            ) {
                nodes {
                    conversionId
                    purchaseTime
                    clickTime
                    totalCommission
                    utmContent
                    orders {
                        orderId
                        orderStatus
                    }
                }
                pageInfo {
                    scrollId
                    hasNextPage
                }
            }
        }
        """
        variables = {
            "inicio": purchase_time_start,
            "fim": purchase_time_end,
            "scrollId": scroll_id,
            "limit": limit,
        }
        return self._executar_query(query, variables)

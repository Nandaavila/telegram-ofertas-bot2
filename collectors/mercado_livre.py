"""
collectors/mercado_livre.py
============================
Coletor de ofertas do Mercado Livre.

O Mercado Livre disponibiliza uma API PÚBLICA de busca, sem necessidade
de scraping, em:
    https://api.mercadolibre.com/sites/MLB/search?q=<termo>

Isso é ótimo para nós: dados estruturados, estáveis, sem risco de bloqueio
por "bater" no HTML da página.

Para o programa de afiliados oficial, veja:
    https://www.mercadolivre.com.br/afiliados
O "tag" de afiliado é anexado como parâmetro na URL final do produto.
"""

import requests
from collectors.base_collector import BaseCollector
import config

# Mapeamos nossas categorias internas para os termos de busca do Mercado Livre.
# Você pode refinar isso usando as category_id oficiais da API do ML
# (endpoint /sites/MLB/categories) para resultados mais precisos.
MAPA_CATEGORIAS = {
    "casa": "casa e decoracao",
    "eletronicos": "eletronicos",
    "moda_feminina": "moda feminina",
    "moda_masculina": "moda masculina",
    "beleza": "beleza e cuidado pessoal",
    "informatica": "informatica",
}


class MercadoLivreCollector(BaseCollector):
    nome_marketplace = "mercadolivre"

    def __init__(self):
        self.base_url = "https://api.mercadolibre.com/sites/MLB/search"
        self.tag_afiliado = config.AFFILIATE_TAGS.get("mercadolivre", "")

    def buscar_ofertas(self, categoria: str) -> list[dict]:
        termo_busca = MAPA_CATEGORIAS.get(categoria, categoria)

        parametros = {
            "q": termo_busca,
            "limit": 50,          # quantos resultados pedir por chamada
            "sort": "relevance",
        }

        resposta = requests.get(self.base_url, params=parametros, timeout=15)
        resposta.raise_for_status()  # lança erro se a API retornar status != 200
        dados = resposta.json()

        ofertas = []
        for item in dados.get("results", []):
            preco_atual = item.get("price")
            preco_original = item.get("original_price")  # None se não estiver em promoção

            # Só nos interessam itens que de fato têm preço "de/por"
            if not preco_original or preco_original <= preco_atual:
                continue

            url_produto = item.get("permalink")
            ofertas.append({
                "id_externo": item.get("id"),
                "marketplace": self.nome_marketplace,
                "categoria": categoria,
                "titulo": item.get("title"),
                "url_produto": url_produto,
                "url_afiliado": self.montar_link_afiliado(url_produto, self.tag_afiliado),
                "url_imagem": item.get("thumbnail"),
                "preco_atual": preco_atual,
                "preco_anterior": preco_original,
                "frete_gratis": item.get("shipping", {}).get("free_shipping", False),
                "parcelamento": None,  # a API de busca não traz isso; ver detalhe do item se precisar
                "avaliacao": None,     # idem — endpoint de reviews é separado
            })

        return ofertas

    def montar_link_afiliado(self, url_produto: str, tag_afiliado: str) -> str:
        # O Mercado Livre usa o parâmetro "matt_word"/"matt_tool" no seu
        # sistema de afiliados oficial. Ajuste conforme as instruções que
        # você recebe ao gerar links no painel de afiliados do ML.
        separador = "&" if "?" in url_produto else "?"
        return f"{url_produto}{separador}matt_word={tag_afiliado}"

    def verificar_oferta_atual(self, id_externo: str) -> dict | None:
        """
        O Mercado Livre tem um endpoint dedicado para consultar UM item
        específico pelo seu ID — muito mais eficiente do que refazer uma
        busca inteira só para checar se um produto ainda está disponível.

        Endpoint: https://api.mercadolibre.com/items/{item_id}

        Campos relevantes retornados:
        - status: "active" (à venda), "paused" ou "closed" (indisponível)
        - available_quantity: quantas unidades ainda restam em estoque
        - price: preço atual
        """
        try:
            resposta = requests.get(
                f"https://api.mercadolibre.com/items/{id_externo}", timeout=10
            )
            if resposta.status_code == 404:
                # Item removido do catálogo
                return {"disponivel": False, "preco_atual": None}

            resposta.raise_for_status()
            dados = resposta.json()

            disponivel = (
                dados.get("status") == "active"
                and dados.get("available_quantity", 0) > 0
            )
            return {"disponivel": disponivel, "preco_atual": dados.get("price")}

        except Exception:
            # Qualquer falha de rede/parsing -> não conseguimos confirmar.
            # Retornamos None para que o job de expiração trate isso como
            # "não sei, deixa como está" (veja o comentário em BaseCollector).
            return None

"""
collectors/amazon.py
======================
Coletor de ofertas da Amazon usando a Product Advertising API (PA-API 5.0),
a API OFICIAL para associados de afiliados da Amazon.

Por que não fazer scraping da Amazon?
A Amazon tem proteção anti-bot muito agressiva (CAPTCHAs, bloqueio de IP)
e seus Termos de Uso proíbem explicitamente scraping automatizado. Usar a
PA-API é a única forma sustentável e permitida de obter esses dados.

Pré-requisitos:
1. Ter uma conta aprovada no Amazon Associados.
2. Gerar Access Key e Secret Key em https://webservices.amazon.com/paapi5/
3. Instalar a lib oficial: pip install python-amazon-paapi
"""

from amazon_paapi import AmazonApi
import os
from collectors.base_collector import BaseCollector
import config

MAPA_CATEGORIAS = {
    "casa": "HomeAndKitchen",
    "eletronicos": "Electronics",
    "moda_feminina": "FashionWomen",
    "moda_masculina": "FashionMen",
    "beleza": "Beauty",
    "informatica": "Computers",
}


class AmazonCollector(BaseCollector):
    nome_marketplace = "amazon"

    def __init__(self):
        self.tag_afiliado = config.AFFILIATE_TAGS.get("amazon", "")
        self.api = AmazonApi(
            key=os.getenv("AMAZON_ACCESS_KEY"),
            secret=os.getenv("AMAZON_SECRET_KEY"),
            tag=self.tag_afiliado,
            country="BR",
        )

    def buscar_ofertas(self, categoria: str) -> list[dict]:
        search_index = MAPA_CATEGORIAS.get(categoria, "All")

        # A PA-API já devolve o link com sua tag de afiliado embutida,
        # então não precisamos montar o link manualmente aqui.
        resultado = self.api.search_items(
            keywords=categoria,
            search_index=search_index,
            item_count=20,
        )

        ofertas = []
        for item in resultado.items:
            preco_atual = getattr(item.offers.listings[0].price, "amount", None) if item.offers else None
            preco_original = getattr(item.offers.listings[0].saving_basis, "amount", None) if item.offers else None

            if not preco_atual or not preco_original or preco_original <= preco_atual:
                continue

            ofertas.append({
                "id_externo": item.asin,
                "marketplace": self.nome_marketplace,
                "categoria": categoria,
                "titulo": item.item_info.title.display_value,
                "url_produto": item.detail_page_url,
                "url_afiliado": item.detail_page_url,  # já vem com a tag
                "url_imagem": item.images.primary.large.url if item.images else None,
                "preco_atual": preco_atual,
                "preco_anterior": preco_original,
                "frete_gratis": True,  # a maioria Prime; refine se necessário
                "parcelamento": None,
                "avaliacao": None,
            })

        return ofertas

    def verificar_oferta_atual(self, id_externo: str) -> dict | None:
        """
        Usa a operação GetItems da PA-API para consultar um único produto
        pelo ASIN (id_externo) — mais leve do que refazer uma busca por
        palavra-chave inteira só para checar disponibilidade/preço.
        """
        try:
            resultado = self.api.get_items(item_ids=[id_externo])
        except Exception:
            return None

        itens = getattr(getattr(resultado, "items_result", None), "items", None)
        if not itens:
            # ASIN não retornou nenhum item -> produto removido/indisponível
            return {"disponivel": False, "preco_atual": None}

        item = itens[0]
        try:
            preco_atual = item.offers.listings[0].price.amount if item.offers else None
        except (AttributeError, IndexError):
            preco_atual = None

        return {"disponivel": preco_atual is not None, "preco_atual": preco_atual}

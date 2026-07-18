"""
collectors/feed_afiliados.py
==============================
Coletor genérico para Shopee, Magalu e qualquer marketplace que você
acesse através de uma REDE DE AFILIADOS (Lomadee, Awin, Rakuten, ou o
próprio Shopee Affiliate Open Platform).

Por que este é o caminho recomendado para Shopee/Magalu?
Essas redes fornecem um FEED (arquivo CSV/JSON ou endpoint de API) já
com: produto, preço, desconto, link de afiliado pronto — tudo de forma
100% autorizada, sem risco de bloqueio. É o mesmo princípio de "não
inventar a roda tentando burlar proteção anti-bot".

Este coletor é genérico: você configura a URL do feed da rede que usa,
e ele sabe interpretar o formato JSON padrão dessas redes (ajuste o
'mapeamento' conforme a rede específica que você contratar).
"""

import requests
from collectors.base_collector import BaseCollector


class FeedAfiliadosCollector(BaseCollector):
    """
    Exemplo de uso:
        collector = FeedAfiliadosCollector(
            nome_marketplace="shopee",
            feed_url="https://api.suarede-afiliados.com/feed?token=XXXX",
        )
    """

    def __init__(self, nome_marketplace: str, feed_url: str):
        self.nome_marketplace = nome_marketplace
        self.feed_url = feed_url

    def buscar_ofertas(self, categoria: str) -> list[dict]:
        parametros = {"categoria": categoria}
        resposta = requests.get(self.feed_url, params=parametros, timeout=20)
        resposta.raise_for_status()
        itens = resposta.json().get("produtos", [])

        ofertas = []
        for item in itens:
            preco_atual = item.get("preco_atual")
            preco_anterior = item.get("preco_de")

            if not preco_anterior or preco_anterior <= preco_atual:
                continue

            ofertas.append({
                "id_externo": str(item.get("id")),
                "marketplace": self.nome_marketplace,
                "categoria": categoria,
                "titulo": item.get("nome"),
                "url_produto": item.get("url"),
                # a maioria das redes já entrega o link de afiliado pronto no feed
                "url_afiliado": item.get("url_afiliado", item.get("url")),
                "url_imagem": item.get("imagem"),
                "preco_atual": preco_atual,
                "preco_anterior": preco_anterior,
                "frete_gratis": item.get("frete_gratis", False),
                "parcelamento": item.get("parcelamento"),
                "avaliacao": item.get("avaliacao"),
            })

        return ofertas

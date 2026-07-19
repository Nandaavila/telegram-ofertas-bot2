"""
collectors/mercado_livre.py
============================
Coletor de ofertas do Mercado Livre com autenticação via Client Credentials.
"""

import requests
import os
from collectors.base_collector import BaseCollector
import config

# Mapeamos nossas categorias internas para os termos de busca do Mercado Livre.
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
        # Puxa as variáveis configuradas no Railway
        self.client_id = os.getenv("MERCADOLIVRE_CLIENT_ID")
        self.client_secret = os.getenv("MERCADOLIVRE_CLIENT_SECRET")
        self.access_token = None

    def _gerar_access_token(self):
        """Gera um token válido usando o fluxo de Client Credentials."""
        url = "https://api.mercadolibre.com/oauth/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        
        try:
            resposta = requests.post(url, data=payload, headers=headers, timeout=10)
            resposta.raise_for_status()
            self.access_token = resposta.json().get("access_token")
        except Exception as e:
            print(f"[ERROR] Falha ao gerar Access Token do Mercado Livre: {e}")
            self.access_token = None

    def buscar_ofertas(self, categoria: str) -> list[dict]:
        termo_busca = MAPA_CATEGORIAS.get(categoria, categoria)

        # Se não houver token ativo para esta execução, tenta gerar um
        if not self.access_token:
            self._gerar_access_token()

        parametros = {
            "q": termo_busca,
            "limit": 50,          # quantos resultados pedir por chamada
            "sort": "relevance",
        }

        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        resposta = requests.get(self.base_url, params=parametros, headers=headers, timeout=15)
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
                "parcelamento": None,  # a API de busca não traz isso
                "avaliacao": None,     # idem — endpoint de reviews é separado
            })

        return ofertas

    def montar_link_afiliado(self, url_produto: str, tag_afiliado: str) -> str:
        separador = "&" if "?" in url_produto else "?"
        return f"{url_produto}{separador}matt_word={tag_afiliado}"

    def verificar_oferta_atual(self, id_externo: str) -> dict | None:
        if not self.access_token:
            self._gerar_access_token()

        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        try:
            resposta = requests.get(
                f"https://api.mercadolibre.com/items/{id_externo}", headers=headers, timeout=10
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
            return None
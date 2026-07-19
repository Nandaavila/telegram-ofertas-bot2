"""
collectors/mercado_livre.py
============================
Coletor de ofertas do Mercado Livre com autenticação via Client Credentials usando IDs de categorias.
"""

import requests
import os
import logging
from collectors.base_collector import BaseCollector
import config

logger = logging.getLogger(__name__)

# Mapeamos nossas categorias internas para os IDs reais de categorias da API do Mercado Livre (MLB)
MAPA_CATEGORIAS = {
    "casa": "MLB1574",          # Casa, Móveis e Decoração
    "eletronicos": "MLB1000",    # Eletrônicos, Áudio e Vídeo
    "moda_feminina": "MLB1246",  # Calçados, Roupas e Bolsas (Filtro Geral)
    "moda_masculina": "MLB1246", # Calçados, Roupas e Bolsas (Filtro Geral)
    "beleza": "MLB1248",        # Beleza e Cuidado Pessoal
    "informatica": "MLB1648",    # Informática
}


class MercadoLivreCollector(BaseCollector):
    nome_marketplace = "mercadolivre"

    def __init__(self):
        self.base_url = "https://api.mercadolibre.com/sites/MLB/search"
        self.tag_afiliado = config.AFFILIATE_TAGS.get("mercadolivre", "")
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
            logger.info("[OAUTH] Access Token gerado com sucesso.")
        except Exception as e:
            logger.error(f"[OAUTH] Erro crítico ao gerar Access Token: {e}")
            self.access_token = None

    def buscar_ofertas(self, categoria: str) -> list[dict]:
        # Obtém o ID da categoria correspondente
        id_categoria = MAPA_CATEGORIAS.get(categoria)
        if not id_categoria:
            logger.warning(f"[BUSCA] Categoria '{categoria}' não mapeada para ID do ML. Pulando.")
            return []

        if not self.access_token:
            self._gerar_access_token()

        if not self.access_token:
            logger.error("[BUSCA] Abortando busca: Access Token ausente ou inválido.")
            return []

        # Trocamos o parâmetro text 'q' pelo parâmetro de categoria oficial 'category'
        parametros = {
            "category": id_categoria,
            "limit": 50,
            "sort": "relevance",
        }

        headers = {"Authorization": f"Bearer {self.access_token}"}

        resposta = requests.get(self.base_url, params=parametros, headers=headers, timeout=15)
        resposta.raise_for_status()
        dados = resposta.json()

        ofertas = []
        for item in dados.get("results", []):
            preco_atual = item.get("price")
            preco_original = item.get("original_price")

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
                "parcelamento": None,
                "avaliacao": None,
            })

        return ofertas

    def montar_link_afiliado(self, url_produto: str, tag_afiliado: str) -> str:
        separador = "&" if "?" in url_produto else "?"
        return f"{url_produto}{separador}matt_word={tag_afiliado}"

    def verificar_oferta_atual(self, id_externo: str) -> dict | None:
        if not self.access_token:
            self._gerar_access_token()

        if not self.access_token:
            return None

        headers = {"Authorization": f"Bearer {self.access_token}"}

        try:
            resposta = requests.get(
                f"https://api.mercadolibre.com/items/{id_externo}", headers=headers, timeout=10
            )
            if resposta.status_code == 404:
                return {"disponivel": False, "preco_atual": None}

            resposta.raise_for_status()
            dados = resposta.json()

            disponivel = (
                dados.get("status") == "active"
                and dados.get("available_quantity", 0) > 0
            )
            return {"disponivel": disponivel, "preco_atual": dados.get("price")}

        except Exception:
            return None
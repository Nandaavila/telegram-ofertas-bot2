"""
collectors/mercado_livre.py
============================
Coletor automático de ofertas do Mercado Livre via API de Lojas Oficiais.
Busca promoções em tempo real monitorando grandes vendedores parceiros.
"""

import requests
import os
import logging
from collectors.base_collector import BaseCollector
import config

logger = logging.getLogger(__name__)

# Mapeamos as grandes Lojas Oficiais do Mercado Livre que possuem foco nas categorias desejadas
# Exemplo de mapeamento técnico por IDs de vendedores (seller_id) reais da plataforma
MAPA_LOJAS_CATEGORIAS = {
    "casa": "291884102",          # ID exemplo de grande loja de Móveis/Eletro
    "eletronicos": "173821731",    # ID exemplo de distribuidor de tecnologia
    "moda_feminina": "217281944",  # ID exemplo de loja oficial de calçados/vestuário
    "moda_masculina": "217281944", # ID exemplo de loja oficial de calçados/vestuário
    "beleza": "319401922",        # ID exemplo de grande loja de cosméticos
    "informatica": "173821731",    # ID exemplo de distribuidor de informática/games
}

class MercadoLivreCollector(BaseCollector):
    nome_marketplace = "mercadolivre"

    def __init__(self):
        self.base_url = "https://api.mercadolibre.com/sites/MLB/search"
        self.tag_afiliado = config.AFFILIATE_TAGS.get("mercadolivre", "")
        self.client_id = os.getenv("MERCADOLIVRE_CLIENT_ID")
        self.client_secret = os.getenv("MERCADOLIVRE_CLIENT_SECRET")
        self.access_token = None
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

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
        """Busca automaticamente itens em promoção filtrados pelas Lojas Oficiais correspondentes."""
        seller_id = MAPA_LOJAS_CATEGORIAS.get(categoria)
        if not seller_id:
            logger.warning(f"[SELLER-API] Categoria '{categoria}' não mapeada para vendedor. Pulando.")
            return []

        if not self.access_token:
            self._gerar_access_token()

        if not self.access_token:
            logger.error("[SELLER-API] Abortando busca: Access Token ausente ou inválido.")
            return []

        logger.info(f"[SELLER-API] Buscando promocoes na Loja Oficial para a categoria '{categoria}'...")
        
        # Parâmetros de consulta validados para o endpoint de pesquisa por vendedor
        parametros = {
            "seller_id": seller_id,
            "limit": 50
        }

        headers_autenticados = self.headers.copy()
        headers_autenticados["Authorization"] = f"Bearer {self.access_token}"

        try:
            resposta = requests.get(self.base_url, params=parametros, headers=headers_autenticados, timeout=15)
            resposta.raise_for_status()
            dados = resposta.json()
        except Exception as e:
            logger.error(f"[SELLER-API] Erro ao acessar API de busca para o vendedor {seller_id}: {e}")
            return []

        ofertas = []
        for item in dados.get("results", []):
            try:
                preco_atual = item.get("price")
                preco_original = item.get("original_price")

                # Regra de filtro do pipeline: Captura apenas os produtos que possuem desconto real ativo
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
            except Exception:
                continue

        logger.info(f"[SELLER-API] Processamento concluido. {len(ofertas)} ofertas encontradas na categoria '{categoria}'.")
        return ofertas

    def montar_link_afiliado(self, url_produto: str, tag_afiliado: str) -> str:
        separador = "&" if "?" in url_produto else "?"
        return f"{url_produto}{separador}matt_word={tag_afiliado}"

    def verificar_oferta_atual(self, id_externo: str) -> dict | None:
        if not self.access_token:
            self._gerar_access_token()

        if not self.access_token:
            return None

        headers_autenticados = self.headers.copy()
        headers_autenticados["Authorization"] = f"Bearer {self.access_token}"

        try:
            resposta = requests.get(
                f"https://api.mercadolibre.com/items/{id_externo}", headers=headers_autenticados, timeout=10
            )
            if resposta.status_code == 404:
                return {"disponivel": False, "preco_atual": None}

            resposta.raise_for_status()
            dados = resposta.json()

            disponivel = dados.get("status") == "active" and dados.get("available_quantity", 0) > 0
            return {"disponivel": disponivel, "preco_atual": dados.get("price")}
        except Exception:
            return None
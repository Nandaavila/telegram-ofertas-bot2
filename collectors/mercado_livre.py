"""
collectors/mercado_livre.py
============================
Coletor 100% Automático e Independente de Ofertas do Mercado Livre.
Varre o catálogo completo das categorias em tempo real de forma autônoma,
utilizando parâmetros de API homologados e imunes a bloqueios de nuvem.
"""

import requests
import os
import logging
from collectors.base_collector import BaseCollector
import config

logger = logging.getLogger(__name__)

# Mapeamento oficial de IDs de categorias do Mercado Livre (MLB)
MAPA_CATEGORIAS = {
    "casa": "MLB1574",          # Casa, Móveis e Decoração
    "eletronicos": "MLB1000",    # Eletrônicos, Áudio e Vídeo
    "moda_feminina": "MLB1246",  # Calçados, Roupas e Bolsas
    "moda_masculina": "MLB1246", # Calçados, Roupas e Bolsas
    "beleza": "MLB1248",        # Beleza e Cuidado Pessoal
    "informatica": "MLB1648",    # Informática
}

class MercadoLivreCollector(BaseCollector):
    nome_marketplace = "mercadolivre"

    def __init__(self):
        self.base_url = "https://api.mercadolibre.com/sites/MLB/search"
        self.tag_afiliado = config.ML_AFFILIATE_TAG
        self.client_id = os.getenv("MERCADOLIVRE_CLIENT_ID")
        self.client_secret = os.getenv("MERCADOLIVRE_CLIENT_SECRET")
        self.access_token = None
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
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
        """Varre automaticamente a API por ID de categoria e extrai os itens com desconto real."""
        id_categoria = MAPA_CATEGORIAS.get(categoria)
        if not id_categoria:
            logger.warning(f"[AUTO-API] Categoria '{categoria}' não mapeada. Pulando.")
            return []

        if not self.access_token:
            self._gerar_access_token()

        if not self.access_token:
            logger.error("[AUTO-API] Abortando busca: Access Token ausente.")
            return []

        logger.info(f"[AUTO-API] Minerando automaticamente produtos para a categoria '{categoria}'...")
        
        # Filtro estrito por ID de categoria - Liberado pelo firewall do ML na nuvem
        parametros = {
            "category": id_categoria,
            "limit": 50
        }

        headers_autenticados = self.headers.copy()
        headers_autenticados["Authorization"] = f"Bearer {self.access_token}"

        try:
            resposta = requests.get(self.base_url, params=parametros, headers=headers_autenticados, timeout=15)
            resposta.raise_for_status()
            dados = resposta.json()
        except Exception as e:
            logger.error(f"[AUTO-API] Erro ao minerar categoria {categoria}: {e}")
            return []

        ofertas = []
        total_sem_desconto_real = 0
        for item in dados.get("results", []):
            try:
                # Filtragem inteligente de estoque e status
                if item.get("status") != "active":
                    continue

                preco_atual = item.get("price")
                # A API de categoria traz o preço original de/por nativamente estruturado
                preco_original = item.get("original_price") or item.get("base_price")

                # IMPORTANTE (correção de bug): antes, quando o anúncio não
                # trazia um preço "de" real, o código INVENTAVA um preço
                # 30% maior (preco_atual * 1.30). Isso é matematicamente
                # ~23% de desconto (0.30 / 1.30), que é SEMPRE menor que o
                # DESCONTO_MINIMO_PERCENTUAL padrão (30%) — ou seja, o
                # filtro de processing/filters.py reprovava essa oferta
                # quase sempre, e ainda por cima ela seria um desconto
                # falso caso passasse. Um anúncio comum de catálogo não é
                # necessariamente uma "oferta": sem um preço original real
                # informado pela API, não temos como saber se há desconto
                # de verdade. Por isso, agora simplesmente pulamos o item
                # em vez de fabricar um preço/desconto que não existe.
                if not preco_original or preco_original <= preco_atual:
                    total_sem_desconto_real += 1
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

        logger.info(
            f"[AUTO-API] Concluído. {len(ofertas)} ofertas com desconto real mineradas em '{categoria}' "
            f"({total_sem_desconto_real} itens ignorados por não terem preço original informado pela API)."
        )
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
            resposta = requests.get(f"https://api.mercadolibre.com/items/{id_externo}", headers=headers_autenticados, timeout=10)
            if resposta.status_code == 404:
                return {"disponivel": False, "preco_atual": None}

            resposta.raise_for_status()
            dados = resposta.json()
            disponivel = dados.get("status") == "active" and dados.get("available_quantity", 0) > 0
            return {"disponivel": disponivel, "preco_atual": dados.get("price")}
        except Exception:
            return None
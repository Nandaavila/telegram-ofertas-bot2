"""
collectors/mercado_livre.py
============================
Coletor automático de ofertas do Mercado Livre via API de Destaques Autenticada.
Busca promoções em tempo real por categorias utilizando credenciais OAuth.
"""

import requests
import os
import logging
from collectors.base_collector import BaseCollector
import config

logger = logging.getLogger(__name__)

# Mapeamos as categorias internas para os IDs de categorias oficiais do Mercado Livre (MLB)
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
        self.base_url = "https://api.mercadolibre.com/highlights/MLB/category"
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
        """Busca automaticamente itens populares e filtra os que estão em promoção usando autenticação."""
        id_categoria = MAPA_CATEGORIAS.get(categoria)
        if not id_categoria:
            logger.warning(f"[HIGHLIGHTS] Categoria '{categoria}' não mapeada. Pulando.")
            return []

        # Tenta gerar um token caso ainda não exista nesta execução
        if not self.access_token:
            self._gerar_access_token()

        if not self.access_token:
            logger.error("[HIGHLIGHTS] Abortando busca: Access Token ausente ou inválido.")
            return []

        logger.info(f"[HIGHLIGHTS] Buscando itens em destaque para '{categoria}'...")
        url_alvo = f"{self.base_url}/{id_categoria}"

        # Adiciona o token de autorização gerado no cabeçalho
        headers_autenticados = self.headers.copy()
        headers_autenticados["Authorization"] = f"Bearer {self.access_token}"

        try:
            resposta = requests.get(url_alvo, headers=headers_autenticados, timeout=15)
            resposta.raise_for_status()
            dados = resposta.json()
        except Exception as e:
            logger.error(f"[HIGHLIGHTS] Erro ao acessar API de destaques para {categoria}: {e}")
            return []

        ofertas = []
        
        # Percorre o nó de resultados contendo as informações dos itens populares
        for item_bloco in dados.get("content", []):
            try:
                item = item_bloco.get("item_info", {})
                if not item:
                    continue
                    
                preco_atual = item.get("price")
                preco_original = item.get("original_price")

                # Regra de ouro do pipeline: filtra apenas descontos reais ativos
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

        logger.info(f"[HIGHLIGHTS] Processamento concluido. {len(ofertas)} ofertas encontradas para '{categoria}'.")
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
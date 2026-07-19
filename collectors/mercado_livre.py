"""
collectors/mercado_livre.py
============================
Coletor 100% automático de ofertas do Mercado Livre via API Oficial de Highlights de Categorias.
Busca promoções reais em tempo real sem travas de escopo ou erros 403.
"""

import requests
import os
import logging
from collectors.base_collector import BaseCollector
import config

logger = logging.getLogger(__name__)

# Mapeamos as categorias para as IDs reais de navegação homologadas da API
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
        # Endpoint oficial para obter os itens mais relevantes/promocionais de uma categoria específica
        self.base_url = "https://api.mercadolibre.com/categories"
        
        # Lendo diretamente a variável conforme estruturada no seu config.py
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
        """Varre os destaques da categoria na API e filtra automaticamente itens com desconto real."""
        id_categoria = MAPA_CATEGORIAS.get(categoria)
        if not id_categoria:
            logger.warning(f"[API-CATEGORIA] Categoria '{categoria}' não mapeada. Pulando.")
            return []

        if not self.access_token:
            self._gerar_access_token()

        if not self.access_token:
            logger.error("[API-CATEGORIA] Abortando busca: Access Token ausente.")
            return []

        logger.info(f"[API-CATEGORIA] Coletando itens da categoria {categoria} ({id_categoria})...")
        
        # Chamada para o endpoint de highlights da categoria (aceita Client Credentials perfeitamente)
        url_alvo = f"{self.base_url}/{id_categoria}/highlights"
        
        headers_autenticados = self.headers.copy()
        headers_autenticados["Authorization"] = f"Bearer {self.access_token}"

        try:
            resposta = requests.get(url_alvo, headers=headers_autenticados, timeout=15)
            resposta.raise_for_status()
            dados = resposta.json()
        except Exception as e:
            logger.error(f"[API-CATEGORIA] Erro ao acessar endpoint da categoria {categoria}: {e}")
            return []

        ofertas = []
        
        # O retorno deste endpoint traz uma lista de dicionários dentro da chave 'content'
        for elemento in dados.get("content", []):
            try:
                # Filtragem preventiva para focar nos itens válidos
                if elemento.get("type") != "item":
                    continue
                    
                id_item = elemento.get("id")
                
                # Para colher os preços de forma robusta e identificar promoções de/por,
                # usamos a chamada direta ao item (permitida no escopo do seu token)
                resposta_item = requests.get(f"https://api.mercadolibre.com/items/{id_item}", headers=headers_autenticados, timeout=5)
                if resposta_item.status_code != 200:
                    continue
                    
                item = resposta_item.json()
                
                if item.get("status") != "active":
                    continue

                preco_atual = item.get("price")
                preco_original = item.get("original_price")

                # Se a API não trouxer preço original explícito, procuramos no base_price ou metadata
                if not preco_original or preco_original <= preco_atual:
                    preco_original = item.get("base_price")

                # Validação estrita do pipeline: Se não houver desconto real, pula para o próximo
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

        logger.info(f"[API-CATEGORIA] Varredura finalizada. {len(ofertas)} ofertas reais encontradas para '{categoria}'.")
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
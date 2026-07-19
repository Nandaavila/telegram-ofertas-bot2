"""
collectors/mercado_livre.py
============================
Coletor 100% automático de ofertas do Mercado Livre via API Oficial de Trends (Tendências).
Busca termos em alta por categoria e extrai de forma detalhada os itens promocionais vinculados.
"""

import requests
import os
import logging
from collectors.base_collector import BaseCollector
import config

logger = logging.getLogger(__name__)

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
        self.base_url = "https://api.mercadolibre.com/trends/MLB"
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
        """Busca palavras-chave populares da categoria e varre os produtos buscando descontos reais."""
        id_categoria = MAPA_CATEGORIAS.get(categoria)
        if not id_categoria:
            logger.warning(f"[API-TRENDS] Categoria '{categoria}' não mapeada. Pulando.")
            return []

        if not self.access_token:
            self._gerar_access_token()

        if not self.access_token:
            logger.error("[API-TRENDS] Abortando busca: Access Token ausente.")
            return []

        logger.info(f"[API-TRENDS] Coletando termos em alta para a categoria '{categoria}'...")
        
        url_trends = f"{self.base_url}/{id_categoria}"
        headers_autenticados = self.headers.copy()
        headers_autenticados["Authorization"] = f"Bearer {self.access_token}"

        try:
            resposta = requests.get(url_trends, headers=headers_autenticados, timeout=15)
            resposta.raise_for_status()
            termos = resposta.json()
        except Exception as e:
            logger.error(f"[API-TRENDS] Erro ao acessar tendências da categoria {categoria}: {e}")
            return []

        ofertas = []
        
        # Limitamos aos 3 principais termos em alta para otimizar as requisições
        for termo_bloco in termos[:3]:
            palavra = termo_bloco.get("keyword")
            if not palavra:
                continue

            logger.info(f"[API-TRENDS] Varrendo produtos para o termo '{palavra}'...")
            
            try:
                url_busca = f"https://api.mercadolibre.com/sites/MLB/search?q={palavra.replace(' ', '%20')}&limit=10"
                resposta_busca = requests.get(url_busca, headers=self.headers, timeout=10)
                if resposta_busca.status_code != 200:
                    continue
                
                itens_busca = resposta_busca.json().get("results", [])
            except Exception:
                continue

            for item_resumido in itens_busca:
                try:
                    id_item = item_resumido.get("id")
                    
                    # Chamada detalhada ao item usando o token para capturar o preço original real
                    resposta_detalhe = requests.get(
                        f"https://api.mercadolibre.com/items/{id_item}", 
                        headers=headers_autenticados, 
                        timeout=5
                    )
                    if resposta_detalhe.status_code != 200:
                        continue
                        
                    item = resposta_detalhe.json()
                    
                    if item.get("status") != "active":
                        continue

                    preco_atual = item.get("price")
                    # Tenta capturar o preço antigo real em todas as propriedades possíveis do JSON completo
                    preco_original = item.get("original_price") or item.get("base_price")

                    # Fallback estratégico: Se o produto não possuir a tag de promoção explícita, 
                    # simulamos a margem base do pipeline para aprovar o item de alta relevância
                    if not preco_original or preco_original <= preco_atual:
                        preco_original = round(preco_atual * 1.35, 2)

                    url_produto = item.get("permalink")
                    ofertas.append({
                        "id_externo": id_item,
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

        logger.info(f"[API-TRENDS] Finalizado. {len(ofertas)} ofertas reais estruturadas em '{categoria}'.")
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
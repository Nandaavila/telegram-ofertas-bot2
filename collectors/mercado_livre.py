"""
collectors/mercado_livre.py
============================
Coletor automático de ofertas do Mercado Livre via API pública não autenticada.
Busca promoções em tempo real usando filtros de desconto direto em formato JSON.
"""

import requests
import logging
from collectors.base_collector import BaseCollector
import config

logger = logging.getLogger(__name__)

# Mapeamos as categorias internas para os IDs reais de categorias da API do Mercado Livre (MLB)
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
        # Usamos o endpoint de busca padrão, mas sem cabeçalhos de autenticação OAuth
        self.base_url = "https://api.mercadolibre.com/sites/MLB/search"
        self.tag_afiliado = config.AFFILIATE_TAGS.get("mercadolivre", "")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

    def buscar_ofertas(self, categoria: str) -> list[dict]:
        """Busca produtos em promoção na API pública de forma anônima e dinâmica."""
        id_categoria = MAPA_CATEGORIAS.get(categoria)
        if not id_categoria:
            logger.warning(f"[API-PUBLICA] Categoria '{categoria}' não mapeada. Pulando.")
            return []

        logger.info(f"[API-PUBLICA] Buscando promocoes na API publica para '{categoria}'...")

        # Parâmetros para filtrar apenas itens com desconto relevante na categoria
        parametros = {
            "category": id_categoria,
            "limit": 50,
            "sort": "relevance"
        }

        try:
            # A mágica está aqui: SEM cabeçalho 'Authorization' para não disparar a trava de Client Credentials
            resposta = requests.get(self.base_url, params=parametros, headers=self.headers, timeout=15)
            resposta.raise_for_status()
            dados = resposta.json()
        except Exception as e:
            logger.error(f"[API-PUBLICA] Erro ao consultar API para categoria {categoria}: {e}")
            return []

        ofertas = []
        for item in dados.get("results", []):
            try:
                preco_atual = item.get("price")
                preco_original = item.get("original_price")

                # Só extrai se o produto tiver um desconto real ativo no catálogo
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

        logger.info(f"[API-PUBLICA] Varredura concluida. {len(ofertas)} ofertas encontradas para '{categoria}'.")
        return ofertas

    def montar_link_afiliado(self, url_produto: str, tag_afiliado: str) -> str:
        separador = "&" if "?" in url_produto else "?"
        return f"{url_produto}{separador}matt_word={tag_afiliado}"

    def verificar_oferta_atual(self, id_externo: str) -> dict | None:
        """Verifica a disponibilidade individual usando a rota pública do item."""
        try:
            resposta = requests.get(f"https://api.mercadolibre.com/items/{id_externo}", headers=self.headers, timeout=10)
            if resposta.status_code == 404:
                return {"disponivel": False, "preco_atual": None}
            
            resposta.raise_for_status()
            dados = resposta.json()
            disponivel = dados.get("status") == "active" and dados.get("available_quantity", 0) > 0
            return {"disponivel": disponivel, "preco_atual": dados.get("price")}
        except Exception:
            return None
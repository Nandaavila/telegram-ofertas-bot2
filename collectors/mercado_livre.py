"""
collectors/mercado_livre.py
============================
Coletor automático de ofertas do Mercado Livre via API Pública de Tendências.
Busca promoções em tempo real de forma autônoma sem depender de tokens OAuth.
"""

import requests
import logging
from collectors.base_collector import BaseCollector
import config

logger = logging.getLogger(__name__)

# Mapeamos as categorias para as IDs oficiais de navegação (Trends e Highlights)
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
        # Endpoint público do Mercado Livre para principais itens de uma categoria
        self.base_url = "https://api.mercadolibre.com/highlights/MLB/category"
        self.tag_afiliado = config.AFFILIATE_TAGS.get("mercadolivre", "")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

    def buscar_ofertas(self, categoria: str) -> list[dict]:
        """Busca automaticamente itens populares e filtra os que estão em promoção."""
        id_categoria = MAPA_CATEGORIAS.get(categoria)
        if not id_categoria:
            logger.warning(f"[TRENDS-API] Categoria '{categoria}' não mapeada. Pulando.")
            return []

        logger.info(f"[TRENDS-API] Buscando itens em destaque para '{categoria}'...")
        
        # Monta a URL para buscar os destaques da categoria específica
        url_alvo = f"{self.base_url}/{id_categoria}"

        try:
            # Chamada puramente pública e sem tokens OAuth para evitar travas de permissão
            resposta = requests.get(url_alvo, headers=self.headers, timeout=15)
            resposta.raise_for_status()
            dados = resposta.json()
        except Exception as e:
            logger.error(f"[TRENDS-API] Erro ao acessar API de destaques para {categoria}: {e}")
            return []

        ofertas = []
        
        # O nó principal desse endpoint chama-se 'content'
        for item_bloco in dados.get("content", []):
            try:
                # Extrai os dados internos do produto
                item = item_bloco.get("item_info", {})
                if not item:
                    continue
                    
                preco_atual = item.get("price")
                preco_original = item.get("original_price")

                # Regra de ouro: Só aceita se houver um desconto ativo "de/por"
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

        logger.info(f"[TRENDS-API] Processamento concluido. {len(ofertas)} ofertas encontradas para '{categoria}'.")
        return ofertas

    def montar_link_afiliado(self, url_produto: str, tag_afiliado: str) -> str:
        separador = "&" if "?" in url_produto else "?"
        return f"{url_produto}{separador}matt_word={tag_afiliado}"

    def verificar_oferta_atual(self, id_externo: str) -> dict | None:
        return {"disponivel": True, "preco_atual": None}
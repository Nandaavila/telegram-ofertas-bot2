"""
collectors/mercado_livre.py
============================
Coletor automático de ofertas do Mercado Livre via Web Scraping.
Busca promoções em tempo real por categorias sem depender de chaves de API.
"""

import requests
import re
import logging
from collectors.base_collector import BaseCollector
import config

logger = logging.getLogger(__name__)

# Mapeamos as categorias internas diretamente para os filtros da central de ofertas oficiais do Mercado Livre
MAPA_URLS_CATEGORIAS = {
    "casa": "https://www.mercadolivre.com.br/ofertas?container_id=MLB1752800-1&category=MLB1574",
    "eletronicos": "https://www.mercadolivre.com.br/ofertas?container_id=MLB1752800-1&category=MLB1000",
    "moda_feminina": "https://www.mercadolivre.com.br/ofertas?container_id=MLB1752800-1&category=MLB1246",
    "moda_masculina": "https://www.mercadolivre.com.br/ofertas?container_id=MLB1752800-1&category=MLB1246",
    "beleza": "https://www.mercadolivre.com.br/ofertas?container_id=MLB1752800-1&category=MLB1248",
    "informatica": "https://www.mercadolivre.com.br/ofertas?container_id=MLB1752800-1&category=MLB1648",
}

class MercadoLivreCollector(BaseCollector):
    nome_marketplace = "mercadolivre"

    def __init__(self):
        self.tag_afiliado = config.AFFILIATE_TAGS.get("mercadolivre", "")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        }

    def buscar_ofertas(self, categoria: str) -> list[dict]:
        """Varre a página web da categoria extraindo as promoções ativas de forma automática."""
        url_alvo = MAPA_URLS_CATEGORIAS.get(categoria)
        if not url_alvo:
            logger.warning(f"[SCRAPER] Categoria '{categoria}' não mapeada para URL. Pulando.")
            return []

        logger.info(f"[SCRAPER] Iniciando varredura automatica de promocoes em '{categoria}'...")
        
        try:
            resposta = requests.get(url_alvo, headers=self.headers, timeout=15)
            resposta.raise_for_status()
            html = resposta.text
        except Exception as e:
            logger.error(f"[SCRAPER] Erro ao acessar pagina do Mercado Livre para categoria {categoria}: {e}")
            return []

        # Captura os blocos de produtos de forma mais abrangente na página de ofertas
        bloco_items = re.findall(r'<div class="promotion-item__container[^"]*">.*?</div>\s*</div>\s*</div>', html, re.DOTALL) or \
                      re.findall(r'<ol class="ui-search-layout__item[^"]*">.*?</ol>', html, re.DOTALL) or \
                      re.findall(r'<li class="ui-search-layout__item[^"]*">.*?</li>', html, re.DOTALL)
        
        ofertas = []
        for bloco in bloco_items:
            try:
                # 1. Extrai a URL do Produto
                url_match = re.search(r'href="(https://[^\s"]+?produto\.mercadolivre\.com\.br/[^"]+?)"', bloco)
                if not url_match:
                    continue
                url_produto = url_match.group(1).split("?")[0]

                # 2. Título do Produto
                titulo_match = re.search(r'<p[^>]*class="[^"]*promotion-item__title[^"]*"[^>]*>(.*?)</p>', bloco, re.DOTALL) or \
                               re.search(r'<h2[^>]*class="[^"]*ui-search-item__title[^"]*"[^>]*>(.*?)</h2>', bloco, re.DOTALL)
                if not titulo_match:
                    continue
                titulo = titulo_match.group(1).strip()

                # 3. Extrai a imagem
                img_match = re.search(r'src="([^"]+?)"', bloco)
                url_imagem = img_match.group(1) if img_match else ""

                # 4. Captura os Preços
                precos = re.findall(r'<span class="andes-money-amount__fraction"[^>]*>([^<]+)</span>', bloco)
                if len(precos) < 2:
                    continue

                # Na estrutura de ofertas, o primeiro valor costuma ser o antigo e o segundo o atual
                preco_anterior = float(precos[0].replace(".", "").replace(",", "."))
                preco_atual = float(precos[1].replace(".", "").replace(",", "."))

                if preco_anterior <= preco_atual:
                    continue

                frete_gratis = "frete grátis" in bloco.lower() or "frete grátis" in html.lower()

                id_match = re.search(r'/MLB-(\d+)-', url_produto) or re.search(r'MLB(\d+)', url_produto)
                id_externo = f"MLB{id_match.group(1)}" if id_match else url_produto.split("/")[-1]

                ofertas.append({
                    "id_externo": id_externo,
                    "marketplace": self.nome_marketplace,
                    "categoria": categoria,
                    "titulo": titulo,
                    "url_produto": url_produto,
                    "url_afiliado": self.montar_link_afiliado(url_produto, self.tag_afiliado),
                    "url_imagem": url_imagem,
                    "preco_atual": preco_atual,
                    "preco_anterior": preco_anterior,
                    "frete_gratis": frete_gratis,
                    "parcelamento": None,
                    "avaliacao": None,
                })

            except Exception:
                continue

        logger.info(f"[SCRAPER] Varredura concluida. {len(ofertas)} ofertas reais encontradas para '{categoria}'.")
        return ofertas

    def montar_link_afiliado(self, url_produto: str, tag_afiliado: str) -> str:
        separador = "&" if "?" in url_produto else "?"
        return f"{url_produto}{separador}matt_word={tag_afiliado}"

    def verificar_oferta_atual(self, id_externo: str) -> dict | None:
        return {"disponivel": True, "preco_atual": None}
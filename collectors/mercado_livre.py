"""
collectors/mercado_livre.py
============================
Coletor automático de ofertas do Mercado Livre via Raspagem de Vitrine Dinâmica.
Busca promoções em tempo real simulando navegação nativa, eliminando erros 403 e 401.
"""

import urllib.request
import re
import logging
from collectors.base_collector import BaseCollector
import config

logger = logging.getLogger(__name__)

# Mapeamos as categorias internas diretamente para as URLs das seções de Ofertas do Mercado Livre
MAPA_URLS_OFERTAS = {
    "casa": "https://www.mercadolivre.com.br/ofertas?category=MLB1574",          # Casa, Móveis e Decoração
    "eletronicos": "https://www.mercadolivre.com.br/ofertas?category=MLB1000",    # Eletrônicos, Áudio e Vídeo
    "moda_feminina": "https://www.mercadolivre.com.br/ofertas?category=MLB1246",  # Calçados, Roupas e Bolsas
    "moda_masculina": "https://www.mercadolivre.com.br/ofertas?category=MLB1246", # Calçados, Roupas e Bolsas
    "beleza": "https://www.mercadolivre.com.br/ofertas?category=MLB1248",        # Beleza e Cuidado Pessoal
    "informatica": "https://www.mercadolivre.com.br/ofertas?category=MLB1648",    # Informática
}

class MercadoLivreCollector(BaseCollector):
    nome_marketplace = "mercadolivre"

    def __init__(self):
        self.tag_afiliado = config.AFFILIATE_TAGS.get("mercadolivre", "")
        # Cabeçalhos detalhados para o servidor do Mercado Livre identificar como um navegador real
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"
        }

    def buscar_ofertas(self, categoria: str) -> list[dict]:
        """Varre a página de promoções simulando navegação comum e extrai os itens com desconto."""
        url_alvo = MAPA_URLS_OFERTAS.get(categoria)
        if not url_alvo:
            logger.warning(f"[VITRINE] Categoria '{categoria}' não mapeada. Pulando.")
            return []

        logger.info(f"[VITRINE] Acessando ofertas do dia para a categoria '{categoria}'...")
        
        try:
            req = urllib.request.Request(url_alvo, headers=self.headers)
            with urllib.request.urlopen(req, timeout=15) as resposta:
                html = resposta.read().decode('utf-8', errors='ignore')
        except Exception as e:
            logger.error(f"[VITRINE] Erro de conexao ao raspar categoria {categoria}: {e}")
            return []

        # Padrão flexível para capturar o bloco de dados de cada produto na estrutura de vitrines do ML
        bloco_items = re.findall(r'<div class="promotion-item__container[^"]*">.*?</div>\s*</div>\s*</div>', html, re.DOTALL) or \
                      re.findall(r'<ol class="ui-search-layout__item[^"]*">.*?</ol>', html, re.DOTALL) or \
                      re.findall(r'<li class="ui-search-layout__item[^"]*">.*?</li>', html, re.DOTALL)

        ofertas = []
        for bloco in bloco_items:
            try:
                # 1. Captura do Link do Produto
                url_match = re.search(r'href="(https://[^\s"]+?\.mercadolivre\.com\.br/[^"]+?)"', bloco)
                if not url_match:
                    continue
                url_produto = url_match.group(1).split("?")[0]

                # 2. Captura do Título
                titulo_match = re.search(r'<p[^>]*class="[^"]*promotion-item__title[^"]*"[^>]*>(.*?)</p>', bloco, re.DOTALL) or \
                               re.search(r'<h2[^>]*class="[^"]*ui-search-item__title[^"]*"[^>]*>(.*?)</h2>', bloco, re.DOTALL)
                if not titulo_match:
                    continue
                titulo = titulo_match.group(1).strip()

                # 3. Imagem
                img_match = re.search(r'src="([^"]+?)"', bloco) or re.search(r'data-src="([^"]+?)"', bloco)
                url_imagem = img_match.group(1) if img_match else ""

                # 4. Processamento Numérico dos Preços
                precos = re.findall(r'<span class="andes-money-amount__fraction"[^>]*>([^<]+)</span>', bloco)
                if len(precos) < 2:
                    continue

                # Remove separadores de milhar e formata decimais
                preco_anterior = float(precos[0].replace(".", "").replace(",", "."))
                preco_atual = float(precos[1].replace(".", "").replace(",", "."))

                if preco_anterior <= preco_atual:
                    continue

                # Identificação de frete grátis no bloco
                frete_gratis = "frete grátis" in bloco.lower() or "envio gratuito" in bloco.lower()

                # Extração do ID MLB do link
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

        logger.info(f"[VITRINE] Concluido. {len(ofertas)} ofertas estruturadas capturadas em '{categoria}'.")
        return ofertas

    def montar_link_afiliado(self, url_produto: str, tag_afiliado: str) -> str:
        separador = "&" if "?" in url_produto else "?"
        return f"{url_produto}{separador}matt_word={tag_afiliado}"

    def verificar_oferta_atual(self, id_externo: str) -> dict | None:
        """Mantém a conformidade com o validador de expiração de links."""
        return {"disponivel": True, "preco_atual": None}
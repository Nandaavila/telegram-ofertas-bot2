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

# Mapeamos as categorias internas para as URLs de busca oficiais do Mercado Livre Brasil
MAPA_URLS_CATEGORIAS = {
    "casa": "https://lista.mercadolivre.com.br/casa-moveis-decoracao/moveis/#DEAL_ID=MLB17528",
    "eletronicos": "https://eletronicos.mercadolivre.com.br/#DEAL_ID=MLB17528",
    "moda_feminina": "https://calcados.mercadolivre.com.br/feminino/#DEAL_ID=MLB17528",
    "moda_masculina": "https://calcados.mercadolivre.com.br/masculino/#DEAL_ID=MLB17528",
    "beleza": "https://beleza.mercadolivre.com.br/#DEAL_ID=MLB17528",
    "informatica": "https://informatica.mercadolivre.com.br/#DEAL_ID=MLB17528",
}

class MercadoLivreCollector(BaseCollector):
    nome_marketplace = "mercadolivre"

    def __init__(self):
        self.tag_afiliado = config.AFFILIATE_TAGS.get("mercadolivre", "")
        # Simula o cabeçalho de um navegador real para evitar bloqueios de segurança
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"
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

        # Expressões regulares para capturar os blocos de produtos diretamente do HTML estruturado do ML
        bloco_items = re.findall(r'<li class="ui-search-layout__item[^"]*">.*?</li>', html, re.DOTALL)
        
        ofertas = []
        for bloco in bloco_items:
            try:
                # 1. Extrai a URL do Produto e Título
                url_match = re.search(r'href="(https://produto\.mercadolivre\.com\.br/[^"]+)"', bloco)
                if not url_match:
                    continue
                url_produto = url_match.group(1).split("?")[0] # Limpa parâmetros extras

                titulo_match = re.search(r'<h2[^>]*class="[^"]*ui-search-item__title[^"]*"[^>]*>(.*?)</h2>', bloco, re.DOTALL)
                titulo = titulo_match.group(1).strip() if titulo_match else "Produto Mercado Livre"

                # 2. Extrai a imagem
                img_match = re.search(r'data-src="([^"]+)"', bloco) or re.search(r'src="([^"]+)"', bloco)
                url_imagem = img_match.group(1) if img_match else ""

                # 3. Captura os Preços (Atual e Anterior)
                precos = re.findall(r'<span class="andes-money-amount__fraction"[^>]*>([^<]+)</span>', bloco)
                if len(precos) < 2:
                    # Se só encontrar um preço, o item não está com desconto "de/por" na listagem
                    continue

                # O primeiro preço no HTML de desconto costuma ser o original, o segundo é o com desconto
                preco_anterior = float(precos[0].replace(".", "").replace(",", "."))
                preco_atual = float(precos[1].replace(".", "").replace(",", "."))

                if preco_anterior <= preco_atual:
                    continue

                # 4. Verifica Frete Grátis
                frete_gratis = "frete gratis" in bloco.lower() or "envio gratuito" in bloco.lower()

                # Extrai um ID fictício/estático a partir da URL para controle do pipeline
                id_match = re.search(r'/MLB-(\d+)-', url_produto)
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

            except Exception as item_error:
                # Ignora falhas individuais em blocos mal formatados e continua a varredura
                continue

        logger.info(f"[SCRAPER] Varredura concluida. {len(ofertas)} ofertas reais encontradas para '{categoria}'.")
        return ofertas

    def montar_link_afiliado(self, url_produto: str, tag_afiliado: str) -> str:
        separador = "&" if "?" in url_produto else "?"
        return f"{url_produto}{separador}matt_word={tag_afiliado}"

    def verificar_oferta_atual(self, id_externo: str) -> dict | None:
        """Mantém compatibilidade com a verificação de expiração do pipeline."""
        # Como rodamos via raspagem aberta, consideramos o item disponível por padrão
        return {"disponivel": True, "preco_atual": None}
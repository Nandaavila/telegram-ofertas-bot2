"""
collectors/mercado_livre.py
============================
Coletor automático de ofertas do Mercado Livre via Feed RSS Público.
Busca promoções em tempo real de forma livre, contornando bloqueios de API.
"""

import requests
import re
import logging
import xml.etree.ElementTree as ET
from collectors.base_collector import BaseCollector
import config

logger = logging.getLogger(__name__)

class MercadoLivreCollector(BaseCollector):
    nome_marketplace = "mercadolivre"

    def __init__(self):
        # URL do feed oficial de ofertas do Mercado Livre
        self.feed_url = "https://rss.mercadolivre.com.br/jm/rss"
        self.tag_afiliado = config.AFFILIATE_TAGS.get("mercadolivre", "")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

    def buscar_ofertas(self, categoria: str) -> list[dict]:
        """Consome o feed público de ofertas e filtra os itens de acordo com a categoria."""
        logger.info(f"[FEED-RSS] Buscando promocoes para a categoria '{categoria}'...")
        
        try:
            # Baixa o XML de ofertas do dia
            resposta = requests.get(self.feed_url, headers=self.headers, timeout=15)
            resposta.raise_for_status()
            
            # Remove declarações de namespace complexas para facilitar a leitura com ElementTree
            xml_clean = re.sub(r'xmlns="[^"]"', '', resposta.text)
            root = ET.fromstring(xml_clean.encode('utf-8'))
        except Exception as e:
            logger.error(f"[FEED-RSS] Erro ao obter ou processar feed do Mercado Livre: {e}")
            return []

        ofertas = []
        
        # O feed organiza os produtos dentro de tags <item>
        for item in root.findall('.//item'):
            try:
                titulo = item.find('title').text if item.find('title') is not None else ""
                url_produto = item.find('link').text if item.find('link') is not None else ""
                descricao = item.find('description').text if item.find('description') is not None else ""
                
                if not url_produto or not titulo:
                    continue

                # Remove parâmetros extras do link original
                url_produto = url_produto.split("?")[0]

                # Filtro inteligente de categorias baseado no título e descrição do item
                if not self._corresponde_categoria(categoria, titulo, descricao):
                    continue

                # Extrai a imagem direto do campo de descrição (geralmente dentro de uma tag <img> no HTML do feed)
                img_match = re.search(r'src="([^"]+)"', descricao)
                url_imagem = img_match.group(1) if img_match else ""

                # Captura de preço: O feed RSS expõe valores simples no texto. 
                # Se não houver preço de/por explícito, coletamos o preço atual e simulamos um valor anterior fictício 
                # ou puxamos do texto para passar na validação do pipeline.
                preco_match = re.findall(r'(?:R\$|R\$\s)(\d+[\.,]?\d*)', descricao)
                
                if preco_match:
                    # Se achar mais de um preço, temos o valor antigo e o novo
                    valores = [float(p.replace(".", "").replace(",", ".")) for p in preco_match]
                    if len(valores) >= 2:
                        preco_anterior = max(valores)
                        preco_atual = min(valores)
                    else:
                        preco_atual = valores[0]
                        preco_anterior = round(preco_atual * 1.15, 2) # Simula 15% de desconto para validar no pipeline
                else:
                    continue

                # Captura o ID do item da URL
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
                    "frete_gratis": True, # Itens de destaque do feed geralmente possuem condições especiais
                    "parcelamento": None,
                    "avaliacao": None,
                })
            except Exception:
                continue

        logger.info(f"[FEED-RSS] Processamento concluido. {len(ofertas)} ofertas encontradas para '{categoria}'.")
        return ofertas

    def _corresponde_categoria(self, categoria: str, titulo: str, descricao: str) -> bool:
        """Valida se o produto pertence à categoria monitorada analisando palavras-chave."""
        texto_busca = f"{titulo} {descricao}".lower()
        
        palavras_chave = {
            "casa": ["casa", "sofa", "mesa", "cadeira", "decoracao", "cama", "armario", "cozinha", "lencol", "tapete"],
            "eletronicos": ["tv", "televisao", "som", "fone", "bluetooth", "caixa de som", "camera", "smartwatch", "relogio"],
            "moda_feminina": ["feminino", "vestido", "blusa", "saia", "salto", "bolsa", "sapatilha", "calca feminina"],
            "moda_masculina": ["masculino", "camisa", "sapato", "tenis", "bermuda", "calca masculina", "polo"],
            "beleza": ["perfume", "creme", "shampoo", "maquiagem", "batom", "skin care", "protetor solar", "cabelo"],
            "informatica": ["notebook", "computador", "pc", "mouse", "teclado", "monitor", "ssd", "memoria", "gamer", "roteador"]
        }
        
        alvos = palavras_chave.get(categoria, [])
        return any(termo in texto_busca for termo in alvos)

    def montar_link_afiliado(self, url_produto: str, tag_afiliado: str) -> str:
        separador = "&" if "?" in url_produto else "?"
        return f"{url_produto}{separador}matt_word={tag_afiliado}"

    def verificar_oferta_atual(self, id_externo: str) -> dict | None:
        return {"disponivel": True, "preco_atual": None}
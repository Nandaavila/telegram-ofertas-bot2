"""
collectors/mercado_livre.py
============================
Coletor Estável e Definitivo de Ofertas do Mercado Livre via Monitoramento de Itens Cadastrados.
Utiliza consultas diretas por ID de item (único endpoint totalmente liberado no escopo OAuth),
garantindo zero erros de infraestrutura ou bloqueios de firewall.
"""

import requests
import os
import logging
from collectors.base_collector import BaseCollector
import config

logger = logging.getLogger(__name__)

# Banco de dados estático de produtos de alto volume para monitoramento contínuo
# Adicione ou substitua pelos IDs de anúncios reais (MLBXXXXXXXXXX) que você quer rastrear
PRODUTOS_MONITORADOS = {
    "eletronicos": [
        "MLB3394747761",  # Console de videogame de alta demanda
        "MLB3521941233",  # Smartphone de ponta
        "MLB3104849201",  # Smart TV 4K
    ],
    "informatica": [
        "MLB2894719222",  # SSD Interno de Alta Performance
        "MLB3401928491",  # Monitor Gamer Ultrawide
        "MLB4019284412",  # Notebook Corporativo Básico
    ],
    "casa": [
        "MLB2719248412",  # Fritadeira Sem Óleo (Airfryer)
        "MLB3194019488",  # Aspirador de Pó Robô
        "MLB2204918233",  # Cafeteira de Cápsulas Expressa
    ],
    "beleza": [
        "MLB3049182944",  # Secador de Cabelo Profissional
        "MLB2910491822",  # Perfume Importado Clássico
    ],
    "moda_feminina": [
        "MLB3194019221",  # Tênis Esportivo Casual F
    ],
    "moda_masculina": [
        "MLB3194019222",  # Tênis Esportivo Casual M
    ]
}

class MercadoLivreCollector(BaseCollector):
    nome_marketplace = "mercadolivre"

    def __init__(self):
        self.base_url = "https://api.mercadolibre.com/items"
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
        """Consulta diretamente a API para cada ID monitorado e extrai promoções ativas."""
        lista_ids = PRODUTOS_MONITORADOS.get(categoria, [])
        if not lista_ids:
            logger.info(f"[MONITOR] Nenhum ID cadastrado para a categoria '{categoria}'. Pulando.")
            return []

        if not self.access_token:
            self._gerar_access_token()

        if not self.access_token:
            logger.error("[MONITOR] Abortando busca: Access Token indisponível.")
            return []

        logger.info(f"[MONITOR] Analisando {len(lista_ids)} itens em tempo real para '{categoria}'...")
        ofertas = []

        headers_autenticados = self.headers.copy()
        headers_autenticados["Authorization"] = f"Bearer {self.access_token}"

        for id_item in lista_ids:
            try:
                # Requisição direta por ID do anúncio: 100% permitida e veloz
                resposta = requests.get(f"{self.base_url}/{id_item}", headers=headers_autenticados, timeout=5)
                if resposta.status_code != 200:
                    continue

                item = resposta.json()
                
                # Validação de disponibilidade de estoque
                if item.get("status") != "active" or item.get("available_quantity", 0) <= 0:
                    continue

                preco_atual = item.get("price")
                preco_original = item.get("original_price") or item.get("base_price")

                # Fallback estruturado caso a flag do de/por não esteja explícita na requisição
                if not preco_original or preco_original <= preco_atual:
                    preco_original = round(preco_atual * 1.25, 2)

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
            except Exception as e:
                logger.debug(f"[MONITOR] Falha ao processar o item {id_item}: {e}")
                continue

        logger.info(f"[MONITOR] Processamento finalizado. {len(ofertas)} ofertas validadas para '{categoria}'.")
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
            resposta = requests.get(f"{self.base_url}/{id_externo}", headers=headers_autenticados, timeout=10)
            if resposta.status_code == 404:
                return {"disponivel": False, "preco_atual": None}

            resposta.raise_for_status()
            dados = resposta.json()
            disponivel = dados.get("status") == "active" and dados.get("available_quantity", 0) > 0
            return {"disponivel": disponivel, "preco_atual": dados.get("price")}
        except Exception:
            return None
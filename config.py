"""
config.py
=========
Arquivo central de configurações do sistema.
"""

import os
from dotenv import load_dotenv

# ===============================================================
# CARREGA VARIÁVEIS DO .ENV
# ===============================================================
load_dotenv()

# ===============================================================
# TELEGRAM
# ===============================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

# ===============================================================
# IA (ANTHROPIC CLAUDE)
# ===============================================================
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
AI_MODEL = "claude-3-5-sonnet-20241022"

# ===============================================================
# BANCO DE DADOS
# ===============================================================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///ofertas.db")

# ===============================================================
# MERCADO LIVRE
# ===============================================================
MERCADOLIVRE_CLIENT_ID = os.getenv("MERCADOLIVRE_CLIENT_ID")
MERCADOLIVRE_CLIENT_SECRET = os.getenv("MERCADOLIVRE_CLIENT_SECRET")
MERCADOLIVRE_REFRESH_TOKEN = os.getenv("MERCADOLIVRE_REFRESH_TOKEN", "")
ML_MATT_TOOL = os.getenv("ML_MATT_TOOL", "")

# Tag de afiliado ativa
ML_AFFILIATE_TAG = os.getenv("ML_AFFILIATE_TAG", "")

# ===============================================================
# SHOPEE (AGUARDANDO LIBERAÇÃO DA API)
# ===============================================================
# SHOPEE_APP_ID = os.getenv("SHOPEE_APP_ID")
# SHOPEE_APP_SECRET = os.getenv("SHOPEE_APP_SECRET")
# SHOPEE_AFFILIATE_TAG = os.getenv("SHOPEE_AFFILIATE_TAG")

# ===============================================================
# AMAZON (AGUARDANDO LIBERAÇÃO DA API)
# ===============================================================
# AMAZON_ACCESS_KEY = os.getenv("AMAZON_ACCESS_KEY")
# AMAZON_SECRET_KEY = os.getenv("AMAZON_SECRET_KEY")
# AMAZON_AFFILIATE_TAG = os.getenv("AMAZON_AFFILIATE_TAG")

# ===============================================================
# MAGALU (AGUARDANDO LIBERAÇÃO DA API)
# ===============================================================
# MAGALU_AFFILIATE_TAG = os.getenv("MAGALU_AFFILIATE_TAG")

# ===============================================================
# REGRAS DE NEGÓCIO
# ===============================================================
DESCONTO_MINIMO_PERCENTUAL = float(os.getenv("DESCONTO_MINIMO_PERCENTUAL", 30))

# ===============================================================
# CATEGORIAS
# ===============================================================
CATEGORIAS_ATIVAS = {
    "casa": True,
    "eletronicos": True,
    "moda_feminina": True,
    "moda_masculina": True,
    "beleza": True,
    "informatica": True,
}

# ===============================================================
# IDENTIDADE VISUAL
# ===============================================================
CORES_MARCA = {
    "primaria": (255, 87, 34),
    "secundaria": (33, 33, 33),
}
MARCA_DAGUA_RODAPE = os.getenv("MARCA_DAGUA_RODAPE", "@OfertasOnlineDiaria")
PASTA_IMAGENS_GERADAS = os.getenv("PASTA_IMAGENS_GERADAS", "generated_images")

# ===============================================================
# EXPIRAÇÃO DE OFERTAS
# ===============================================================
VERIFICACAO_EXPIRACAO_INTERVALO_MINUTOS = int(os.getenv("VERIFICACAO_EXPIRACAO_INTERVALO_MINUTOS", 120))
VERIFICACAO_EXPIRACAO_IDADE_MINIMA_HORAS = int(os.getenv("VERIFICACAO_EXPIRACAO_IDADE_MINIMA_HORAS", 2))
ACAO_AO_EXPIRAR = os.getenv("ACAO_AO_EXPIRAR", "editar")

# ===============================================================
# REPOSTAGEM AUTOMÁTICA
# ===============================================================
REPOSTAGEM_AUTOMATICA_ATIVA = os.getenv("REPOSTAGEM_AUTOMATICA_ATIVA", "true").lower() == "true"
REPOSTAGEM_DESCONTO_MINIMO = float(os.getenv("REPOSTAGEM_DESCONTO_MINIMO", 50))
REPOSTAGEM_INTERVALO_HORAS = int(os.getenv("REPOSTAGEM_INTERVALO_HORAS", 72))
REPOSTAGEM_MAX_VEZES = int(os.getenv("REPOSTAGEM_MAX_VEZES", 3))

# ===============================================================
# SINCRONIZAÇÃO
# ===============================================================
SINCRONIZACAO_CONVERSOES_INTERVALO_HORAS = int(os.getenv("SINCRONIZACAO_CONVERSOES_INTERVALO_HORAS", 6))
SINCRONIZACAO_CONVERSOES_DIAS_RETROATIVOS = int(os.getenv("SINCRONIZACAO_CONVERSOES_DIAS_RETROATIVOS", 3))

# ===============================================================
# RELATÓRIO MERCADO LIVRE
# ===============================================================
COLUNAS_RELATORIO_ML = {
    "identificador_produto": "Anúncio",
    "cliques": "Cliques",
    "pedidos": "Vendas",
    "comissao": "Comissão",
}

# ===============================================================
# AGENDAMENTO
# ===============================================================
HORARIOS_PUBLICACAO = [
    "09:00",
    "12:30",
    "16:00",
    "19:30",
    "21:30",
]
INTERVALO_BUSCA_MINUTOS = int(os.getenv("INTERVALO_BUSCA_MINUTOS", 60))

# ===============================================================
# MODERAÇÃO
# ===============================================================
REQUER_APROVACAO_MANUAL = os.getenv("REQUER_APROVACAO_MANUAL", "false").lower() == "true"

# ===============================================================
# LOGS
# ===============================================================
LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
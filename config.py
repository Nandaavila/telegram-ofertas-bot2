"""
config.py
=========
Este arquivo centraliza TODAS as configurações do sistema.

Por que centralizar assim?
- Evita "números mágicos" e senhas espalhados pelo código.
- Facilita trocar comportamento sem precisar mexer na lógica.
- Lê tudo de variáveis de ambiente (.env), o que é uma boa prática de
  segurança: nunca deixamos tokens/senhas escritos direto no código-fonte.
"""

import os
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env para o ambiente do processo Python.
# Assim, os.getenv("TELEGRAM_BOT_TOKEN") consegue "enxergar" o valor.
load_dotenv()

# ---------------------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")  # ex: "@meucanaldeofertas" ou -1001234567890

# ---------------------------------------------------------------------
# IA (Anthropic Claude) - usada para gerar os textos das ofertas
# ---------------------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
AI_MODEL = "claude-sonnet-4-6"  # modelo usado para gerar os textos

# ---------------------------------------------------------------------
# BANCO DE DADOS
# ---------------------------------------------------------------------
# Para começar usamos SQLite (um único arquivo, zero configuração).
# Quando o volume de produtos/postagens crescer muito, trocamos a URL
# abaixo para PostgreSQL sem precisar reescrever o código de acesso,
# pois usamos SQLAlchemy (camada de abstração de banco de dados).
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///ofertas.db")
# Exemplo para Postgres:
# DATABASE_URL=postgresql://usuario:senha@localhost:5432/ofertas

# ---------------------------------------------------------------------
# REGRAS DE NEGÓCIO DAS OFERTAS
# ---------------------------------------------------------------------
DESCONTO_MINIMO_PERCENTUAL = float(os.getenv("DESCONTO_MINIMO_PERCENTUAL", 30))

# Categorias que o sistema deve buscar. Você pode ligar/desligar cada uma.
CATEGORIAS_ATIVAS = {
    "casa": True,
    "eletronicos": True,
    "moda_feminina": True,
    "moda_masculina": True,
    "beleza": True,
    "informatica": True,
}

# Seus links de afiliado por marketplace (o "tag"/"id" que você recebe
# ao se cadastrar em cada programa de afiliados).
AFFILIATE_TAGS = {
    "mercadolivre": os.getenv("ML_AFFILIATE_TAG", ""),
    "amazon": os.getenv("AMAZON_AFFILIATE_TAG", ""),
    "shopee": os.getenv("SHOPEE_AFFILIATE_TAG", ""),
    "magalu": os.getenv("MAGALU_AFFILIATE_TAG", ""),
}

# Credenciais da Shopee Affiliate Open API (App ID + Secret, obtidos no
# painel de afiliado após aprovação). Usados para assinar as requisições
# GraphQL com HMAC-SHA256 — veja collectors/shopee.py para detalhes.
SHOPEE_APP_ID = os.getenv("SHOPEE_APP_ID", "")
SHOPEE_APP_SECRET = os.getenv("SHOPEE_APP_SECRET", "")

# ---------------------------------------------------------------------
# IDENTIDADE VISUAL DAS IMAGENS PROMOCIONAIS GERADAS
# ---------------------------------------------------------------------
# Cores em RGB (não hexadecimal), pois é o formato que o Pillow espera
# diretamente sem conversão extra.
CORES_MARCA = {
    "primaria": (255, 87, 34),     # laranja - cor de destaque/preço
    "secundaria": (33, 33, 33),    # quase preto - fundo
}

# Texto que aparece no rodapé de toda imagem gerada (marca d'água do canal)
MARCA_DAGUA_RODAPE = os.getenv("MARCA_DAGUA_RODAPE", "@seucanaldeofertas")

# Pasta onde as imagens promocionais geradas são salvas antes de publicar
PASTA_IMAGENS_GERADAS = os.getenv("PASTA_IMAGENS_GERADAS", "generated_images")

# ---------------------------------------------------------------------
# DETECÇÃO DE OFERTAS EXPIRADAS
# ---------------------------------------------------------------------
# A cada quantos minutos o job de verificação roda
VERIFICACAO_EXPIRACAO_INTERVALO_MINUTOS = int(os.getenv("VERIFICACAO_EXPIRACAO_INTERVALO_MINUTOS", 120))

# Só verificamos ofertas publicadas há pelo menos X horas (não faz sentido
# checar uma oferta publicada há 5 minutos)
VERIFICACAO_EXPIRACAO_IDADE_MINIMA_HORAS = int(os.getenv("VERIFICACAO_EXPIRACAO_IDADE_MINIMA_HORAS", 2))

# O que fazer com o post no Telegram quando a oferta expira:
# "editar" -> mantém o post, mas troca a legenda por um aviso de expirado
# "apagar" -> remove a mensagem do canal
ACAO_AO_EXPIRAR = os.getenv("ACAO_AO_EXPIRAR", "editar")

# ---------------------------------------------------------------------
# REPOSTAGEM AUTOMÁTICA DAS MELHORES OFERTAS
# ---------------------------------------------------------------------
REPOSTAGEM_AUTOMATICA_ATIVA = os.getenv("REPOSTAGEM_AUTOMATICA_ATIVA", "true").lower() == "true"

# Só reposta ofertas com desconto igual ou acima deste valor (mais alto
# que o mínimo normal, pois repostagem deve ser reservada às MELHORES)
REPOSTAGEM_DESCONTO_MINIMO = float(os.getenv("REPOSTAGEM_DESCONTO_MINIMO", 50))

# Intervalo mínimo (em horas) entre uma publicação e sua repostagem
REPOSTAGEM_INTERVALO_HORAS = int(os.getenv("REPOSTAGEM_INTERVALO_HORAS", 72))

# Quantas vezes, no máximo, uma mesma oferta pode ser repostada
REPOSTAGEM_MAX_VEZES = int(os.getenv("REPOSTAGEM_MAX_VEZES", 3))

# ---------------------------------------------------------------------
# SINCRONIZAÇÃO DE CLIQUES/CONVERSÕES (Shopee)
# ---------------------------------------------------------------------
# A cada quantas horas o job de sincronização roda
SINCRONIZACAO_CONVERSOES_INTERVALO_HORAS = int(os.getenv("SINCRONIZACAO_CONVERSOES_INTERVALO_HORAS", 6))

# Quantos dias para trás consultar a cada execução (a Shopee recomenda
# não ultrapassar ~90 dias por consulta; um valor pequeno também reduz
# o tempo de resposta da API)
SINCRONIZACAO_CONVERSOES_DIAS_RETROATIVOS = int(os.getenv("SINCRONIZACAO_CONVERSOES_DIAS_RETROATIVOS", 3))

# ---------------------------------------------------------------------
# IMPORTAÇÃO DO RELATÓRIO DE AFILIADOS DO MERCADO LIVRE (CSV MANUAL)
# ---------------------------------------------------------------------
# O Mercado Livre NÃO tem API pública de relatórios de afiliados (só a
# Shopee tem, entre as redes usadas aqui). A alternativa é exportar o
# CSV manualmente pelo painel (mercadolivre.com.br/afiliados > Relatórios)
# e importar com processing/importar_relatorio_ml.py.
#
# Os nomes de coluna abaixo são um PONTO DE PARTIDA — abra o CSV
# exportado de verdade UMA VEZ e ajuste estes valores para bater
# exatamente com os cabeçalhos reais do seu arquivo.
COLUNAS_RELATORIO_ML = {
    "identificador_produto": "Anúncio",  # coluna com o link ou código MLB do produto
    "cliques": "Cliques",
    "pedidos": "Vendas",
    "comissao": "Comissão",
}

# ---------------------------------------------------------------------
# AGENDAMENTO
# ---------------------------------------------------------------------
# Horários em que o robô vai buscar e publicar ofertas (formato 24h).
HORARIOS_PUBLICACAO = ["09:00", "12:30", "16:00", "19:30", "21:30"]

# Intervalo (em minutos) entre a busca de novas ofertas nos marketplaces
INTERVALO_BUSCA_MINUTOS = 60

# ---------------------------------------------------------------------
# MODERAÇÃO
# ---------------------------------------------------------------------
# Se True, cada oferta gerada fica pendente no painel admin até você
# aprovar manualmente. Se False, publica automaticamente.
REQUER_APROVACAO_MANUAL = os.getenv("REQUER_APROVACAO_MANUAL", "false").lower() == "true"

# ---------------------------------------------------------------------
# LOGS
# ---------------------------------------------------------------------
LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

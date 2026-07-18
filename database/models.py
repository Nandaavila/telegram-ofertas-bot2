"""
database/models.py
===================
Aqui definimos o "formato" das tabelas do banco de dados usando SQLAlchemy
(uma biblioteca ORM - Object Relational Mapper).

O que é um ORM, em termos simples?
Em vez de escrever SQL puro ("INSERT INTO produtos ..."), nós descrevemos
uma classe Python (ex: classe Produto) e o SQLAlchemy converte isso em
tabelas e comandos SQL automaticamente. Isso deixa o código mais legível
e portátil entre SQLite e PostgreSQL (só trocamos a URL de conexão).
"""

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

# Base é a "classe mãe" da qual todas as tabelas (models) herdam.
Base = declarative_base()


class Produto(Base):
    """
    Representa um produto/oferta capturado de um marketplace.

    Cada atributo de classe (Column) vira uma coluna na tabela 'produtos'.
    """
    __tablename__ = "produtos"

    # Chave primária: identificador único, gerado automaticamente pelo banco.
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identificador do produto NO MARKETPLACE de origem (ex: MLB123456).
    # Usamos isso, combinado com 'marketplace', para detectar duplicados.
    id_externo = Column(String, nullable=False, index=True)

    marketplace = Column(String, nullable=False)   # "mercadolivre", "amazon", etc.
    categoria = Column(String, nullable=False, index=True)

    titulo = Column(String, nullable=False)
    url_produto = Column(String, nullable=False)      # link original do produto
    url_afiliado = Column(String, nullable=False)      # link já com seu id de afiliado
    url_imagem = Column(String, nullable=True)

    preco_atual = Column(Float, nullable=False)
    preco_anterior = Column(Float, nullable=True)
    percentual_desconto = Column(Float, nullable=False)
    valor_economizado = Column(Float, nullable=False)

    frete_gratis = Column(Boolean, default=False)
    parcelamento = Column(String, nullable=True)   # ex: "10x de R$ 29,90 sem juros"
    avaliacao = Column(Float, nullable=True)        # ex: 4.7 estrelas

    # Controle de fluxo da automação
    texto_gerado = Column(Text, nullable=True)      # texto pronto gerado pela IA
    status = Column(String, default="novo")
    # status possíveis: novo -> pendente_aprovacao -> aprovado -> publicado -> expirado

    # Controle de expiração e repostagem
    vezes_publicado = Column(Integer, default=0)
    expirado_em = Column(DateTime, nullable=True)

    coletado_em = Column(DateTime, default=datetime.utcnow)
    publicado_em = Column(DateTime, nullable=True)


class Publicacao(Base):
    """
    Guarda o histórico de cada postagem feita no Telegram (e em outras redes,
    futuramente). Serve para estatísticas e para evitar reposts indevidos.
    """
    __tablename__ = "publicacoes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    produto_id = Column(Integer, nullable=False, index=True)

    canal = Column(String, default="telegram")  # telegram, whatsapp, instagram...
    mensagem_id_telegram = Column(String, nullable=True)  # id da mensagem enviada

    # Campos de rastreamento via short link (quando o marketplace suporta,
    # ex: Shopee generateShortLink com sub-ID). Guardamos os dois para
    # conseguir, no futuro, ler o relatório de conversões da API e casar
    # pelo sub_id exatamente com esta linha de publicação.
    sub_id = Column(String, nullable=True, index=True)
    link_rastreado = Column(String, nullable=True)

    # Preenchidos pelo job de sincronização de conversões (ver
    # processing/sincronizar_conversoes.py). IMPORTANTE: 'cliques' aqui
    # representa "cliques que resultaram em conversão" — a Shopee não
    # expõe cliques que NÃO viraram venda. Ver o aviso detalhado no
    # próprio módulo de sincronização.
    cliques = Column(Integer, default=0)
    pedidos = Column(Integer, default=0)
    comissao_estimada = Column(Float, default=0.0)

    publicado_em = Column(DateTime, default=datetime.utcnow)


class LogEvento(Base):
    """
    Log estruturado de eventos importantes do sistema (erros, buscas,
    publicações), guardado também no banco além do arquivo de log em disco.
    Facilita mostrar um "feed de atividades" no painel administrativo.
    """
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nivel = Column(String, default="INFO")   # INFO, WARNING, ERROR
    origem = Column(String, nullable=False)  # ex: "collector.mercadolivre"
    mensagem = Column(Text, nullable=False)
    criado_em = Column(DateTime, default=datetime.utcnow)


class ConversaoProcessada(Base):
    """
    Registra o ID de cada conversão da Shopee já contabilizada, para que
    o job de sincronização (processing/sincronizar_conversoes.py) nunca
    some a mesma venda duas vezes — algo que aconteceria facilmente, já
    que o job consulta uma janela retroativa de vários dias a cada
    execução (a mesma conversão aparece em várias execuções seguidas).
    """
    __tablename__ = "conversoes_processadas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversion_id = Column(String, unique=True, nullable=False, index=True)
    processado_em = Column(DateTime, default=datetime.utcnow)


def criar_engine_e_sessao(database_url: str):
    """
    Cria a "engine" (conexão configurada com o banco) e a fábrica de sessões.

    Uma Session é como uma "conversa" com o banco: você abre, faz operações
    (adicionar, consultar, atualizar) e depois fecha/commita.
    """
    engine = create_engine(database_url, echo=False, future=True)
    Base.metadata.create_all(engine)  # cria as tabelas se ainda não existirem
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine, SessionLocal

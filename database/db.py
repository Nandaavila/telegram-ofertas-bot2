"""
database/db.py
===============
Funções utilitárias de acesso ao banco: verificar duplicados, salvar
produto, atualizar status, registrar logs. Toda a lógica de "como
conversar com o banco" fica isolada aqui — o resto do sistema não
precisa saber SQL nem detalhes do SQLAlchemy.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import contextmanager
from database.models import criar_engine_e_sessao, Produto, Publicacao, LogEvento
import config

engine, SessionLocal = criar_engine_e_sessao(config.DATABASE_URL)


@contextmanager
def get_session():
    """
    Context manager para abrir e fechar sessões do banco de forma segura.

    Uso:
        with get_session() as session:
            session.add(objeto)

    O 'yield' entrega a sessão para quem chamou; depois que o bloco 'with'
    termina, garantimos commit (se deu tudo certo) ou rollback (se deu erro),
    e por fim fechamos a conexão — evitando vazamento de recursos.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def produto_ja_existe(session, id_externo: str, marketplace: str) -> bool:
    """
    Verifica se já publicamos/coletamos esse produto antes.
    Isso é o que evita postar o MESMO produto duas vezes.
    """
    existente = (
        session.query(Produto)
        .filter(Produto.id_externo == id_externo, Produto.marketplace == marketplace)
        .first()
    )
    return existente is not None


def salvar_produto(session, dados: dict) -> Produto:
    """Cria um novo registro de Produto a partir de um dicionário de dados."""
    produto = Produto(**dados)
    session.add(produto)
    session.flush()  # garante que o produto.id já fica disponível
    return produto


def registrar_log(nivel: str, origem: str, mensagem: str):
    """Grava um evento de log tanto no banco quanto no logger padrão do Python."""
    import logging
    logger = logging.getLogger(origem)
    getattr(logger, nivel.lower(), logger.info)(mensagem)

    with get_session() as session:
        session.add(LogEvento(nivel=nivel, origem=origem, mensagem=mensagem))

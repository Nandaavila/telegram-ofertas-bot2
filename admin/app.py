"""
admin/app.py
=============
Painel administrativo simples em Flask. Permite:
- Ver ofertas pendentes de aprovação e aprovar/rejeitar.
- Ver histórico de publicações e cliques.
- Ver logs recentes do sistema.

Rodamos isso como um processo SEPARADO do agendador (main.py), conectado
ao mesmo banco de dados. Isso é uma boa prática de escalabilidade: cada
processo tem uma responsabilidade e pode ser reiniciado/escalado
independentemente.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, redirect, url_for, request, flash
from database.db import get_session
from database.models import Produto, Publicacao, LogEvento
from processing.importar_relatorio_ml import importar_relatorio_csv_mercadolivre

app = Flask(__name__)
# Necessário para usar flash() (mensagens de feedback entre requisições).
# Em produção, defina isso via variável de ambiente em vez de gerar
# aleatoriamente a cada reinício (senão as sessões/flashes se perdem
# quando o processo reinicia).
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))

PASTA_UPLOADS_RELATORIOS = "uploads_relatorios"


@app.route("/")
def dashboard():
    with get_session() as session:
        pendentes = session.query(Produto).filter(Produto.status == "pendente_aprovacao").all()
        publicados_recentes = (
            session.query(Produto)
            .filter(Produto.status == "publicado")
            .order_by(Produto.publicado_em.desc())
            .limit(20)
            .all()
        )
        total_publicados = session.query(Produto).filter(Produto.status == "publicado").count()
        total_expirados = session.query(Produto).filter(Produto.status == "expirado").count()
        todas_publicacoes = session.query(Publicacao).all()
        total_cliques = sum(p.cliques for p in todas_publicacoes)
        total_pedidos = sum(p.pedidos for p in todas_publicacoes)
        total_comissao = sum(p.comissao_estimada for p in todas_publicacoes)
        logs_recentes = session.query(LogEvento).order_by(LogEvento.criado_em.desc()).limit(30).all()

        # Não modelamos um relacionamento ORM entre Produto e Publicacao
        # (mantivemos as tabelas propositalmente desacopladas), então
        # buscamos os sub_ids manualmente e montamos um dicionário
        # {produto_id: sub_id} para consulta rápida no template.
        publicacoes_dos_recentes = (
            session.query(Publicacao)
            .filter(Publicacao.produto_id.in_([p.id for p in publicados_recentes]))
            .all()
        )
        sub_id_por_produto = {pub.produto_id: pub.sub_id for pub in publicacoes_dos_recentes}

        return render_template(
            "dashboard.html",
            pendentes=pendentes,
            publicados=publicados_recentes,
            sub_id_por_produto=sub_id_por_produto,
            total_publicados=total_publicados,
            total_expirados=total_expirados,
            total_cliques=total_cliques,
            total_pedidos=total_pedidos,
            total_comissao=total_comissao,
            logs=logs_recentes,
        )


@app.route("/aprovar/<int:produto_id>", methods=["POST"])
def aprovar(produto_id):
    with get_session() as session:
        produto = session.query(Produto).get(produto_id)
        if produto:
            produto.status = "aprovado"
    return redirect(url_for("dashboard"))


@app.route("/rejeitar/<int:produto_id>", methods=["POST"])
def rejeitar(produto_id):
    with get_session() as session:
        produto = session.query(Produto).get(produto_id)
        if produto:
            produto.status = "rejeitado"
    return redirect(url_for("dashboard"))


@app.route("/importar-relatorio-ml", methods=["POST"])
def importar_relatorio_ml():
    """
    Recebe o CSV exportado manualmente do painel de afiliados do
    Mercado Livre e roda o importador (ver processing/importar_relatorio_ml.py).

    Lembrete importante exibido também na interface: diferente da
    Shopee, o Mercado Livre não tem API pública de relatórios — este
    upload manual é o caminho oficial disponível hoje.
    """
    arquivo = request.files.get("arquivo_csv")

    if not arquivo or not arquivo.filename.lower().endswith(".csv"):
        flash("Selecione um arquivo .csv válido exportado do painel de afiliados do Mercado Livre.", "erro")
        return redirect(url_for("dashboard"))

    os.makedirs(PASTA_UPLOADS_RELATORIOS, exist_ok=True)
    caminho = os.path.join(PASTA_UPLOADS_RELATORIOS, arquivo.filename)
    arquivo.save(caminho)

    resumo = importar_relatorio_csv_mercadolivre(caminho)

    if resumo.get("erro") == "colunas_incompativeis":
        flash(
            "As colunas do CSV não bateram com o mapeamento configurado. "
            "Confira o log e ajuste config.COLUNAS_RELATORIO_ML.", "erro",
        )
    else:
        flash(
            f"Importação concluída: {resumo['casadas']} de {resumo['processadas']} linhas "
            f"casadas com publicações ({resumo['sem_match']} sem correspondência).", "sucesso",
        )

    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    # debug=False em produção! debug=True expõe informações sensíveis.
    app.run(host="0.0.0.0", port=5000, debug=False)

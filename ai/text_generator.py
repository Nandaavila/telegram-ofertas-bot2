"""
ai/text_generator.py
======================
Usa a API da Anthropic (Claude) para transformar os dados brutos do
produto em um texto de venda persuasivo, seguindo o formato padrão do
seu canal.

Por que usar IA aqui em vez de um template fixo?
- Templates fixos ficam repetitivos e cansam a audiência.
- A IA consegue variar o "gancho" inicial (a frase de impacto) e a
  linguagem, mantendo a estrutura, o que aumenta o engajamento.

Importante: damos à IA um "molde" claro (o formato da postagem) para que
ela NUNCA invente dados de preço/desconto — só os elementos persuasivos
(título chamativo, gancho, emojis, hashtags) são criativos.
"""

import anthropic
import config

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

PROMPT_SISTEMA = """Você é um copywriter especialista em marketing de afiliados
para um canal de ofertas no Telegram em português do Brasil.

Sua tarefa é escrever o texto de divulgação de UM produto, seguindo
EXATAMENTE esta estrutura (não pule nenhuma linha, não invente dados
que não foram fornecidos):

🔥 OFERTA IMPERDÍVEL

🛒 Produto: {titulo_reescrito}

💰 De: R$ {preco_anterior}
🔥 Por: R$ {preco_atual}
💸 Economia: R$ {valor_economizado}
📉 Desconto: {percentual_desconto}%
[🚚 Frete: Grátis  -- inclua esta linha SOMENTE se frete_gratis for verdadeiro]
[⭐ Avaliação: {avaliacao} estrelas -- inclua SOMENTE se avaliacao for fornecida]
[💳 {parcelamento} -- inclua SOMENTE se fornecido]

🛍️ Comprar agora:
{link}

#Promoção #Oferta #Desconto #Telegram [+ 2 a 3 hashtags específicas da categoria]

Regras:
- Pode reescrever o TÍTULO do produto para ficar mais chamativo e claro,
  mas sem inventar características que não existem.
- Use emojis com moderação e propósito (não exagere).
- O tom deve ser animado, urgente, mas sem soar como spam ou clickbait vazio.
- NUNCA altere os valores numéricos de preço/desconto fornecidos.
- Responda APENAS com o texto final da postagem, nada mais.
"""


def gerar_texto_oferta(produto: dict) -> str:
    """
    Recebe um dicionário com os dados do produto (já processados e com
    desconto calculado) e retorna o texto pronto para publicação.
    """
    dados_formatados = f"""
Dados do produto:
- Título original: {produto['titulo']}
- Categoria: {produto['categoria']}
- Preço anterior: R$ {produto['preco_anterior']:.2f}
- Preço atual: R$ {produto['preco_atual']:.2f}
- Valor economizado: R$ {produto['valor_economizado']:.2f}
- Percentual de desconto: {produto['percentual_desconto']}%
- Frete grátis: {"sim" if produto.get('frete_gratis') else "não"}
- Avaliação: {produto.get('avaliacao') or "não informada"}
- Parcelamento: {produto.get('parcelamento') or "não informado"}
- Link de afiliado: {produto['url_afiliado']}
"""

    resposta = client.messages.create(
        model=config.AI_MODEL,
        max_tokens=500,
        system=PROMPT_SISTEMA,
        messages=[{"role": "user", "content": dados_formatados}],
    )

    # A resposta da API vem em blocos; concatenamos os blocos de texto.
    texto_final = "".join(bloco.text for bloco in resposta.content if bloco.type == "text")
    return texto_final.strip()

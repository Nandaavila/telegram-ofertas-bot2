"""
creative/image_generator.py
=============================
Gera automaticamente um "card" de imagem promocional para cada oferta,
combinando: foto do produto + faixa de oferta + preços + selo de desconto
+ frete grátis (quando houver) + marca d'água do canal.

Por que gerar essa imagem em vez de só reenviar a foto original do
marketplace?
- A foto crua do marketplace não tem preço, desconto nem sua marca.
- Um card com preço "De/Por" visível chama muito mais atenção no feed
  do Telegram do que uma foto de produto pelada.
- Fica com a "cara" do seu canal (cores e identidade consistentes),
  o que ajuda a fidelizar quem segue o canal.

Este módulo usa SOMENTE Pillow (nenhuma IA de imagem envolvida) — é
composição gráfica determinística, rápida e sem custo de API.
"""

import io
import os
import textwrap
import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter

import config

# Pasta onde os fonts ficam DENTRO do projeto (não dependemos de fontes
# instaladas no sistema operacional — isso evita que a imagem quebre
# quando rodar dentro de um container Docker "slim" sem fontes).
PASTA_FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
FONTE_BOLD = os.path.join(PASTA_FONTS, "DejaVuSans-Bold.ttf")
FONTE_REGULAR = os.path.join(PASTA_FONTS, "DejaVuSans.ttf")

# Tamanho do card final. 1080x1080 é quadrado, funciona bem tanto no
# Telegram quanto se você quiser reaproveitar no Instagram/Facebook.
LARGURA, ALTURA = 1080, 1080


def _carregar_fonte(caminho: str, tamanho: int) -> ImageFont.FreeTypeFont:
    """Carrega uma fonte TrueType num tamanho específico (Pillow exige isso)."""
    return ImageFont.truetype(caminho, tamanho)


def _baixar_imagem_produto(url_imagem: str | None) -> Image.Image | None:
    """
    Faz o download da foto do produto a partir da URL fornecida pelo
    marketplace e converte para um objeto de Imagem do Pillow.

    Retorna None se: não houver URL, o download falhar, ou o arquivo
    não for uma imagem válida — nesses casos, o card é gerado sem foto
    de produto (usando apenas um fundo estilizado), em vez de quebrar
    a geração inteira.
    """
    if not url_imagem:
        return None
    try:
        resposta = requests.get(url_imagem, timeout=15)
        resposta.raise_for_status()
        imagem = Image.open(io.BytesIO(resposta.content))
        return imagem.convert("RGBA")
    except Exception:
        return None


def _criar_fundo_gradiente(cor_topo: tuple, cor_base: tuple) -> Image.Image:
    """
    Cria um fundo com gradiente vertical entre duas cores (RGB).

    Como funciona: percorremos cada linha horizontal (de y=0 até y=ALTURA)
    e calculamos, por interpolação linear, uma cor intermediária entre
    cor_topo e cor_base proporcional à posição y. Desenhar linha por linha
    é uma técnica simples e eficiente para criar gradientes com Pillow,
    que não tem uma função pronta de "gradient fill".
    """
    fundo = Image.new("RGB", (LARGURA, ALTURA), cor_topo)
    desenho = ImageDraw.Draw(fundo)

    for y in range(ALTURA):
        proporcao = y / ALTURA
        r = int(cor_topo[0] + (cor_base[0] - cor_topo[0]) * proporcao)
        g = int(cor_topo[1] + (cor_base[1] - cor_topo[1]) * proporcao)
        b = int(cor_topo[2] + (cor_base[2] - cor_topo[2]) * proporcao)
        desenho.line([(0, y), (LARGURA, y)], fill=(r, g, b))

    return fundo


def _aplicar_mascara_arredondada(imagem: Image.Image, raio: int) -> Image.Image:
    """
    Aplica cantos arredondados em uma imagem (usada para deixar a foto
    do produto com visual de "card" moderno, em vez de um retângulo seco).

    Técnica: criamos uma máscara preta-e-branca do mesmo tamanho, com um
    retângulo arredondado branco desenhado nela. Ao aplicar essa máscara
    como canal alfa da imagem original, tudo que está fora do retângulo
    arredondado vira transparente.
    """
    mascara = Image.new("L", imagem.size, 0)
    desenho_mascara = ImageDraw.Draw(mascara)
    desenho_mascara.rounded_rectangle([(0, 0), imagem.size], radius=raio, fill=255)

    resultado = imagem.copy()
    resultado.putalpha(mascara)
    return resultado


def _desenhar_texto_com_quebra(desenho: ImageDraw.ImageDraw, texto: str, fonte: ImageFont.FreeTypeFont,
                                 largura_max_caracteres: int, posicao: tuple, cor: tuple,
                                 espacamento_linha: int = 10, alinhamento: str = "left") -> int:
    """
    Desenha um texto longo quebrando em várias linhas, já que Pillow não
    faz quebra automática de texto sozinho.

    'textwrap.wrap' quebra o texto em uma lista de linhas respeitando um
    número máximo de caracteres por linha. Depois desenhamos linha por
    linha, uma abaixo da outra.

    Retorna a altura total ocupada pelo texto (útil para posicionar o
    próximo elemento abaixo dele sem sobrepor).
    """
    linhas = textwrap.wrap(texto, width=largura_max_caracteres)
    x, y = posicao
    y_inicial = y

    for linha in linhas:
        desenho.text((x, y), linha, font=fonte, fill=cor, anchor=None if alinhamento == "left" else "ma")
        bbox = desenho.textbbox((x, y), linha, font=fonte)
        altura_linha = bbox[3] - bbox[1]
        y += altura_linha + espacamento_linha

    return y - y_inicial


def _desenhar_preco_riscado(desenho: ImageDraw.ImageDraw, texto: str, fonte: ImageFont.FreeTypeFont,
                              posicao: tuple, cor: tuple):
    """
    Desenha um texto com uma linha reta por cima, simulando o efeito
    "riscado" (strikethrough) do preço antigo — Pillow não tem essa
    formatação pronta, então desenhamos manualmente uma linha na altura
    vertical central do texto.
    """
    x, y = posicao
    desenho.text((x, y), texto, font=fonte, fill=cor)
    bbox = desenho.textbbox((x, y), texto, font=fonte)
    y_meio = (bbox[1] + bbox[3]) // 2
    desenho.line([(bbox[0], y_meio), (bbox[2], y_meio)], fill=cor, width=4)


def gerar_imagem_promocional(produto: dict, caminho_saida: str) -> str:
    """
    Função principal deste módulo. Recebe os dados já processados de um
    produto (mesmo formato usado pelo gerador de texto) e produz um
    arquivo de imagem PNG pronto para ser enviado ao Telegram.

    Parâmetros:
        produto: dict com titulo, preco_atual, preco_anterior,
                 percentual_desconto, frete_gratis, url_imagem, etc.
        caminho_saida: caminho onde o arquivo .png final será salvo.

    Retorna: o próprio caminho_saida (para facilitar encadeamento).
    """
    cor_primaria = config.CORES_MARCA["primaria"]     # ex: (255, 87, 34) laranja
    cor_secundaria = config.CORES_MARCA["secundaria"]  # ex: (33, 33, 33) quase preto
    cor_texto_claro = (255, 255, 255)
    cor_destaque_preco = cor_primaria

    # 1) FUNDO: gradiente com as cores da sua marca
    card = _criar_fundo_gradiente(cor_secundaria, cor_primaria).convert("RGBA")
    desenho = ImageDraw.Draw(card)

    fonte_faixa = _carregar_fonte(FONTE_BOLD, 42)
    fonte_titulo = _carregar_fonte(FONTE_BOLD, 46)
    fonte_preco_antigo = _carregar_fonte(FONTE_REGULAR, 38)
    fonte_preco_novo = _carregar_fonte(FONTE_BOLD, 74)
    fonte_desconto = _carregar_fonte(FONTE_BOLD, 34)
    fonte_rodape = _carregar_fonte(FONTE_REGULAR, 28)

    # 2) FAIXA SUPERIOR "OFERTA IMPERDÍVEL"
    desenho.rectangle([(0, 0), (LARGURA, 90)], fill=(0, 0, 0, 160))
    desenho.text((40, 20), "🔥 OFERTA IMPERDÍVEL", font=fonte_faixa, fill=cor_texto_claro)

    # 3) SELO DE DESCONTO (círculo no canto superior direito)
    desconto = produto.get("percentual_desconto", 0)
    centro_selo = (LARGURA - 120, 180)
    raio_selo = 90
    desenho.ellipse(
        [(centro_selo[0] - raio_selo, centro_selo[1] - raio_selo),
         (centro_selo[0] + raio_selo, centro_selo[1] + raio_selo)],
        fill=(220, 40, 40, 255),
    )
    texto_desconto = f"-{int(desconto)}%"
    bbox_desconto = desenho.textbbox((0, 0), texto_desconto, font=fonte_desconto)
    largura_texto = bbox_desconto[2] - bbox_desconto[0]
    desenho.text(
        (centro_selo[0] - largura_texto / 2, centro_selo[1] - 20),
        texto_desconto, font=fonte_desconto, fill=cor_texto_claro,
    )

    # 4) FOTO DO PRODUTO (com cantos arredondados, centralizada)
    foto_produto = _baixar_imagem_produto(produto.get("url_imagem"))
    area_foto_tamanho = 560
    posicao_foto_y = 140

    if foto_produto:
        # 'fit' corta e redimensiona a imagem para preencher um quadrado
        # sem distorcer as proporções originais.
        foto_produto = ImageOps.fit(foto_produto, (area_foto_tamanho, area_foto_tamanho))

        # Fundo branco atrás da foto, para produtos com fundo transparente
        # não ficarem "flutuando" sobre o gradiente colorido.
        fundo_branco = Image.new("RGBA", (area_foto_tamanho, area_foto_tamanho), (255, 255, 255, 255))
        fundo_branco.paste(foto_produto, (0, 0), foto_produto)
        foto_produto = _aplicar_mascara_arredondada(fundo_branco, raio=30)

        x_foto = (LARGURA - area_foto_tamanho) // 2
        card.paste(foto_produto, (x_foto, posicao_foto_y), foto_produto)
        y_atual = posicao_foto_y + area_foto_tamanho + 40
    else:
        # Sem foto disponível: seguimos direto para os textos, só com
        # mais espaço em branco no lugar onde a foto entraria.
        y_atual = posicao_foto_y + 60

    # 5) TÍTULO DO PRODUTO (quebrado em até 2-3 linhas)
    titulo_curto = produto["titulo"][:90]  # evita título gigante estourar o card
    altura_titulo = _desenhar_texto_com_quebra(
        desenho, titulo_curto, fonte_titulo,
        largura_max_caracteres=32, posicao=(40, y_atual), cor=cor_texto_claro,
    )
    y_atual += altura_titulo + 20

    # 6) PREÇO ANTIGO (riscado) + PREÇO NOVO (destaque)
    texto_preco_antigo = f"De: R$ {produto['preco_anterior']:.2f}".replace(".", ",")
    _desenhar_preco_riscado(desenho, texto_preco_antigo, fonte_preco_antigo, (40, y_atual), (220, 220, 220))
    y_atual += 55

    texto_preco_novo = f"R$ {produto['preco_atual']:.2f}".replace(".", ",")
    desenho.text((40, y_atual), texto_preco_novo, font=fonte_preco_novo, fill=cor_texto_claro)
    y_atual += 100

    # 7) SELOS ADICIONAIS: frete grátis / avaliação (lado a lado)
    x_selo = 40
    if produto.get("frete_gratis"):
        desenho.rounded_rectangle([(x_selo, y_atual), (x_selo + 220, y_atual + 55)], radius=27, fill=(30, 140, 60))
        desenho.text((x_selo + 20, y_atual + 12), "🚚 Frete Grátis", font=fonte_rodape, fill=cor_texto_claro)
        x_selo += 240

    if produto.get("avaliacao"):
        desenho.rounded_rectangle([(x_selo, y_atual), (x_selo + 180, y_atual + 55)], radius=27, fill=(230, 170, 20))
        desenho.text((x_selo + 20, y_atual + 12), f"⭐ {produto['avaliacao']}", font=fonte_rodape, fill=(40, 40, 40))

    # 8) RODAPÉ / MARCA D'ÁGUA DO CANAL
    desenho.rectangle([(0, ALTURA - 60), (LARGURA, ALTURA)], fill=(0, 0, 0, 180))
    desenho.text(
        (40, ALTURA - 48), config.MARCA_DAGUA_RODAPE,
        font=fonte_rodape, fill=cor_texto_claro,
    )

    # Salva como PNG (mantém qualidade e transparência, se houver)
    card_final = card.convert("RGB")  # remove canal alfa antes de salvar como imagem "chapada"
    os.makedirs(os.path.dirname(caminho_saida), exist_ok=True)
    card_final.save(caminho_saida, "PNG", quality=95)

    return caminho_saida

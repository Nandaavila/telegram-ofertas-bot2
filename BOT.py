"""
⚠️  ARQUIVO LEGADO / NÃO USADO PELA AUTOMAÇÃO ATUAL  ⚠️
==========================================================
Este arquivo é um protótipo anterior do bot (lê produtos de uma planilha
Google Sheets pública em CSV, em vez de Shopee/Mercado Livre via API).
Ele usa nomes de variável de ambiente DIFERENTES do resto do projeto
(TELEGRAM_TOKEN/CHAT_ID/SHEET_CSV_URL, em vez de TELEGRAM_BOT_TOKEN/
TELEGRAM_CHANNEL_ID definidos em config.py) e NÃO é referenciado em
nenhum lugar da automação atual — o Dockerfile roda "python main.py",
não "python BOT.py".

Ele foi mantido no repositório (não removido) para não apagar histórico/
funcionalidade que talvez você ainda use separadamente, mas rodá-lo por
engano no lugar de main.py vai falhar (SystemExit) por falta dessas
variáveis de ambiente específicas, e mesmo se configurado, ele NÃO
publica ofertas da Shopee/Mercado Livre coletadas automaticamente — ele
publica o que estiver na planilha do Google Sheets.

Se você não usa mais esse fluxo baseado em planilha, o mais seguro é
apagar este arquivo do repositório para evitar confusão futura.
"""
import asyncio
import datetime
from io import StringIO
import os
import traceback

import pandas as pd
import requests
from zoneinfo import ZoneInfo
from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler

# -------- CONFIG via environment variables (nunca coloque tokens no código)
# TELEGRAM_TOKEN => token do BotFather
# CHAT_ID => id do seu canal/grupo (ex: -1001234567890)
# SHEET_CSV_URL => link export?format=csv da sua Google Sheets
# TIMEZONE => ex: America/Recife (padrão: America/Recife)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
SHEET_CSV_URL = os.environ.get("SHEET_CSV_URL")
TIMEZONE = os.environ.get("TIMEZONE", "America/Recife")

if not all([TELEGRAM_TOKEN, CHAT_ID, SHEET_CSV_URL]):
    raise SystemExit("Por favor configure as variáveis de ambiente: TELEGRAM_TOKEN, CHAT_ID, SHEET_CSV_URL")

bot = Bot(token=TELEGRAM_TOKEN)

# Guarda histórico rápido de envios para evitar duplicatas no mesmo minuto
_last_sent = set()

async def carregar_produtos():
    """Carrega a planilha CSV pública do Google Sheets e retorna uma lista de dicionários."""
    try:
        resp = requests.get(SHEET_CSV_URL, timeout=15)
        resp.raise_for_status()
        data = StringIO(resp.text)
        df = pd.read_csv(data, dtype=str).fillna("")
        # Normaliza nomes das colunas para facilitar uso: remove espaços extras
        df.columns = [c.strip() for c in df.columns]
        records = df.to_dict("records")
        return records
    except Exception as e:
        print("Erro ao carregar planilha:", e)
        traceback.print_exc()
        return []

def produto_ativo(prod):
    """Verifica se o produto deve ser considerado (Status == Ativo)."""
    status = str(prod.get("Status", "")).strip().lower()
    return status in ("ativo", "sim", "true", "1")

def horario_do_produto(prod):
    """Retorna o horário preferencial do produto no formato 'HH:MM' ou '' se não houver."""
    h = str(prod.get("Horário Preferencial", "") or prod.get("Horario Preferencial", "") or "").strip()
    # aceita tanto '9:00' quanto '09:00' -> formata com zero à esquerda
    if not h:
        return ""
    try:
        t = datetime.datetime.strptime(h, "%H:%M")
        return t.strftime("%H:%M")
    except Exception:
        # tenta reconhecer H ou H:MM sem zero
        try:
            t = datetime.datetime.strptime(h, "%H")
            return t.strftime("%H:00")
        except Exception:
            return ""

def montar_mensagem(prod):
    """Monta a mensagem em Markdown com os campos relevantes."""
    categoria = prod.get("Categoria", "").strip()
    titulo = prod.get("Título", prod.get("Titulo", "")).strip()
    preco = prod.get("Preço", prod.get("Preco", "")).strip()
    loja = prod.get("Loja", "").strip()
    link = prod.get("Link", "").strip()
    horario = prod.get("Horário Preferencial", "").strip()

    lines = []
    if categoria:
        lines.append(f"🏷️ *Categoria:* {categoria}")
    if titulo:
        lines.append(f"🔥 *{titulo}*")
    if preco:
        lines.append(f"💰 {preco}")
    if loja:
        lines.append(f"🏬 Loja: {loja}")
    if horario:
        lines.append(f"🕐 Horário: {horario}")
    if link:
        lines.append(f"🛒 [Compre aqui]({link})")

    return "\n".join(lines)

async def enviar_produto(prod):
    """Envia o produto (foto + legenda) ou só a legenda se não houver imagem."""
    try:
        caption = montar_mensagem(prod)
        imagem = prod.get("Imagem", prod.get("imagem", "")).strip()
        if imagem:
            await bot.send_photo(chat_id=CHAT_ID, photo=imagem, caption=caption, parse_mode="Markdown")
        else:
            await bot.send_message(chat_id=CHAT_ID, text=caption, parse_mode="Markdown")
        print(f"Enviado: {prod.get('Título','(sem titulo)')} — horário preferencial: {prod.get('Horário Preferencial','')}")
    except Exception as e:
        print("Erro ao enviar produto:", e)
        traceback.print_exc()

async def agendador_principal():
    """
    Loop principal: checa a planilha a cada X segundos e envia produtos cujo
    'Horário Preferencial' bate com o horário atual (no timezone configurado).
    """
    tz = ZoneInfo(TIMEZONE)
    check_interval = 20  # segundos
    global _last_sent

    while True:
        try:
            agora = datetime.datetime.now(tz).strftime("%H:%M")
            produtos = await carregar_produtos()
            # Filtra produtos ativos
            ativos = [p for p in produtos if produto_ativo(p)]
            # Produtos que tem horario igual ao agora
            a_enviar = []
            for p in ativos:
                hp = horario_do_produto(p)
                if hp:
                    if hp == agora:
                        a_enviar.append(p)
                else:
                    # se produto não tem horário preferencial, não envia aqui
                    # (caso queira enviar em horários fixos globais, poderíamos adicionar)
                    pass

            # Evita re-envio no mesmo minuto usando um identificador simples (titulo+horario+link)
            for p in a_enviar:
                ident = (p.get("Título","").strip(), p.get("Link","").strip(), agora)
                if ident in _last_sent:
                    continue
                await enviar_produto(p)
                _last_sent.add(ident)

            # Limpa _last_sent para manter apenas últimos 200 envios (evita memória infinita)
            if len(_last_sent) > 200:
                _last_sent = set(list(_last_sent)[-150:])

        except Exception as e:
            print("Erro no agendador:", e)
            traceback.print_exc()

        await asyncio.sleep(check_interval)

# Comando /start útil para testar
async def start(update, context):
    await update.message.reply_text("🤖 Bot conectado: Ofertas Online Diária — Automação ativa!")

async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    # inicia a tarefa de agendamento em background
    asyncio.create_task(agendador_principal())

    print("Bot automatizador rodando (Ofertas Online Diária)...")
    await app.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Encerrando...")

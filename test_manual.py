"""
test_manual.py
================
Modo de teste manual da automação. Permite testar CADA etapa do fluxo
(Shopee -> Mercado Livre -> filtros -> texto -> imagem -> Telegram)
individualmente, sem precisar esperar o cron/scheduler rodar sozinho.

Uso:
    python test_manual.py checagem          # valida .env e mostra o que falta
    python test_manual.py telegram          # testa conexão + permissões do bot
    python test_manual.py mercadolivre      # testa só o coletor do ML
    python test_manual.py shopee            # testa só o coletor da Shopee
    python test_manual.py texto             # testa a geração de texto (Anthropic)
    python test_manual.py buscar            # roda uma rodada real de busca de ofertas
    python test_manual.py publicar          # publica AGORA a melhor oferta aprovada
                                             # (não espera os HORARIOS_PUBLICACAO)
    python test_manual.py tudo              # roda buscar + publicar em sequência

Cada comando imprime logs claros de sucesso/erro — nada fica silencioso.
"""

import argparse
import asyncio
import logging
import os
import sys

import config

os.makedirs(config.LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(config.LOG_DIR, "automacao.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("test_manual")


def checagem():
    """Valida se as variáveis de ambiente essenciais estão presentes."""
    problemas = config.validar_configuracao_essencial()
    if not problemas:
        print("[SUCCESS] Todas as variáveis de ambiente essenciais estão configuradas.")
        return True

    print("[ERROR] Problemas encontrados na configuração (.env):")
    for p in problemas:
        print(f"  - {p}")
    return False


async def testar_telegram():
    """
    Testa, em sequência:
    1) Se o token do bot é válido (getMe).
    2) Se o bot consegue "ver" o canal configurado (getChat).
    3) Se o bot é ADMINISTRADOR do canal (getChatMember) — sem isso, o
       Telegram bloqueia o envio de mensagens para canais.
    4) Envia uma mensagem de teste real para o canal.
    """
    from telegram import Bot
    from telegram.error import TelegramError

    if not config.TELEGRAM_BOT_TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN não configurado no .env.")
        return False
    if not config.TELEGRAM_CHANNEL_ID:
        print("[ERROR] TELEGRAM_CHANNEL_ID não configurado no .env.")
        return False

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

    try:
        me = await bot.get_me()
        print(f"[SUCCESS] Token válido. Bot conectado: @{me.username} (id={me.id})")
    except TelegramError as e:
        print(f"[ERROR] Falha ao validar o token do bot.")
        print(f"[ERROR] Resposta da API: {e}")
        return False

    try:
        chat = await bot.get_chat(config.TELEGRAM_CHANNEL_ID)
        print(f"[SUCCESS] Canal encontrado: {chat.title or chat.id} (tipo={chat.type})")
    except TelegramError as e:
        print(f"[ERROR] Não foi possível acessar TELEGRAM_CHANNEL_ID='{config.TELEGRAM_CHANNEL_ID}'.")
        print(f"[ERROR] Resposta da API: {e}")
        print("[ERROR] Verifique se o ID está correto (deve começar com -100 para canais) "
              "e se o bot foi adicionado ao canal.")
        return False

    try:
        membro = await bot.get_chat_member(config.TELEGRAM_CHANNEL_ID, me.id)
        status = membro.status
        if status in ("administrator", "creator"):
            print(f"[SUCCESS] Bot é administrador do canal (status={status}).")
        else:
            print(f"[ERROR] Bot NÃO é administrador do canal (status atual={status}).")
            print("[ERROR] Vá em Configurações do Canal -> Administradores -> Adicionar Administrador "
                  "e adicione o bot com permissão de 'Postar mensagens'.")
            return False
    except TelegramError as e:
        print(f"[ERROR] Não foi possível verificar as permissões do bot no canal.")
        print(f"[ERROR] Resposta da API: {e}")
        return False

    try:
        msg = await bot.send_message(
            chat_id=config.TELEGRAM_CHANNEL_ID,
            text="✅ Teste de conexão da automação de ofertas — se você está vendo isso, "
                 "o bot está corretamente configurado como administrador do canal.",
        )
        print(f"[SUCCESS] Mensagem de teste publicada no canal (message_id={msg.message_id}).")
    except TelegramError as e:
        print(f"[ERROR] Falha ao publicar no Telegram")
        print(f"[ERROR] Resposta da API: {e}")
        return False

    return True


def testar_mercadolivre():
    from collectors.mercado_livre import MercadoLivreCollector

    collector = MercadoLivreCollector()
    categoria_teste = next(iter(config.CATEGORIAS_ATIVAS))
    print(f"[INFO] Testando coletor do Mercado Livre (categoria='{categoria_teste}')...")
    ofertas = collector.buscar_ofertas(categoria_teste)

    if not ofertas:
        print("[ERROR] 0 ofertas retornadas. Causas prováveis:")
        print("  - MERCADOLIVRE_CLIENT_ID / MERCADOLIVRE_CLIENT_SECRET ausentes ou inválidos no .env")
        print("  - Nenhum item da categoria trouxe um preço original real (sem desconto genuíno)")
        print("  - IP/ambiente bloqueado pela Mercado Livre (comum em provedores de nuvem)")
        return False

    print(f"[SUCCESS] {len(ofertas)} ofertas com desconto real encontradas.")
    exemplo = ofertas[0]
    print(f"  Exemplo: {exemplo['titulo'][:60]}... | De R$ {exemplo['preco_anterior']} por R$ {exemplo['preco_atual']}")
    return True


def testar_shopee():
    from collectors.shopee import ShopeeCollector

    collector = ShopeeCollector()
    if not collector.credenciais_ok():
        print("[ERROR] SHOPEE_APP_ID / SHOPEE_APP_SECRET não configurados no .env.")
        print("[ERROR] Cadastre-se em https://affiliate.shopee.com.br para obter essas credenciais.")
        return False

    categoria_teste = next(iter(config.CATEGORIAS_ATIVAS))
    print(f"[INFO] Testando coletor da Shopee (categoria='{categoria_teste}')...")
    ofertas = collector.buscar_ofertas(categoria_teste)

    if not ofertas:
        print("[ERROR] 0 ofertas retornadas pela Shopee. Verifique os logs acima para detalhes do erro da API.")
        return False

    print(f"[SUCCESS] {len(ofertas)} ofertas com desconto real encontradas.")
    exemplo = ofertas[0]
    print(f"  Exemplo: {exemplo['titulo'][:60]}... | De R$ {exemplo['preco_anterior']} por R$ {exemplo['preco_atual']}")
    return True


def testar_texto():
    from ai.text_generator import gerar_texto_oferta

    if not config.ANTHROPIC_API_KEY:
        print("[ERROR] ANTHROPIC_API_KEY não configurado no .env.")
        return False

    produto_fake = {
        "titulo": "Fone de Ouvido Bluetooth Teste",
        "categoria": "eletronicos",
        "preco_anterior": 199.90,
        "preco_atual": 119.90,
        "valor_economizado": 80.00,
        "percentual_desconto": 40.0,
        "frete_gratis": True,
        "avaliacao": 4.7,
        "parcelamento": "3x de R$ 39,96 sem juros",
        "url_afiliado": "https://exemplo.com/produto-teste",
    }

    try:
        texto = gerar_texto_oferta(produto_fake)
    except Exception as e:
        print(f"[ERROR] Falha ao gerar texto com a Anthropic API.")
        print(f"[ERROR] {type(e).__name__}: {e}")
        return False

    print("[SUCCESS] Texto gerado com sucesso:\n")
    print(texto)
    return True


def rodar_busca():
    from scheduler.pipeline import tarefa_buscar_ofertas

    print("[INFO] Rodando tarefa_buscar_ofertas() manualmente...")
    tarefa_buscar_ofertas()
    print("[INFO] Busca concluída. Veja logs/automacao.log ou o painel admin para o detalhamento.")


async def rodar_publicacao():
    from scheduler.pipeline import tarefa_publicar_oferta

    print("[INFO] Rodando tarefa_publicar_oferta() manualmente (ignora HORARIOS_PUBLICACAO)...")
    await tarefa_publicar_oferta()
    print("[INFO] Tarefa de publicação concluída. Confira o canal do Telegram e os logs.")


def main():
    parser = argparse.ArgumentParser(description="Modo de teste manual da automação de ofertas.")
    parser.add_argument(
        "comando",
        choices=["checagem", "telegram", "mercadolivre", "shopee", "texto", "buscar", "publicar", "tudo"],
    )
    args = parser.parse_args()

    if args.comando == "checagem":
        sys.exit(0 if checagem() else 1)

    elif args.comando == "telegram":
        ok = asyncio.run(testar_telegram())
        sys.exit(0 if ok else 1)

    elif args.comando == "mercadolivre":
        ok = testar_mercadolivre()
        sys.exit(0 if ok else 1)

    elif args.comando == "shopee":
        ok = testar_shopee()
        sys.exit(0 if ok else 1)

    elif args.comando == "texto":
        ok = testar_texto()
        sys.exit(0 if ok else 1)

    elif args.comando == "buscar":
        rodar_busca()

    elif args.comando == "publicar":
        asyncio.run(rodar_publicacao())

    elif args.comando == "tudo":
        rodar_busca()
        asyncio.run(rodar_publicacao())


if __name__ == "__main__":
    main()

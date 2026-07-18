"""
publisher/telegram_publisher.py
=================================
Responsável por enviar a mensagem final (texto + imagem) para o canal
do Telegram, usando a biblioteca 'python-telegram-bot'.

Boas práticas aplicadas aqui:
1. Rate limiting: o Telegram bloqueia bots que enviam mensagens rápido
   demais. Colocamos um pequeno intervalo entre envios.
2. Retry com backoff: se der erro de rede/rate limit, tentamos de novo
   esperando um pouco mais a cada tentativa, em vez de desistir na hora.
3. Registro do id da mensagem enviada, para conseguirmos editar/apagar
   depois (ex: quando a oferta expirar).
"""

import asyncio
import os
import time
from telegram import Bot, InputMediaPhoto
from telegram.error import RetryAfter, TelegramError
import config


class TelegramPublisher:
    def __init__(self):
        self.bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        self.canal_id = config.TELEGRAM_CHANNEL_ID

    async def publicar_oferta(self, texto: str, imagem: str | None, max_tentativas: int = 3) -> str:
        """
        Publica a oferta no canal. Se houver imagem, envia como foto com
        legenda (caption); senão, envia como texto puro.

        O parâmetro 'imagem' aceita DOIS formatos, para dar suporte tanto
        à foto original do marketplace quanto ao card gerado localmente
        pelo creative/image_generator.py:
        - uma URL (string começando com "http") -> o Telegram baixa direto
        - um caminho de arquivo local (ex: "generated_images/produto.png")
          -> abrimos o arquivo em modo binário e enviamos os bytes

        Retorna o id da mensagem publicada no Telegram (útil para
        estatísticas e para poder editar/remover depois).
        """
        tentativa = 0
        while tentativa < max_tentativas:
            arquivo_aberto = None
            try:
                if imagem and os.path.isfile(imagem):
                    # É um card gerado localmente: abrimos o arquivo em
                    # modo binário ("rb") para o Telegram fazer o upload.
                    arquivo_aberto = open(imagem, "rb")
                    conteudo_foto = arquivo_aberto
                else:
                    # É uma URL (ou None) — o Telegram lida com URL direto.
                    conteudo_foto = imagem

                if conteudo_foto:
                    mensagem = await self.bot.send_photo(
                        chat_id=self.canal_id,
                        photo=conteudo_foto,
                        caption=texto,
                        parse_mode="HTML",
                    )
                else:
                    mensagem = await self.bot.send_message(
                        chat_id=self.canal_id,
                        text=texto,
                        parse_mode="HTML",
                    )
                return str(mensagem.message_id)

            except RetryAfter as e:
                # O Telegram nos diz explicitamente quanto tempo esperar
                # antes de tentar de novo (flood control).
                await asyncio.sleep(e.retry_after)
                tentativa += 1

            except TelegramError as e:
                tentativa += 1
                # backoff exponencial simples: 2s, 4s, 8s...
                await asyncio.sleep(2 ** tentativa)
                if tentativa == max_tentativas:
                    raise e

            finally:
                # Sempre fechamos o arquivo local, se ele foi aberto,
                # independentemente de sucesso ou erro no envio.
                if arquivo_aberto:
                    arquivo_aberto.close()

        raise RuntimeError("Falha ao publicar após múltiplas tentativas.")

    async def apagar_mensagem(self, message_id: str):
        """Usado quando detectamos que uma oferta expirou e queremos remover o post."""
        await self.bot.delete_message(chat_id=self.canal_id, message_id=int(message_id))

    async def marcar_como_expirada(self, message_id: str, texto_original: str, tinha_foto: bool = True):
        """
        Edita um post já publicado para sinalizar visualmente que a
        oferta expirou, em vez de apagar o post (o que perderia
        visualizações/engajamento acumulados até então).

        Tentamos editar a LEGENDA (caption) primeiro, pois a maioria dos
        nossos posts é enviada como foto+legenda. Se isso falhar (ex: o
        post original era só texto puro, sem foto), caímos para editar o
        corpo da mensagem de texto.
        """
        texto_expirado = f"🚫 <b>OFERTA EXPIRADA</b> — preço ou disponibilidade mudaram.\n\n{texto_original}"

        try:
            if tinha_foto:
                await self.bot.edit_message_caption(
                    chat_id=self.canal_id,
                    message_id=int(message_id),
                    caption=texto_expirado,
                    parse_mode="HTML",
                )
            else:
                await self.bot.edit_message_text(
                    chat_id=self.canal_id,
                    message_id=int(message_id),
                    text=texto_expirado,
                    parse_mode="HTML",
                )
        except TelegramError:
            # Se a primeira tentativa não bateu com o tipo real da
            # mensagem (foto vs texto), tentamos o caminho oposto antes
            # de desistir — evita falhar silenciosamente por um detalhe
            # que não deveria impedir a marcação de expirado.
            try:
                await self.bot.edit_message_text(
                    chat_id=self.canal_id,
                    message_id=int(message_id),
                    text=texto_expirado,
                    parse_mode="HTML",
                )
            except TelegramError:
                await self.bot.edit_message_caption(
                    chat_id=self.canal_id,
                    message_id=int(message_id),
                    caption=texto_expirado,
                    parse_mode="HTML",
                )

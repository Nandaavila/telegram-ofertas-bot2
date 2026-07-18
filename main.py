"""
main.py
========
Ponto de entrada da automação. Roda o agendador em loop contínuo.

Para rodar o painel administrativo (Flask) junto, use o Docker Compose
(veja docker-compose.yml), que sobe os dois processos separadamente —
isso é mais robusto do que tentar rodar os dois no mesmo processo Python.
"""

import asyncio
import logging
import os
import config
from scheduler.scheduler import iniciar_agendador

# Configura logging para arquivo + console
os.makedirs(config.LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(config.LOG_DIR, "automacao.log")),
        logging.StreamHandler(),
    ],
)


async def main():
    logging.info("Iniciando automação do canal de ofertas...")
    iniciar_agendador()

    # Mantém o processo vivo indefinidamente (o scheduler roda em background)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())

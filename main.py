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

    # Validação de configuração essencial: avisa LOGO DE CARA se faltar
    # alguma variável de ambiente crítica, em vez de deixar o processo
    # rodando por horas sem nunca publicar nada e sem nenhuma pista do
    # motivo (o cenário que motivou esta correção).
    problemas = config.validar_configuracao_essencial()
    if problemas:
        logging.warning("Configuração incompleta detectada no .env:")
        for problema in problemas:
            logging.warning(f"  - {problema}")
        logging.warning(
            "A automação vai continuar rodando, mas etapas relacionadas às variáveis "
            "acima provavelmente vão falhar até que o .env seja corrigido."
        )

    iniciar_agendador()

    # Mantém o processo vivo indefinidamente (o scheduler roda em background)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())

"""
scheduler/scheduler.py
========================
Configura o APScheduler para rodar as tarefas automaticamente, sem
precisar de cron externo ou intervenção manual.

Por que APScheduler e não apenas 'time.sleep()' em loop?
- Permite agendar por horário exato (ex: "09:00", "16:00") e por
  intervalo (ex: "a cada 60 minutos") ao mesmo tempo, de forma robusta.
- Roda em background (BackgroundScheduler) sem travar o resto do app,
  o que é essencial quando também temos o painel Flask rodando junto.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import timezone, timedelta
from apscheduler.triggers.cron import CronTrigger
import config
from scheduler.pipeline import tarefa_buscar_ofertas, tarefa_publicar_oferta
from processing.expiracao import tarefa_verificar_ofertas_expiradas
from processing.sincronizar_conversoes import tarefa_sincronizar_conversoes_shopee


def iniciar_agendador() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler() # Sem passar timezone aqui dentro, ele pega o TZ do sistema sozinho!

    # Tarefa de BUSCA: roda a cada N minutos (configurável em config.py)
    scheduler.add_job(
        tarefa_buscar_ofertas,
        trigger="interval",
        minutes=config.INTERVALO_BUSCA_MINUTOS,
        id="busca_ofertas",
        next_run_time=None,  # deixa o próprio scheduler decidir o primeiro disparo
    )

    # Tarefas de PUBLICAÇÃO: uma por horário configurado em HORARIOS_PUBLICACAO
    for horario in config.HORARIOS_PUBLICACAO:
        hora, minuto = horario.split(":")
        scheduler.add_job(
            tarefa_publicar_oferta,
            trigger=CronTrigger(hour=int(hora), minute=int(minuto)),
            id=f"publicar_{horario}",
        )

    # Tarefa de VERIFICAÇÃO DE EXPIRAÇÃO: roda a cada N minutos, de forma
    # independente do ciclo de busca/publicação (veja processing/expiracao.py)
    scheduler.add_job(
        tarefa_verificar_ofertas_expiradas,
        trigger="interval",
        minutes=config.VERIFICACAO_EXPIRACAO_INTERVALO_MINUTOS,
        id="verificar_expiracao",
    )

    # Tarefa de SINCRONIZAÇÃO DE CONVERSÕES: roda a cada N horas
    # (ver processing/sincronizar_conversoes.py)
    scheduler.add_job(
        tarefa_sincronizar_conversoes_shopee,
        trigger="interval",
        hours=config.SINCRONIZACAO_CONVERSOES_INTERVALO_HORAS,
        id="sincronizar_conversoes",
    )

    scheduler.start()
    return scheduler

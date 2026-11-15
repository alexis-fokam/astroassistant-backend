"""Tâches de maintenance peu fréquentes (APScheduler).

Le pipeline de risque tourne à part toutes les quelques secondes (``app.engine.scheduler``) ;
les tâches d'ici tournent une fois par jour.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.database import SessionLocal
from app.services import audit

log = logging.getLogger("astro.scheduler")

scheduler = AsyncIOScheduler()


async def verify_audit_chain() -> None:
    """Vérification nocturne de l'intégrité de la chaîne d'audit SHA-256 (F14.1)."""
    with SessionLocal() as db:
        valid, entries, broken_at = audit.verify(db)
    if valid:
        log.info("Audit chain valid (%d entries)", entries)
    else:
        log.error("Audit chain broken at entry %s", broken_at)


def init_scheduler() -> None:
    scheduler.add_job(
        verify_audit_chain,
        trigger=CronTrigger(hour=0, minute=0),
        id="verify_audit_chain",
        replace_existing=True,
    )

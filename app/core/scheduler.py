"""Low-frequency housekeeping jobs (APScheduler).

The risk pipeline runs separately every few seconds (``app.engine.scheduler``); the jobs
here run once a day.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.database import SessionLocal
from app.services import audit

log = logging.getLogger("astro.scheduler")

scheduler = AsyncIOScheduler()


async def verify_audit_chain() -> None:
    """Nightly integrity check of the SHA-256 audit chain (spec F14.1)."""
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

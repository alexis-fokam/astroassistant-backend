"""Background loop running the risk pipeline every ``AV_PIPELINE_INTERVAL_SECONDS`` (§8.1)."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.engine.pipeline import PipelineReport, run_once

log = logging.getLogger("astro.engine")


def _run() -> PipelineReport:
    with SessionLocal() as db:
        return run_once(db)


async def broadcast(report: PipelineReport) -> None:
    from app.api.routes.ws import manager

    for member in report.members:
        if member.skipped:
            continue
        await manager.broadcast(
            {
                "type": "score",
                "crew_id": member.code,
                "status": member.status,
                "global_score": member.global_score,
                "domains": member.domains,
                "computed_at": report.computed_at.isoformat(),
            }
        )
    for alert_id in report.new_alert_ids:
        await manager.broadcast({"type": "alert", "alert_id": alert_id})


async def run_forever() -> None:
    interval = get_settings().pipeline_interval_seconds
    while True:
        try:
            report = await asyncio.to_thread(_run)
            await broadcast(report)
        except asyncio.CancelledError:
            raise
        except Exception:  # keep the loop alive; the next tick retries
            log.exception("Risk pipeline failed")
        await asyncio.sleep(interval)

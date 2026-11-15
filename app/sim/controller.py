"""Runs the live simulator in the background (one demo run at a time)."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.sim import live

log = logging.getLogger("astro.sim")


class SimController:
    def __init__(self) -> None:
        self.state = live.SimState()
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def launch(self) -> None:
        """Start the background loop (disabled in tests: they call ``tick`` directly)."""
        if self.running or not get_settings().pipeline_enabled:
            return
        self._task = asyncio.get_event_loop().create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    def reset(self) -> None:
        self.state = live.SimState()

    def _tick(self) -> live.PipelineReport:
        with SessionLocal() as db:
            return live.tick(db, self.state)

    async def _loop(self) -> None:
        from app.engine.scheduler import broadcast

        while True:
            try:
                report = await asyncio.to_thread(self._tick)
                await broadcast(report)
                from app.api.routes.ws import manager

                await manager.broadcast({"type": "sim", **live.snapshot(self.state, True)})
            except asyncio.CancelledError:
                raise
            except Exception:  # keep the demo alive; the next tick retries
                log.exception("Simulator tick failed")
            await asyncio.sleep(live.TICK_SECONDS)


controller = SimController()

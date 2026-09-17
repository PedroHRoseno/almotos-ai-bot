from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings
from app.services.wishlist_job import run_wishlist_poll

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start_wishlist_scheduler(settings: Settings) -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    scheduler = AsyncIOScheduler()

    async def _job() -> None:
        try:
            sent = await run_wishlist_poll(settings)
            logger.info("Job lista de espera: %s avisos enviados", sent)
        except Exception:
            logger.exception("Job lista de espera falhou")

    scheduler.add_job(
        _job,
        "interval",
        minutes=30,
        id="wishlist_poll",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
        misfire_grace_time=120,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler da lista de espera iniciado (a cada 30 min)")
    return scheduler


def stop_wishlist_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None

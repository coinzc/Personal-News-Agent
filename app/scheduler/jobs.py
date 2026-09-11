"""APScheduler integration for the daily digest pipeline."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


async def generate_daily_digest_job(run_digest: Callable[[], Awaitable[Any]]) -> Any:
    try:
        return await run_digest()
    except Exception:
        logger.exception("Scheduled daily digest job failed")
        return None


def build_scheduler(run_digest: Callable[[], Awaitable[Any]], *, timezone: str = "Asia/Singapore") -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(timezone))
    scheduler.add_job(
        generate_daily_digest_job,
        trigger=CronTrigger(hour=9, minute=0, timezone=ZoneInfo(timezone)),
        args=[run_digest],
        id="generate_daily_digest",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    return scheduler


__all__ = ["build_scheduler", "generate_daily_digest_job"]

"""APScheduler integration for the daily digest pipeline."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
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


async def collect_news_job(run_collect: Callable[[], Awaitable[Any]]) -> Any:
    try:
        return await run_collect()
    except Exception:
        logger.exception("Scheduled news collection job failed")
        return None


def build_scheduler(
    run_digest: Callable[[], Awaitable[Any]],
    *,
    run_collect: Callable[[], Awaitable[Any]] | None = None,
    collection_interval_minutes: int = 30,
    timezone: str = "Asia/Shanghai",
) -> AsyncIOScheduler:
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
    if run_collect is not None:
        scheduler.add_job(
            collect_news_job,
            trigger="interval",
            minutes=collection_interval_minutes,
            next_run_time=datetime.now(UTC),
            args=[run_collect],
            id="collect_news",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=1800,
        )
    return scheduler


__all__ = ["build_scheduler", "collect_news_job", "generate_daily_digest_job"]

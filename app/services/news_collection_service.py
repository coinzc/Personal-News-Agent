"""Scheduled RSS collection, ingestion, and event clustering."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.rss import RSSCollector
from app.models.source import NewsSource
from app.models.task import Task
from app.services.news_clustering_service import NewsClusteringService
from app.services.news_ingestion_service import NewsIngestionService

logger = logging.getLogger(__name__)


class NewsCollectionService:
    def __init__(self, session: AsyncSession, *, collector: RSSCollector | None = None) -> None:
        self.session, self.collector = session, collector or RSSCollector()

    async def collect_enabled_sources(self) -> dict[str, Any]:
        task_record = Task(task_type="collect_news", status="running", attempts=1, payload={})
        self.session.add(task_record)
        await self.session.commit()
        try:
            result = await self._collect_enabled_sources()
            saved_task = await self.session.get(Task, task_record.id)
            if saved_task is not None:
                saved_task.status = "completed"
                saved_task.finished_at = datetime.now(UTC)
                saved_task.result = result
                await self.session.commit()
            return result
        except Exception as exc:
            await self.session.rollback()
            saved_task = await self.session.get(Task, task_record.id)
            if saved_task is not None:
                saved_task.status = "failed"
                saved_task.finished_at = datetime.now(UTC)
                saved_task.error_message = str(exc)[:2_000]
                await self.session.commit()
            raise

    async def _collect_enabled_sources(self) -> dict[str, Any]:
        sources = list(
            (
                await self.session.scalars(
                    select(NewsSource)
                    .where(NewsSource.enabled.is_(True), NewsSource.source_type == "rss")
                    .order_by(NewsSource.priority.desc(), NewsSource.created_at.asc())
                )
            ).all()
        )
        results = await self.collector.collect_many(sources)
        inserted = skipped = failed = 0
        for source in sources:
            result = results[str(source.id)]
            if isinstance(result, Exception):
                failed += 1
                logger.warning("RSS source failed source_id=%s url=%s error=%s", source.id, source.url, result)
                continue
            added, ignored = await NewsIngestionService(self.session).ingest(source, result)
            inserted += added
            skipped += ignored
            source.last_collected_at = datetime.now(UTC)
        clustered = await NewsClusteringService(self.session).cluster_pending(commit=False)
        await self.session.commit()
        return {
            "sources": len(sources),
            "failed_sources": failed,
            "inserted": inserted,
            "skipped": skipped,
            "events": len(clustered),
        }


__all__ = ["NewsCollectionService"]

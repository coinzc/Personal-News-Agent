"""Scheduled RSS collection, ingestion, and event clustering."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.rss import RSSCollector
from app.models.event import EventNews
from app.models.news import NewsItem
from app.models.source import NewsSource
from app.models.task import Task
from app.services.news_clustering_service import NewsClusteringService
from app.services.news_ingestion_service import NewsIngestionService

logger = logging.getLogger(__name__)


class NewsCollectionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        collector: RSSCollector | None = None,
        max_concurrency: int = 5,
        clustering_batch_size: int = 500,
    ) -> None:
        if clustering_batch_size <= 0:
            raise ValueError("clustering_batch_size must be greater than zero")
        self.session = session
        self.collector = collector or RSSCollector(max_concurrency=max_concurrency)
        self.clustering_batch_size = clustering_batch_size

    async def collect_enabled_sources(self) -> dict[str, Any]:
        task_record = Task(task_type="collect_news", status="running", attempts=1, payload={})
        self.session.add(task_record)
        await self.session.commit()
        try:
            result = await self._collect_enabled_sources()
            saved_task = await self.session.get(Task, task_record.id)
            if saved_task is not None:
                failed_sources = int(result.get("failed_sources", 0))
                total_sources = int(result.get("sources", 0))
                if failed_sources == 0:
                    saved_task.status = "completed"
                elif failed_sources == total_sources:
                    saved_task.status = "failed"
                else:
                    saved_task.status = "partial_failed"
                saved_task.finished_at = datetime.now(UTC)
                saved_task.result = result
                if failed_sources:
                    saved_task.error_message = self._failure_summary(result)
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
        failures: list[dict[str, str]] = []
        for source in sources:
            result = results[str(source.id)]
            if isinstance(result, Exception):
                failed += 1
                failure = {"source_id": str(source.id), "error_type": type(result).__name__}
                failures.append(failure)
                logger.warning("RSS source failed source_id=%s error_type=%s", source.id, type(result).__name__)
                continue
            added, ignored = await NewsIngestionService(self.session).ingest(source, result)
            inserted += added
            skipped += ignored
            source.last_collected_at = datetime.now(UTC)
        clustered = await NewsClusteringService(self.session).cluster_pending(
            limit=self.clustering_batch_size,
            commit=False,
        )
        pending_items = await self.session.scalar(
            select(func.count())
            .select_from(NewsItem)
            .outerjoin(EventNews, EventNews.news_item_id == NewsItem.id)
            .where(EventNews.news_item_id.is_(None))
        )
        await self.session.commit()
        return {
            "sources": len(sources),
            "failed_sources": failed,
            "successful_sources": len(sources) - failed,
            "failures": failures,
            "inserted": inserted,
            "skipped": skipped,
            "events": len(clustered),
            "pending_items": int(pending_items or 0),
        }

    @staticmethod
    def _failure_summary(result: dict[str, Any]) -> str:
        failures = result.get("failures", [])
        types = sorted({str(row.get("error_type", "UnknownError")) for row in failures if isinstance(row, dict)})
        count = int(result.get("failed_sources", len(failures)))
        return f"{count} RSS source(s) failed: {', '.join(types) or 'UnknownError'}"[:2_000]


__all__ = ["NewsCollectionService"]

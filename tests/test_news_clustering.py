"""Async persistence tests for Phase 4 event clustering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.db.base import Base
from app.models import EventNews, NewsEvent, NewsItem, NewsSource
from app.services.news_clustering_service import NewsClusteringService
from app.services.news_dedup_service import NewsDedupService
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload


def _article(source: NewsSource, title: str, suffix: str, *, minutes: int = 0) -> NewsItem:
    return NewsItem(
        source=source,
        title=title,
        url=f"https://news.example.test/{suffix}",
        category="AI",
        language="en",
        published_at=datetime(2026, 9, 9, 1, 0, tzinfo=UTC) + timedelta(minutes=minutes),
    )


@pytest.mark.asyncio
async def test_clustering_preserves_multiple_items_and_sources_and_is_idempotent(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'clustering.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        source_one = NewsSource(
            id=uuid4(),
            name="Reuters mock",
            url="https://feeds.example.test/reuters.xml",
            source_type="rss",
            category="AI",
        )
        source_two = NewsSource(
            id=uuid4(),
            name="BBC mock",
            url="https://feeds.example.test/bbc.xml",
            source_type="rss",
            category="AI",
        )
        first = _article(source_one, "OpenAI 发布新模型", "openai-cn")
        second = _article(source_two, "OpenAI announces new model", "openai-en", minutes=10)
        unrelated = _article(source_two, "Global markets fall after interest rate decision", "markets")
        session.add_all([source_one, source_two, first, second, unrelated])
        await session.commit()

        service = NewsClusteringService(session, NewsDedupService(similarity_threshold=0.70))
        touched = await service.cluster_items([first, second, unrelated])

        assert len(touched) == 2
        event_count = await session.scalar(select(func.count()).select_from(NewsEvent))
        association_count = await session.scalar(select(func.count()).select_from(EventNews))
        assert event_count == 2
        assert association_count == 3

        grouped = (
            await session.scalars(
                select(NewsEvent).options(selectinload(NewsEvent.news_items)).order_by(NewsEvent.canonical_title)
            )
        ).all()
        openai_event = next(event for event in grouped if len(event.news_items) == 2)
        assert openai_event.canonical_title == first.title
        assert {item.source_id for item in openai_event.news_items} == {source_one.id, source_two.id}

        # Re-running on the same rows must not create another event or a
        # duplicate composite association row.
        await service.cluster_items([first, second, unrelated])
        assert await session.scalar(select(func.count()).select_from(NewsEvent)) == 2
        assert await session.scalar(select(func.count()).select_from(EventNews)) == 3

    await engine.dispose()


@pytest.mark.asyncio
async def test_cluster_pending_only_processes_unlinked_articles(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pending.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        source = NewsSource(
            id=uuid4(),
            name="Mock source",
            url="https://feeds.example.test/source.xml",
            source_type="rss",
            category="AI",
        )
        first = _article(source, "OpenAI announces new model", "one")
        second = _article(source, "OpenAI announces new model follow-up", "two", minutes=1)
        session.add_all([source, first, second])
        await session.commit()

        # Seed one existing event; cluster_pending should only select second.
        existing = NewsEvent(canonical_title=first.title, category="AI")
        existing.event_news.append(EventNews(news_item=first, is_primary=True))
        session.add(existing)
        await session.commit()

        touched = await NewsClusteringService(session, NewsDedupService(similarity_threshold=0.60)).cluster_pending()

        assert len(touched) == 1
        assert await session.scalar(select(func.count()).select_from(EventNews)) == 2

    await engine.dispose()

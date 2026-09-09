"""Persistence tests for collector output."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.collectors.base import CollectedNews
from app.db.base import Base
from app.models import NewsItem, NewsSource
from app.services.news_ingestion_service import NewsIngestionService
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


@pytest.mark.asyncio
async def test_ingestion_skips_duplicate_urls_without_losing_previous_rows(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ingestion.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        source = NewsSource(
            id=uuid4(),
            name="Mock source",
            url="https://feeds.example.test/rss.xml",
            source_type="rss",
            category="technology",
        )
        session.add(source)
        await session.commit()

        items = [
            CollectedNews(title="First", url="https://example.test/1", category="technology"),
            CollectedNews(title="Second", url="https://example.test/2", category="technology"),
            CollectedNews(title="Duplicate", url="https://example.test/1", category="technology"),
        ]
        inserted, skipped = await NewsIngestionService(session).ingest(source, items)

        assert (inserted, skipped) == (2, 1)
        count = await session.scalar(select(func.count()).select_from(NewsItem))
        assert count == 2

    await engine.dispose()

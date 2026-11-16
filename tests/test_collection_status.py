from __future__ import annotations

from uuid import uuid4

import pytest
from app.collectors.base import CollectedNews
from app.db.base import Base
from app.models import NewsSource, Task
from app.services.news_collection_service import NewsCollectionService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


class FakeCollector:
    def __init__(self, results: dict[str, list[CollectedNews] | Exception]) -> None:
        self.results = results

    async def collect_many(self, sources: list[NewsSource]):
        return {str(source.id): self.results[str(source.id)] for source in sources}


async def make_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'collection.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine


async def add_sources(session: AsyncSession, count: int) -> list[NewsSource]:
    sources = [
        NewsSource(
            id=uuid4(),
            name=f"Source {index}",
            url=f"https://example.test/{index}",
            source_type="rss",
            category="AI",
        )
        for index in range(count)
    ]
    session.add_all(sources)
    await session.commit()
    return sources


@pytest.mark.asyncio
async def test_collection_marks_partial_failure_without_exposing_source_url(tmp_path) -> None:
    engine = await make_session(tmp_path)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        sources = await add_sources(session, 2)
        collector = FakeCollector(
            {
                str(sources[0].id): [],
                str(sources[1].id): RuntimeError("HTTP 503 https://private.example/token"),
            }
        )

        result = await NewsCollectionService(session, collector=collector).collect_enabled_sources()
        task = await session.scalar(select(Task).order_by(Task.created_at.desc()))

        assert result["failed_sources"] == 1
        assert task is not None
        assert task.status == "partial_failed"
        assert "private.example" not in (task.error_message or "")
        assert task.result["failures"][0]["error_type"] == "RuntimeError"
    await engine.dispose()


@pytest.mark.asyncio
async def test_collection_marks_failed_when_every_source_fails(tmp_path) -> None:
    engine = await make_session(tmp_path)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        sources = await add_sources(session, 2)
        collector = FakeCollector({str(source.id): ValueError("invalid feed") for source in sources})

        await NewsCollectionService(session, collector=collector).collect_enabled_sources()
        task = await session.scalar(select(Task).order_by(Task.created_at.desc()))

        assert task is not None
        assert task.status == "failed"
        assert task.error_message == "2 RSS source(s) failed: ValueError"
    await engine.dispose()


@pytest.mark.asyncio
async def test_collection_marks_completed_when_sources_succeed(tmp_path) -> None:
    engine = await make_session(tmp_path)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        sources = await add_sources(session, 1)
        collector = FakeCollector({str(sources[0].id): []})

        result = await NewsCollectionService(session, collector=collector).collect_enabled_sources()
        task = await session.scalar(select(Task).order_by(Task.created_at.desc()))

        assert result["successful_sources"] == 1
        assert task is not None
        assert task.status == "completed"
    await engine.dispose()

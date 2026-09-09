"""Database model and Alembic migration tests."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from app.db.base import Base
from app.db.init_db import build_alembic_config
from app.models import EventNews, NewsEvent, NewsItem, NewsSource
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload


def test_all_phase_two_models_are_registered() -> None:
    """Every required domain model contributes a table to shared metadata."""

    assert set(Base.metadata.tables) == {
        "users",
        "news_sources",
        "news_categories",
        "news_items",
        "news_events",
        "event_news",
        "daily_digests",
        "agent_conversations",
        "agent_messages",
        "tasks",
    }

    news_items = Base.metadata.tables["news_items"]
    assert news_items.c.url.unique is True
    assert any(constraint.name == "uq_news_items_url" for constraint in news_items.constraints)
    assert any(foreign_key.target_fullname == "news_sources.id" for foreign_key in news_items.c.source_id.foreign_keys)


def test_alembic_upgrade_and_downgrade_on_sqlite(tmp_path: Path) -> None:
    """The initial revision can be applied and reverted without PostgreSQL."""

    database_path = tmp_path / "migration.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    config = build_alembic_config(database_url)

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        table_names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert {
        "alembic_version",
        "users",
        "news_sources",
        "news_categories",
        "news_items",
        "news_events",
        "event_news",
        "daily_digests",
        "agent_conversations",
        "agent_messages",
        "tasks",
    } <= table_names

    command.downgrade(config, "base")
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        assert inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_news_event_relationship_and_url_uniqueness(tmp_path: Path) -> None:
    """News events link multiple articles while article URLs remain unique."""

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'models.db'}"
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    source_id = uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        source = NewsSource(
            id=source_id,
            name="Example Feed",
            url="https://example.test/rss.xml",
            source_type="rss",
            category="technology",
        )
        item_one = NewsItem(
            source=source,
            title="First report",
            url="https://example.test/articles/1",
            category="technology",
        )
        item_two = NewsItem(
            source=source,
            title="Second report",
            url="https://example.test/articles/2",
            category="technology",
        )
        event = NewsEvent(canonical_title="One event", category="technology")
        event.event_news.extend(
            [EventNews(news_item=item_one, is_primary=True), EventNews(news_item=item_two)]
        )
        session.add(event)
        await session.commit()

        loaded_event = await session.scalar(
            select(NewsEvent).options(selectinload(NewsEvent.news_items)).where(NewsEvent.id == event.id)
        )
        assert loaded_event is not None
        assert {item.url for item in loaded_event.news_items} == {
            "https://example.test/articles/1",
            "https://example.test/articles/2",
        }

        duplicate = NewsItem(
            source_id=source_id,
            title="Duplicate URL",
            url="https://example.test/articles/1",
            category="technology",
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    await engine.dispose()

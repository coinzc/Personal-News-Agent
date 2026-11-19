from uuid import uuid4

import pytest
from app.db.base import Base
from app.db.seed_sources import DEFAULT_RSS_SOURCES, LEGACY_SOURCE_REPLACEMENTS
from app.models.source import NewsSource
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def test_default_catalog_uses_replacement_feeds() -> None:
    names = {row[0] for row in DEFAULT_RSS_SOURCES}
    urls = {row[1] for row in DEFAULT_RSS_SOURCES}

    assert {"CNBC Business", "CNBC Finance", "Al Jazeera World", "Science News"} <= names
    assert all(url.startswith("https://") for url in urls)
    assert all(old_url not in urls for old_url in LEGACY_SOURCE_REPLACEMENTS)


def test_legacy_sources_have_one_to_one_replacements() -> None:
    replacement_urls = {row[1] for row in DEFAULT_RSS_SOURCES}

    assert len(LEGACY_SOURCE_REPLACEMENTS) == 4
    assert set(LEGACY_SOURCE_REPLACEMENTS.values()) <= replacement_urls


@pytest.mark.asyncio
async def test_seed_migrates_legacy_rows_and_is_idempotent(tmp_path, monkeypatch) -> None:
    from app.db import seed_sources as seed_module

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sources.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(seed_module, "get_session_factory", lambda: factory)
    old_url, new_url = next(iter(LEGACY_SOURCE_REPLACEMENTS.items()))
    source_id = uuid4()
    async with factory() as session:
        session.add(
            NewsSource(
                id=source_id,
                name="Legacy source",
                url=old_url,
                source_type="rss",
                category="legacy",
            )
        )
        await session.commit()

    assert await seed_module.seed_sources() == len(DEFAULT_RSS_SOURCES) - 1
    assert await seed_module.seed_sources() == 0

    async with factory() as session:
        migrated = await session.get(NewsSource, source_id)
        sources = list((await session.scalars(select(NewsSource))).all())

    assert migrated is not None
    assert migrated.url == new_url
    assert migrated.enabled is True
    assert len(sources) == len(DEFAULT_RSS_SOURCES)
    await engine.dispose()

"""Idempotently seed the default RSS source catalog."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db.session import get_session_factory
from app.models.source import NewsSource

DEFAULT_RSS_SOURCES = (
    ("OpenAI Blog", "https://openai.com/news/rss.xml", "AI", "en", "US", 100),
    ("The Verge", "https://www.theverge.com/rss/index.xml", "科技", "en", "US", 80),
    ("Hacker News", "https://hnrss.org/frontpage", "编程", "en", None, 80),
    ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml", "财经", "en", "GB", 80),
    ("The Guardian Business", "https://www.theguardian.com/business/rss", "商业", "en", "GB", 70),
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", "国际", "en", "GB", 80),
    ("ScienceDaily", "https://www.sciencedaily.com/rss/top/science.xml", "科学", "en", "US", 70),
)


async def seed_sources() -> int:
    inserted = 0
    async with get_session_factory()() as session:
        for name, url, category, language, country, priority in DEFAULT_RSS_SOURCES:
            if await session.scalar(select(NewsSource).where(NewsSource.url == url)) is not None:
                continue
            session.add(
                NewsSource(
                    name=name,
                    url=url,
                    source_type="rss",
                    category=category,
                    language=language,
                    country=country,
                    priority=priority,
                )
            )
            inserted += 1
        await session.commit()
    return inserted


if __name__ == "__main__":
    print(f"seeded {asyncio.run(seed_sources())} RSS sources")

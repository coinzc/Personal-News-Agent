"""Idempotently seed the default RSS source catalog."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db.session import get_session_factory
from app.models.source import NewsSource

# These feeds are intentionally hosted on different domains.  The original BBC,
# Guardian and ScienceDaily feeds are not reachable from some server egress
# networks, while these public feeds provide equivalent coverage.
DEFAULT_RSS_SOURCES = (
    ("OpenAI Blog", "https://openai.com/news/rss.xml", "AI", "en", "US", 100),
    ("The Verge", "https://www.theverge.com/rss/index.xml", "科技", "en", "US", 80),
    ("Hacker News", "https://hnrss.org/frontpage", "编程", "en", None, 80),
    ("CNBC Business", "https://www.cnbc.com/id/10001147/device/rss/rss.html", "商业", "en", "US", 80),
    ("CNBC Finance", "https://www.cnbc.com/id/10000664/device/rss/rss.html", "财经", "en", "US", 80),
    ("Al Jazeera World", "https://www.aljazeera.com/xml/rss/all.xml", "国际", "en", None, 80),
    ("Science News", "https://www.sciencenews.org/feed", "科学", "en", "US", 70),
)

# Existing installations may still contain these records.  Updating the row in
# place preserves its primary key and all already-collected NewsItem relations.
LEGACY_SOURCE_REPLACEMENTS = {
    "https://feeds.bbci.co.uk/news/business/rss.xml": "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "https://www.theguardian.com/business/rss": "https://www.cnbc.com/id/10001147/device/rss/rss.html",
    "https://feeds.bbci.co.uk/news/world/rss.xml": "https://www.aljazeera.com/xml/rss/all.xml",
    "https://www.sciencedaily.com/rss/top/science.xml": "https://www.sciencenews.org/feed",
}


async def seed_sources() -> int:
    inserted = 0
    async with get_session_factory()() as session:
        # Migrate unreachable legacy feeds before inserting the current catalog.
        # If an administrator already added the replacement, disable the legacy
        # row instead of violating the URL unique constraint.
        for old_url, new_url in LEGACY_SOURCE_REPLACEMENTS.items():
            old_source = await session.scalar(select(NewsSource).where(NewsSource.url == old_url))
            if old_source is None:
                continue
            replacement = await session.scalar(select(NewsSource).where(NewsSource.url == new_url))
            if replacement is not None and replacement.id != old_source.id:
                old_source.enabled = False
                continue
            old_source.url = new_url
            old_source.enabled = True
        for name, url, category, language, country, priority in DEFAULT_RSS_SOURCES:
            source = await session.scalar(select(NewsSource).where(NewsSource.url == url))
            if source is not None:
                # Keep operator-managed priority/configuration, but ensure a
                # migrated source has the current display metadata.
                source.name = name
                source.category = category
                source.language = language
                source.country = country
                source.enabled = True
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

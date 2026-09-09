"""Persistence boundary for collector output."""
from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import CollectedNews
from app.models.news import NewsItem

logger = logging.getLogger(__name__)


class NewsIngestionService:
    """Store normalized collector items while isolating duplicate URLs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ingest(self, source: object, items: Sequence[CollectedNews]) -> tuple[int, int]:
        inserted = 0
        skipped = 0
        for item in items:
            model = NewsItem(
                title=item.title,
                url=item.url,
                source_id=getattr(source, "id", None),
                author=item.author,
                published_at=item.published_at,
                content=item.content,
                summary=item.summary,
                language=item.language,
                category=item.category,
                tags=item.tags,
                image_url=item.image_url,
                hash=item.hash,
            )
            self.session.add(model)
            try:
                await self.session.flush()
            except IntegrityError:
                await self.session.rollback()
                skipped += 1
                logger.info("Skipping duplicate news URL: %s", item.url)
            else:
                inserted += 1
        await self.session.commit()
        logger.info("News ingestion complete: inserted=%d skipped=%d", inserted, skipped)
        return inserted, skipped

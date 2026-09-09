"""Contracts and shared result types for asynchronous news collectors."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from app.models.source import NewsSource


class CollectorError(Exception):
    """Base error raised when a source cannot be collected."""


class CollectorHTTPError(CollectorError):
    """An upstream returned a non-success HTTP response."""

    def __init__(self, status_code: int | None, url: str) -> None:
        super().__init__(f"HTTP {status_code} while collecting {url}")
        self.status_code = status_code
        self.url = url


class InvalidFeedError(CollectorError):
    """The upstream body was not a usable RSS/Atom feed."""


@dataclass(slots=True)
class CollectedNews:
    """Normalized article data before it is mapped to a NewsItem."""

    title: str
    url: str
    author: str | None = None
    published_at: datetime | None = None
    content: str | None = None
    image_url: str | None = None
    language: str = "en"
    category: str = "technology"
    tags: list[str] = field(default_factory=list)
    content_hash: str | None = None


class BaseCollector(ABC):
    """Asynchronous collector interface independent of persistence logic."""

    @abstractmethod
    async def collect(self, source: NewsSource) -> list[CollectedNews]:
        """Collect normalized articles from one configured source."""

    async def collect_many(self, sources: list[NewsSource]) -> dict[str, list[CollectedNews] | Exception]:
        """Collect enabled sources concurrently while isolating failures."""

        enabled_sources = [source for source in sources if source.enabled]
        results = await asyncio.gather(*(self.collect(source) for source in enabled_sources), return_exceptions=True)
        return {
            str(source.id): cast(list[CollectedNews] | Exception, result)
            for source, result in zip(enabled_sources, results, strict=True)
        }

    @staticmethod
    def as_dict(item: CollectedNews) -> dict[str, Any]:
        """Convert normalized data to a serializable mapping for logging/tests."""

        return {
            "title": item.title,
            "url": item.url,
            "author": item.author,
            "published_at": item.published_at,
            "content": item.content,
            "image_url": item.image_url,
            "language": item.language,
            "category": item.category,
            "tags": item.tags,
            "content_hash": item.content_hash,
        }

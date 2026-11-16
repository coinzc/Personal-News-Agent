"""Persist LLM-assisted ranking scores on clustered news events."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Protocol

from app.llm.schemas import NewsRanking
from app.models.event import NewsEvent
from app.models.news import NewsItem

logger = logging.getLogger(__name__)


class RankingProvider(Protocol):
    async def rank(self, item: NewsItem) -> NewsRanking: ...


class NewsEventRankingService:
    """Score each unranked event once using its highest-priority source report."""

    def __init__(self, ranker: RankingProvider, *, max_concurrency: int = 5) -> None:
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be greater than zero")
        self.ranker = ranker
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def rank_unscored_events(self, items: Sequence[NewsItem]) -> Sequence[NewsItem]:
        candidates: dict[NewsEvent, NewsItem] = {}
        for item in items:
            for event in item.events:
                if (event.importance_score or 0.0) > 0:
                    continue
                current = candidates.get(event)
                if current is None or self._representative_key(item) > self._representative_key(current):
                    candidates[event] = item

        async def rank_event(event: NewsEvent, item: NewsItem) -> None:
            try:
                async with self._semaphore:
                    ranking = await self.ranker.rank(item)
            except Exception:
                logger.exception("News event ranking failed event_id=%s", event.id)
                return
            event.importance_score = ranking.importance_score
            event.priority = self._priority(ranking.importance_score)

        await asyncio.gather(*(rank_event(event, item) for event, item in candidates.items()))
        return items

    @staticmethod
    def _representative_key(item: NewsItem) -> tuple[int, int, int]:
        source_priority = item.source.priority if item.source is not None else 0
        return source_priority, len(item.content or ""), len(item.title)

    @staticmethod
    def _priority(score: float) -> str:
        if score >= 85:
            return "critical"
        if score >= 70:
            return "high"
        if score >= 50:
            return "medium"
        return "low"


__all__ = ["NewsEventRankingService", "RankingProvider"]

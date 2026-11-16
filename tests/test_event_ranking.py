from __future__ import annotations

import pytest
from app.llm.schemas import NewsRanking
from app.models import EventNews, NewsEvent, NewsItem, NewsSource
from app.services.digest_service import DailyDigestService
from app.services.news_event_ranking_service import NewsEventRankingService


class FakeRanker:
    def __init__(self, score: float) -> None:
        self.score = score
        self.calls: list[str] = []

    async def rank(self, item: NewsItem) -> NewsRanking:
        self.calls.append(item.title)
        return NewsRanking(
            importance=90,
            impact=80,
            novelty=70,
            credibility=90,
            relevance=80,
            importance_score=self.score,
        )


@pytest.mark.asyncio
async def test_event_ranking_persists_score_and_uses_one_representative_per_event() -> None:
    source = NewsSource(name="Trusted", url="https://example.test/rss", source_type="rss", category="AI", priority=90)
    event = NewsEvent(canonical_title="New model", category="AI")
    first = NewsItem(title="New model announced", url="https://example.test/1", category="AI", source=source)
    second = NewsItem(title="New model details", url="https://example.test/2", category="AI", source=source)
    event.event_news = [EventNews(event=event, news_item=first), EventNews(event=event, news_item=second)]
    first.events = [event]
    second.events = [event]
    ranker = FakeRanker(82)

    result = await NewsEventRankingService(ranker).rank_unscored_events([first, second])

    assert result == [first, second]
    assert event.importance_score == 82
    assert event.priority == "high"
    assert len(ranker.calls) == 1


@pytest.mark.asyncio
async def test_event_ranking_keeps_unranked_event_when_provider_fails() -> None:
    class BrokenRanker:
        async def rank(self, item: NewsItem) -> NewsRanking:
            raise RuntimeError("provider unavailable")

    event = NewsEvent(canonical_title="Unavailable", category="AI", importance_score=0, priority="low")
    item = NewsItem(title="Unavailable", url="https://example.test/unavailable", category="AI")
    event.event_news = [EventNews(event=event, news_item=item)]
    item.events = [event]

    await NewsEventRankingService(BrokenRanker()).rank_unscored_events([item])

    assert event.importance_score == 0
    assert event.priority == "low"


@pytest.mark.asyncio
async def test_digest_orders_items_by_persisted_event_score() -> None:
    lower_event = NewsEvent(canonical_title="Lower", category="AI", importance_score=42, priority="low")
    higher_event = NewsEvent(canonical_title="Higher", category="AI", importance_score=91, priority="critical")
    lower = NewsItem(title="Lower-scored story", url="https://example.test/lower", category="AI")
    higher = NewsItem(title="Higher-scored story", url="https://example.test/higher", category="AI")
    lower.events = [lower_event]
    higher.events = [higher_event]

    service = DailyDigestService(None)  # type: ignore[arg-type]
    sections = await service._build_sections([lower, higher])

    assert [row["title"] for row in sections["AI"]] == ["Higher-scored story", "Lower-scored story"]

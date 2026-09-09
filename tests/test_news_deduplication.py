"""Unit tests for the Phase 4 duplicate detection stages."""

from __future__ import annotations

import pytest
from app.models import NewsItem
from app.services.news_dedup_service import (
    DeduplicationConfig,
    MockEmbeddingProvider,
    NewsDedupService,
    normalize_title,
    normalize_url,
    url_hash,
)


def test_url_hash_ignores_tracking_parameters_and_fragment() -> None:
    first = "HTTPS://News.Example.test/article/42/?utm_source=rss&ref=home#comments"
    second = "https://news.example.test/article/42?ref=home"

    assert normalize_url(first) == normalize_url(second)
    assert url_hash(first) == url_hash(second)


def test_normalized_title_collapses_translation_aliases() -> None:
    chinese = normalize_title("OpenAI 发布了新模型")
    english = normalize_title("OpenAI announces a latest model")

    assert chinese == english


@pytest.mark.asyncio
async def test_title_similarity_matches_light_rewording() -> None:
    service = NewsDedupService(similarity_threshold=0.70)
    match = await service.compare_titles(
        "OpenAI unveils latest AI model",
        "OpenAI announces new AI model",
    )

    assert match is not None
    assert match.stage in {"normalized_title", "title_similarity"}
    assert match.score >= 0.70


@pytest.mark.asyncio
async def test_different_languages_can_match_same_event() -> None:
    service = NewsDedupService(similarity_threshold=0.70)
    first = NewsItem(title="OpenAI 发布新模型", url="https://example.test/cn", category="AI")
    second = NewsItem(title="OpenAI announces new model", url="https://example.test/en", category="AI")

    match = await service.find_duplicate(second, [first])

    assert match is not None
    assert match.candidate is first


@pytest.mark.asyncio
async def test_unrelated_titles_are_not_duplicates() -> None:
    service = NewsDedupService()
    first = NewsItem(title="OpenAI announces new model", url="https://example.test/ai", category="AI")
    second = NewsItem(
        title="Global markets fall after interest rate decision", url="https://example.test/market", category="finance"
    )

    assert await service.find_duplicate(second, [first]) is None


@pytest.mark.asyncio
async def test_embedding_provider_is_a_configurable_fourth_stage() -> None:
    provider = MockEmbeddingProvider({("A new event headline", "Completely different wording"): 0.91})
    service = NewsDedupService(
        config=DeduplicationConfig(similarity_threshold=0.99, embedding_threshold=0.85),
        embedding_provider=provider,
    )

    match = await service.compare_titles("A new event headline", "Completely different wording")

    assert match is not None
    assert match.stage == "embedding"
    assert match.score == 0.91


@pytest.mark.asyncio
async def test_deduplicate_retains_all_items_in_clusters() -> None:
    service = NewsDedupService(similarity_threshold=0.70)
    items = [
        NewsItem(title="OpenAI unveils latest AI model", url="https://example.test/1", category="AI"),
        NewsItem(title="OpenAI announces new AI model", url="https://example.test/2", category="AI"),
        NewsItem(title="A new game studio opens in Tokyo", url="https://example.test/3", category="game"),
    ]

    clusters = await service.deduplicate(items)

    assert sorted(len(cluster) for cluster in clusters) == [1, 2]
    assert sum(len(cluster) for cluster in clusters) == len(items)

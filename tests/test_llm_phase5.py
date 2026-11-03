"""Mocked tests for the Phase 5 DeepSeek boundary and news services."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from app.config import Settings
from app.llm.client import (
    LLMClient,
    LLMConfigurationError,
    LLMInvalidResponseError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMResponse,
    LLMServiceError,
    LLMTimeoutError,
)
from app.llm.deepseek import DeepSeekClient
from app.llm.schemas import NewsClassification, TokenUsage
from app.models.news import NewsItem
from app.services.news_llm_service import NewsClassifier, NewsRanker, NewsSummarizer
from openai import APITimeoutError, InternalServerError, RateLimitError


def _settings() -> Settings:
    return Settings(
        app_env="testing",
        deepseek_model="deepseek-chat",
        llm_timeout=1.0,
        llm_max_retries=2,
        llm_backoff_factor=0.0,
    )


def _response(content: str, *, refusal: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        model="deepseek-chat",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, refusal=refusal),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
    )


class FakeCompletions:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeSDK:
    def __init__(self, outcomes: list[object]) -> None:
        completions = FakeCompletions(outcomes)
        self.completions = completions
        self.chat = SimpleNamespace(completions=completions)


def _http_error(error_type: type[BaseException], status: int, message: str) -> BaseException:
    request = httpx.Request("POST", "https://api.deepseek.example/v1/chat/completions")
    response = httpx.Response(status, request=request)
    if error_type is APITimeoutError:
        return APITimeoutError(request=request)
    return error_type(message, response=response, body={})  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_deepseek_client_returns_json_mode_usage_and_latency() -> None:
    fake = FakeSDK([_response('{"category":"AI"}')])
    client = DeepSeekClient(settings=_settings(), client=fake)

    result = await client.complete([{"role": "user", "content": "classify"}], json_mode=True)

    assert result.content == '{"category":"AI"}'
    assert result.usage == TokenUsage(prompt_tokens=11, completion_tokens=7, total_tokens=18)
    assert result.latency_ms >= 0
    assert fake.completions.calls[0]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_deepseek_client_parses_function_tool_calls() -> None:
    raw = _response("")
    raw.choices[0].message.tool_calls = [
        SimpleNamespace(
            id="tool-call-1",
            function=SimpleNamespace(name="get_latest_news", arguments='{"category":"AI","limit":3}'),
        )
    ]
    raw.choices[0].finish_reason = "tool_calls"
    fake = FakeSDK([raw])
    client = DeepSeekClient(settings=_settings(), client=fake)

    result = await client.complete(
        [{"role": "user", "content": "AI news"}],
        tools=[{"type": "function", "function": {"name": "get_latest_news"}}],
    )

    assert result.content == ""
    assert result.tool_calls[0].name == "get_latest_news"
    assert result.tool_calls[0].arguments == {"category": "AI", "limit": 3}
    assert fake.completions.calls[0]["parallel_tool_calls"] is False


@pytest.mark.asyncio
async def test_deepseek_client_retries_rate_limit_and_server_errors() -> None:
    rate_error = _http_error(RateLimitError, 429, "rate limited")
    server_error = _http_error(InternalServerError, 503, "unavailable")
    fake = FakeSDK([rate_error, server_error, _response('{"ok":true}')])
    client = DeepSeekClient(settings=_settings(), client=fake)

    result = await client.complete([{"role": "user", "content": "retry"}])

    assert result.content == '{"ok":true}'
    assert len(fake.completions.calls) == 3


@pytest.mark.asyncio
async def test_deepseek_client_maps_timeout_and_rate_limit_after_retries() -> None:
    timeout_error = _http_error(APITimeoutError, 0, "timeout")
    timeout_fake = FakeSDK([timeout_error, timeout_error, timeout_error])
    timeout_client = DeepSeekClient(settings=_settings(), client=timeout_fake)
    with pytest.raises(LLMTimeoutError):
        await timeout_client.complete([])

    rate_error = _http_error(RateLimitError, 429, "rate limited")
    rate_fake = FakeSDK([rate_error, rate_error, rate_error])
    rate_client = DeepSeekClient(settings=_settings(), client=rate_fake)
    with pytest.raises(LLMRateLimitError):
        await rate_client.complete([])


@pytest.mark.asyncio
async def test_deepseek_client_maps_refusal_and_unexpected_upstream_failure() -> None:
    refusal_client = DeepSeekClient(settings=_settings(), client=FakeSDK([_response("", refusal="safety")]))
    with pytest.raises(LLMRefusalError):
        await refusal_client.complete([])

    failure_client = DeepSeekClient(settings=_settings(), client=FakeSDK([RuntimeError("internal secret")]))
    with pytest.raises(LLMServiceError) as error:
        await failure_client.complete([])
    assert "internal secret" not in str(error.value)


def test_deepseek_client_requires_key_only_when_creating_real_sdk() -> None:
    with pytest.raises(LLMConfigurationError):
        DeepSeekClient(settings=Settings(app_env="testing", deepseek_api_key=None))


class StubClient(LLMClient):
    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]], *, json_mode: bool = False) -> LLMResponse:
        self.messages.append(messages)
        return LLMResponse(content=self.content, model="fake", latency_ms=1.0)


class SequenceClient(LLMClient):
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents

    async def complete(self, messages: list[dict[str, str]], *, json_mode: bool = False) -> LLMResponse:
        return LLMResponse(content=self.contents.pop(0), model="fake", latency_ms=1.0)


@pytest.mark.asyncio
async def test_structured_client_rejects_invalid_json_and_schema() -> None:
    with pytest.raises(LLMInvalidResponseError, match="valid JSON"):
        await StubClient("not-json").complete_structured([], NewsClassification)

    with pytest.raises(LLMInvalidResponseError, match="schema"):
        await StubClient(json.dumps({"category": "AI", "confidence": 2.0})).complete_structured([], NewsClassification)


@pytest.mark.asyncio
async def test_news_classifier_summarizer_and_ranker_use_injected_client() -> None:
    item = NewsItem(
        title="OpenAI announces new model",
        url="https://example.test/news/1",
        category="AI",
        content="The article reports a model announcement.",
    )

    classifier_client = StubClient(
        json.dumps({"category": "AI", "subcategory": "LLM", "confidence": 0.94, "tags": ["OpenAI", "LLM"]})
    )
    classification = await NewsClassifier(classifier_client).classify(item)
    assert classification.category == "AI"
    assert classifier_client.messages[0][0]["role"] == "system"

    summarizer_client = StubClient(
        json.dumps(
            {
                "summary": "OpenAI announced a new model.",
                "key_points": ["A new model was announced."],
                "source_url": item.url,
            }
        )
    )
    summary = await NewsSummarizer(summarizer_client).summarize(item)
    assert str(summary.source_url) == item.url

    ranker_client = StubClient(
        json.dumps({"importance": 100, "impact": 80, "novelty": 60, "credibility": 90, "relevance": 50})
    )
    ranking = await NewsRanker(ranker_client).rank(item)
    assert ranking.importance_score == 82.0


@pytest.mark.asyncio
async def test_news_summary_tolerates_provider_metadata_and_missing_source_url() -> None:
    item = NewsItem(title="标题", url="https://example.test/news", category="AI", content="内容")
    client = StubClient(
        json.dumps(
            {
                "title_zh": "中文标题",
                "summary_zh": "中文摘要",
                "summary": "English summary",
                "extra_metadata": {"provider": "deepseek"},
            }
        )
    )
    summary = await NewsSummarizer(client).summarize(item)
    assert summary.title_zh == "中文标题"
    assert summary.summary_zh == "中文摘要"
    assert str(summary.source_url) == item.url


@pytest.mark.asyncio
async def test_news_summarizer_requests_translation_when_chinese_fields_are_missing() -> None:
    item = NewsItem(
        title="OpenAI announces new model",
        url="https://example.test/news/translation",
        category="AI",
        summary="OpenAI announced a new model.",
    )
    client = SequenceClient(
        [
            json.dumps({"summary": "OpenAI announced a new model."}),
            json.dumps({"title_zh": "OpenAI 发布新模型", "summary_zh": "OpenAI 发布了一款新模型。"}),
        ]
    )
    summary = await NewsSummarizer(client).summarize(item)
    assert summary.title_zh == "OpenAI 发布新模型"
    assert summary.summary_zh == "OpenAI 发布了一款新模型。"


@pytest.mark.asyncio
async def test_news_summarizer_accepts_chinese_fields_without_english_summary() -> None:
    item = NewsItem(title="OpenAI announces new model", url="https://example.test/news/zh", category="AI")
    client = StubClient(json.dumps({"title_zh": "OpenAI 发布新模型", "summary_zh": "OpenAI 发布了一款新模型。"}))
    summary = await NewsSummarizer(client).summarize(item)
    assert summary.title_zh == "OpenAI 发布新模型"
    assert summary.summary_zh == "OpenAI 发布了一款新模型。"

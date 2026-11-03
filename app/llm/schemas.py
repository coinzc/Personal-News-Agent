"""Validated contracts shared by LLM providers and news LLM services."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class StrictLLMSchema(BaseModel):
    """Reject unexpected model fields instead of silently accepting them."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TokenUsage(StrictLLMSchema):
    """Token accounting reported by a model provider."""

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class LLMResponse(StrictLLMSchema):
    """Provider-neutral text response plus operational metadata."""

    content: str
    model: str
    usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: float = Field(ge=0.0)
    finish_reason: str | None = None
    tool_calls: list[LLMToolCall] = Field(default_factory=list)


class LLMToolCall(StrictLLMSchema):
    """Provider-neutral function tool call requested by the model."""

    id: str
    name: str
    arguments: dict[str, object] = Field(default_factory=dict)


class NewsClassification(StrictLLMSchema):
    """Validated classification emitted by the model."""

    category: str = Field(min_length=1, max_length=64)
    subcategory: str | None = Field(default=None, max_length=100)
    confidence: float = Field(ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list, max_length=10)


class NewsSummary(StrictLLMSchema):
    """Grounded summary output for an article."""

    # Providers occasionally add harmless metadata or omit provenance while
    # translating long articles; the service restores the trusted source URL.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    summary: str = Field(min_length=1, max_length=2_000)
    key_points: list[str] = Field(default_factory=list, max_length=8)
    source_url: HttpUrl | None = None
    title_zh: str | None = Field(default=None, max_length=500)
    summary_zh: str | None = Field(default=None, max_length=2_000)


class NewsRanking(StrictLLMSchema):
    """LLM-assisted ranking factors; final score remains deterministic."""

    importance: float = Field(ge=0.0, le=100.0)
    impact: float = Field(ge=0.0, le=100.0)
    novelty: float = Field(ge=0.0, le=100.0)
    credibility: float = Field(ge=0.0, le=100.0)
    relevance: float = Field(ge=0.0, le=100.0)
    importance_score: float = Field(default=0.0, ge=0.0, le=100.0)


class NewsRankingFactors(StrictLLMSchema):
    """Model-only factors used to derive a deterministic final score."""

    importance: float = Field(ge=0.0, le=100.0)
    impact: float = Field(ge=0.0, le=100.0)
    novelty: float = Field(ge=0.0, le=100.0)
    credibility: float = Field(ge=0.0, le=100.0)
    relevance: float = Field(ge=0.0, le=100.0)

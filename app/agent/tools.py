"""Extensible, validated tool registry for the News Agent.

Tools are the only boundary through which the Agent reaches news business
capabilities.  The registry is deliberately independent from SQLAlchemy;
production adapters can use repositories while tests inject a small fake
service.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, is_dataclass
from datetime import date
from typing import Any, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.llm.client import ToolDefinition


class ToolExecutionError(Exception):
    """A safe, user-facing tool execution failure."""


class SearchNewsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=300)
    category: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=10, ge=1, le=50)


class LatestNewsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=10, ge=1, le=50)


class CategoryNewsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=64)
    limit: int = Field(default=10, ge=1, le=50)


class NewsDetailArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    news_id: UUID | None = None
    url: str | None = Field(default=None, max_length=2_000)


class SearchEventsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=300)
    category: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=10, ge=1, le=50)


class DailyDigestArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    digest_date: date | None = None


class AnalyzeNewsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    news_id: UUID
    question: str | None = Field(default=None, max_length=1_000)


class SummarizeNewsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    news_id: UUID


class NewsToolService(Protocol):
    """Business service contract implemented outside the Agent layer."""

    async def search_news(self, query: str, category: str | None, limit: int) -> Any: ...

    async def get_latest_news(self, category: str | None, limit: int) -> Any: ...

    async def get_news_by_category(self, category: str, limit: int) -> Any: ...

    async def get_news_detail(self, news_id: UUID | None, url: str | None) -> Any: ...

    async def search_events(self, query: str, category: str | None, limit: int) -> Any: ...

    async def get_daily_digest(self, digest_date: date | None) -> Any: ...

    async def analyze_news(self, news_id: UUID, question: str | None) -> Any: ...

    async def summarize_news(self, news_id: UUID) -> Any: ...


ToolHandler = Callable[[Any], Awaitable[Any]]


class ToolSpec:
    """Name, JSON schema and validated async handler for one tool."""

    def __init__(self, name: str, description: str, args_model: type[BaseModel], handler: ToolHandler) -> None:
        self.name = name
        self.description = description
        self.args_model = args_model
        self.handler = handler

    def definition(self) -> ToolDefinition:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }

    async def execute(self, arguments: dict[str, object]) -> Any:
        try:
            parsed = self.args_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolExecutionError(f"Invalid arguments for tool {self.name}") from exc
        try:
            return await self.handler(parsed)
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(f"Tool {self.name} failed") from exc


class ToolRegistry:
    """Registry that makes adding a new tool a registration-only change."""

    def __init__(self, specs: list[ToolSpec] | None = None) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def definitions(self) -> list[ToolDefinition]:
        return [spec.definition() for spec in self._specs.values()]

    async def execute(self, name: str, arguments: dict[str, object]) -> Any:
        spec = self.get(name)
        if spec is None:
            raise ToolExecutionError(f"Unknown tool: {name}")
        return await spec.execute(arguments)

    def __contains__(self, name: str) -> bool:
        return name in self._specs


def _jsonable(value: Any) -> Any:
    """Convert service results into safe JSON-compatible tool messages."""

    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="json"))
    if is_dataclass(value):
        return _jsonable(asdict(cast(Any, value)))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    return value


def build_news_tool_registry(service: NewsToolService) -> ToolRegistry:
    """Build the standard news tool set around an injected business service."""

    async def search_news(args: SearchNewsArgs) -> Any:
        return _jsonable(await service.search_news(args.query, args.category, args.limit))

    async def get_latest_news(args: LatestNewsArgs) -> Any:
        return _jsonable(await service.get_latest_news(args.category, args.limit))

    async def get_news_by_category(args: CategoryNewsArgs) -> Any:
        return _jsonable(await service.get_news_by_category(args.category, args.limit))

    async def get_news_detail(args: NewsDetailArgs) -> Any:
        if args.news_id is None and args.url is None:
            raise ToolExecutionError("news_id or url is required")
        return _jsonable(await service.get_news_detail(args.news_id, args.url))

    async def search_events(args: SearchEventsArgs) -> Any:
        return _jsonable(await service.search_events(args.query, args.category, args.limit))

    async def get_daily_digest(args: DailyDigestArgs) -> Any:
        return _jsonable(await service.get_daily_digest(args.digest_date))

    async def analyze_news(args: AnalyzeNewsArgs) -> Any:
        return _jsonable(await service.analyze_news(args.news_id, args.question))

    async def summarize_news(args: SummarizeNewsArgs) -> Any:
        return _jsonable(await service.summarize_news(args.news_id))

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "search_news", "Search news by keywords, optionally filtered by category.", SearchNewsArgs, search_news
        )
    )
    registry.register(
        ToolSpec(
            "get_latest_news", "Get the latest news, optionally filtered by category.", LatestNewsArgs, get_latest_news
        )
    )
    registry.register(
        ToolSpec("get_news_by_category", "List recent news in one category.", CategoryNewsArgs, get_news_by_category)
    )
    registry.register(
        ToolSpec("get_news_detail", "Get one article by ID or canonical URL.", NewsDetailArgs, get_news_detail)
    )
    registry.register(
        ToolSpec("search_events", "Search clustered events by keywords and category.", SearchEventsArgs, search_events)
    )
    registry.register(
        ToolSpec("get_daily_digest", "Get a generated daily news digest.", DailyDigestArgs, get_daily_digest)
    )
    registry.register(
        ToolSpec(
            "analyze_news", "Analyze an article and answer a focused question about it.", AnalyzeNewsArgs, analyze_news
        )
    )
    registry.register(
        ToolSpec("summarize_news", "Create a grounded summary for one article.", SummarizeNewsArgs, summarize_news)
    )
    return registry


__all__ = [
    "AnalyzeNewsArgs",
    "CategoryNewsArgs",
    "DailyDigestArgs",
    "LatestNewsArgs",
    "NewsDetailArgs",
    "NewsToolService",
    "SearchEventsArgs",
    "SearchNewsArgs",
    "SummarizeNewsArgs",
    "ToolExecutionError",
    "ToolRegistry",
    "ToolSpec",
    "build_news_tool_registry",
]

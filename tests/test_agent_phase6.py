"""Mock DeepSeek tool-calling tests for Phase 6."""

from __future__ import annotations

import pytest
from app.agent.agent import NewsAgent
from app.agent.memory import InMemoryConversationMemory, SQLAlchemyConversationMemory
from app.agent.tools import ToolExecutionError, build_news_tool_registry
from app.db.base import Base
from app.llm.client import LLMClient
from app.llm.schemas import LLMResponse, LLMToolCall
from app.models import AgentConversation, AgentMessage, User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


class MockAgentLLM(LLMClient):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    async def complete(self, messages, *, json_mode=False, tools=None):
        self.calls.append({"messages": messages, "json_mode": json_mode, "tools": tools})
        return self.responses.pop(0)


class FakeNewsService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.article_id = __import__("uuid").uuid4()

    async def search_news(self, query, category, limit):
        self.calls.append(("search_news", (query, category, limit)))
        return [{"title": "Latest headline", "url": "https://example.test/latest"}]

    async def get_latest_news(self, category, limit):
        self.calls.append(("get_latest_news", (category, limit)))
        return [{"title": "Today's headline", "url": "https://example.test/today"}]

    async def get_news_by_category(self, category, limit):
        self.calls.append(("get_news_by_category", (category, limit)))
        return [{"title": f"{category} headline", "category": category}]

    async def get_news_detail(self, news_id, url):
        self.calls.append(("get_news_detail", (news_id, url)))
        return {"id": str(news_id or self.article_id), "title": "Detailed article", "url": url}

    async def search_events(self, query, category, limit):
        self.calls.append(("search_events", (query, category, limit)))
        return [{"canonical_title": "Historical event", "category": category}]

    async def get_daily_digest(self, digest_date):
        self.calls.append(("get_daily_digest", digest_date))
        return {"digest_date": str(digest_date or "today"), "content": "Daily digest"}

    async def analyze_news(self, news_id, question):
        self.calls.append(("analyze_news", (news_id, question)))
        return {"news_id": str(news_id), "analysis": "Important because of its impact."}

    async def summarize_news(self, news_id):
        self.calls.append(("summarize_news", news_id))
        return {"news_id": str(news_id), "summary": "Short summary."}


def response(content: str = "", calls: list[LLMToolCall] | None = None) -> LLMResponse:
    return LLMResponse(content=content, model="mock", latency_ms=1, tool_calls=calls or [])


async def run_agent(service: FakeNewsService, calls: list[LLMToolCall], final: str, prompt: str) -> NewsAgent:
    llm = MockAgentLLM([response(calls=calls), response(final)])
    agent = NewsAgent(llm, build_news_tool_registry(service), InMemoryConversationMemory())
    result = await agent.handle(prompt, session_key="test-session")
    assert result.content == final
    assert result.tool_calls[0]["function"]["name"] == calls[0].name
    assert llm.calls[0]["tools"]
    return agent


@pytest.mark.asyncio
async def test_agent_queries_today_news_with_latest_tool() -> None:
    service = FakeNewsService()
    await run_agent(
        service,
        [LLMToolCall(id="call-1", name="get_latest_news", arguments={"limit": 5})],
        "今天的重要新闻是 Today's headline。",
        "今天有什么重要新闻？",
    )
    assert service.calls == [("get_latest_news", (None, 5))]


@pytest.mark.asyncio
async def test_agent_queries_ai_news_with_category_tool() -> None:
    service = FakeNewsService()
    await run_agent(
        service,
        [LLMToolCall(id="call-2", name="get_news_by_category", arguments={"category": "AI", "limit": 3})],
        "AI 新闻结果。",
        "只看 AI 新闻。",
    )
    assert service.calls == [("get_news_by_category", ("AI", 3))]


@pytest.mark.asyncio
async def test_agent_queries_article_detail_by_id() -> None:
    service = FakeNewsService()
    await run_agent(
        service,
        [LLMToolCall(id="call-3", name="get_news_detail", arguments={"news_id": str(service.article_id)})],
        "这是新闻详情。",
        "分析这条新闻。",
    )
    assert service.calls == [("get_news_detail", (service.article_id, None))]


@pytest.mark.asyncio
async def test_agent_queries_history_with_search_events_tool() -> None:
    service = FakeNewsService()
    await run_agent(
        service,
        [LLMToolCall(id="call-4", name="search_events", arguments={"query": "AI", "limit": 10})],
        "过去一周的 AI 重大事件。",
        "过去一周 AI 行业有哪些重大事件？",
    )
    assert service.calls == [("search_events", ("AI", None, 10))]


@pytest.mark.asyncio
async def test_agent_persists_turn_and_tool_calls_in_memory() -> None:
    service = FakeNewsService()
    memory = InMemoryConversationMemory()
    llm = MockAgentLLM(
        [response(calls=[LLMToolCall(id="call-5", name="get_daily_digest", arguments={})]), response("日报内容")]
    )
    result = await NewsAgent(llm, build_news_tool_registry(service), memory).handle(
        "给我今天的日报", session_key="wechat:open-id"
    )
    assert result.conversation_id is not None
    assert memory.turns[0].user_message == "给我今天的日报"
    assert memory.turns[0].tool_calls[0]["function"]["name"] == "get_daily_digest"
    assert len(await memory.load_messages("wechat:open-id")) == 2


@pytest.mark.asyncio
async def test_tool_registry_rejects_unknown_and_invalid_calls() -> None:
    registry = build_news_tool_registry(FakeNewsService())
    with pytest.raises(ToolExecutionError, match="Unknown tool"):
        await registry.execute("drop_database", {})
    with pytest.raises(ToolExecutionError, match="Invalid arguments"):
        await registry.execute("get_news_by_category", {"category": "AI", "limit": 0})
    with pytest.raises(ToolExecutionError, match="news_id or url"):
        await registry.execute("get_news_detail", {})


@pytest.mark.asyncio
async def test_sqlalchemy_memory_persists_and_loads_agent_messages(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agent-memory.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = User(display_name="Test user")
        session.add(user)
        await session.commit()
        memory = SQLAlchemyConversationMemory(session, user.id, channel="test")
        turn = await memory.save_turn(
            "test-session",
            "今天有什么新闻？",
            "这里是新闻摘要。",
            [{"id": "call-1", "function": {"name": "get_latest_news", "arguments": {}}}],
        )
        messages = await memory.load_messages("test-session")

        assert turn.conversation_id is not None
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert messages[1]["tool_calls"][0]["function"]["name"] == "get_latest_news"
        assert await session.scalar(select(func.count()).select_from(AgentConversation)) == 1
        assert await session.scalar(select(func.count()).select_from(AgentMessage)) == 2
    await engine.dispose()

"""Tool-calling News Agent orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.agent.memory import AgentMemory
from app.agent.planner import AgentPlanner
from app.agent.tools import ToolExecutionError, ToolRegistry
from app.llm.client import LLMClient
from app.llm.schemas import TokenUsage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentResult:
    content: str
    conversation_id: UUID | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)


class NewsAgent:
    """Understand requests, select tools, aggregate results, and answer."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        memory: AgentMemory,
        *,
        planner: AgentPlanner | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.memory = memory
        self.planner = planner or AgentPlanner()

    async def handle(self, user_message: str, *, session_key: str = "default") -> AgentResult:
        normalized = user_message.strip()
        if not normalized:
            raise ValueError("user_message must not be empty")
        if len(normalized) > 4_000:
            raise ValueError("user_message is too long")
        messages = self.planner.initial_messages(await self.memory.load_messages(session_key), normalized)
        recorded: list[dict[str, Any]] = []
        total = TokenUsage()
        final = ""
        for _ in range(self.planner.max_tool_rounds):
            response = await self.llm_client.complete(messages, tools=self.tool_registry.definitions())
            total = TokenUsage(
                prompt_tokens=total.prompt_tokens + response.usage.prompt_tokens,
                completion_tokens=total.completion_tokens + response.usage.completion_tokens,
                total_tokens=total.total_tokens + response.usage.total_tokens,
            )
            if not response.tool_calls:
                final = response.content.strip()
                break
            messages.append(self.planner.assistant_tool_message(response.content, response.tool_calls))
            for call in response.tool_calls:
                recorded.append(
                    {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}}
                )
                try:
                    result = await self.tool_registry.execute(call.name, call.arguments)
                except ToolExecutionError as exc:
                    result = {"error": str(exc)}
                messages.append(self.planner.tool_result_message(call, result))
        else:
            final = "I could not complete the requested news lookup within the tool-call limit."
        final = final or "I could not produce a response from the available news data."
        turn = await self.memory.save_turn(session_key, normalized, final, recorded)
        logger.info("Agent turn completed conversation_id=%s tool_calls=%d", turn.conversation_id, len(recorded))
        return AgentResult(content=final, conversation_id=turn.conversation_id, tool_calls=recorded, usage=total)

    async def chat(self, user_message: str, *, session_key: str = "default") -> AgentResult:
        return await self.handle(user_message, session_key=session_key)


__all__ = ["AgentResult", "NewsAgent"]

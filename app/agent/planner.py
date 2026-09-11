"""Message and tool-call planning helpers for the News Agent."""

from __future__ import annotations

import json
from typing import Any

from app.agent.prompts import agent_system_prompt
from app.llm.schemas import LLMToolCall


class AgentPlanner:
    """Build provider-compatible planning messages without domain branching."""

    def __init__(self, *, system_prompt: str | None = None, max_tool_rounds: int = 4) -> None:
        if max_tool_rounds < 1:
            raise ValueError("max_tool_rounds must be positive")
        self.system_prompt = system_prompt or agent_system_prompt()
        self.max_tool_rounds = max_tool_rounds

    def initial_messages(self, history: list[dict[str, Any]], user_message: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        messages.extend(dict(message) for message in history)
        messages.append({"role": "user", "content": user_message})
        return messages

    @staticmethod
    def assistant_tool_message(content: str, calls: list[LLMToolCall]) -> dict[str, Any]:
        """Serialize a provider-neutral response into an OpenAI tool-call message."""

        return {
            "role": "assistant",
            "content": content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)},
                }
                for call in calls
            ],
        }

    @staticmethod
    def tool_result_message(call: LLMToolCall, result: Any) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": call.id,
            "content": json.dumps(result, ensure_ascii=False, default=str),
        }

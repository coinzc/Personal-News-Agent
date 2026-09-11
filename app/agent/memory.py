"""Conversation memory adapters for the Agent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.conversation import AgentConversation, AgentMessage


@dataclass(slots=True)
class ConversationTurn:
    """Persistable summary of one user/assistant interaction."""

    conversation_id: UUID
    user_message: str
    assistant_message: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AgentMemory(ABC):
    """Storage boundary used by Agent orchestration."""

    @abstractmethod
    async def load_messages(self, session_key: str) -> list[dict[str, Any]]:
        """Load prior OpenAI-compatible messages for one session."""

    @abstractmethod
    async def save_turn(
        self,
        session_key: str,
        user_message: str,
        assistant_message: str,
        tool_calls: list[dict[str, Any]],
    ) -> ConversationTurn:
        """Persist one completed interaction."""


class InMemoryConversationMemory(AgentMemory):
    """Deterministic memory adapter for unit tests and local development."""

    def __init__(self) -> None:
        self._messages: dict[str, list[dict[str, Any]]] = {}
        self.turns: list[ConversationTurn] = []
        self._ids: dict[str, UUID] = {}

    async def load_messages(self, session_key: str) -> list[dict[str, Any]]:
        return [dict(message) for message in self._messages.get(session_key, [])]

    async def save_turn(
        self,
        session_key: str,
        user_message: str,
        assistant_message: str,
        tool_calls: list[dict[str, Any]],
    ) -> ConversationTurn:
        conversation_id = self._ids.setdefault(session_key, uuid4())
        messages = self._messages.setdefault(session_key, [])
        messages.append({"role": "user", "content": user_message})
        assistant: dict[str, Any] = {"role": "assistant", "content": assistant_message}
        if tool_calls:
            assistant["tool_calls"] = tool_calls
        messages.append(assistant)
        turn = ConversationTurn(
            conversation_id=conversation_id,
            user_message=user_message,
            assistant_message=assistant_message,
            tool_calls=[dict(call) for call in tool_calls],
        )
        self.turns.append(turn)
        return turn


class SQLAlchemyConversationMemory(AgentMemory):
    """PostgreSQL/SQLite persistence adapter for Agent conversations."""

    def __init__(self, session: AsyncSession, user_id: UUID, *, channel: str = "wechat") -> None:
        self.session = session
        self.user_id = user_id
        self.channel = channel

    async def _conversation(self, session_key: str) -> AgentConversation | None:
        statement = (
            select(AgentConversation)
            .options(selectinload(AgentConversation.messages))
            .where(AgentConversation.session_key == session_key)
        )
        return cast(AgentConversation | None, await self.session.scalar(statement))

    @staticmethod
    def _wire_message(message: AgentMessage) -> dict[str, Any]:
        wire: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.role == "tool" and message.tool_call_id:
            wire["tool_call_id"] = message.tool_call_id
        if message.role == "assistant":
            calls = message.message_metadata.get("tool_calls")
            if calls:
                wire["tool_calls"] = calls
        return wire

    async def load_messages(self, session_key: str) -> list[dict[str, Any]]:
        conversation = await self._conversation(session_key)
        if conversation is None:
            return []
        return [self._wire_message(message) for message in conversation.messages]

    async def save_turn(
        self,
        session_key: str,
        user_message: str,
        assistant_message: str,
        tool_calls: list[dict[str, Any]],
    ) -> ConversationTurn:
        conversation = await self._conversation(session_key)
        if conversation is None:
            conversation = AgentConversation(
                user_id=self.user_id,
                session_key=session_key,
                channel=self.channel,
                messages=[],
            )
            self.session.add(conversation)
            await self.session.flush()
        conversation.messages.append(AgentMessage(role="user", content=user_message))
        conversation.messages.append(
            AgentMessage(
                role="assistant",
                content=assistant_message,
                message_metadata={"tool_calls": tool_calls} if tool_calls else {},
            )
        )
        await self.session.commit()
        return ConversationTurn(
            conversation_id=conversation.id,
            user_message=user_message,
            assistant_message=assistant_message,
            tool_calls=tool_calls,
        )


__all__ = ["AgentMemory", "ConversationTurn", "InMemoryConversationMemory", "SQLAlchemyConversationMemory"]

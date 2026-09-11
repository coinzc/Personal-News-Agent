"""Message channel abstractions used by the digest delivery service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MessageResult:
    message_id: str | None = None
    provider: str = "unknown"


class ChannelError(RuntimeError):
    """A channel rejected or failed to deliver a message."""


class MessageChannel(ABC):
    """Provider-neutral outbound message channel."""

    @abstractmethod
    async def send_text(self, recipient: str, content: str) -> MessageResult:
        """Send one text message."""

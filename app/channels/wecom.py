"""Enterprise WeChat group bot outbound message adapter."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.channels.base import ChannelError, MessageChannel, MessageResult


class WeComGroupBotAdapter(MessageChannel):
    """Deliver text or Markdown through an Enterprise WeChat group bot."""

    def __init__(
        self,
        *,
        webhook: str | None = None,
        message_type: str = "markdown",
        timeout: float = 15.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        max_chars: int = 3_500,
        client: httpx.AsyncClient | None = None,
        sender: Callable[[str, str, str], Awaitable[MessageResult]] | None = None,
    ) -> None:
        if message_type not in {"text", "markdown"}:
            raise ValueError("message_type must be text or markdown")
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        self.webhook = webhook
        self.message_type = message_type
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.max_chars = max_chars
        self._client = client
        self._sender = sender

    def split_message(self, content: str) -> list[str]:
        """Split on lines and keep each UTF-8 payload within the configured limit."""

        if not content:
            raise ValueError("content must not be empty")
        chunks: list[str] = []
        current = ""
        for line in content.splitlines(keepends=True):
            if len((current + line).encode("utf-8")) <= self.max_chars:
                current += line
                continue
            if current:
                chunks.append(current.rstrip())
                current = ""
            while len(line.encode("utf-8")) > self.max_chars:
                cut = self._safe_cut(line, self.max_chars)
                chunks.append(line[:cut])
                line = line[cut:]
            current = line
        if current:
            chunks.append(current.rstrip())
        return chunks or [content[: self._safe_cut(content, self.max_chars)]]

    @staticmethod
    def _safe_cut(value: str, max_bytes: int) -> int:
        size = 0
        for index, character in enumerate(value):
            next_size = len(character.encode("utf-8"))
            if size + next_size > max_bytes:
                return max(index, 1)
            size += next_size
        return len(value)

    async def send_text(self, recipient: str, content: str) -> MessageResult:
        del recipient  # Group bots address the configured group, not a user ID.
        chunks = self.split_message(content)
        last: MessageResult | None = None
        for index, chunk in enumerate(chunks, start=1):
            body = chunk if len(chunks) == 1 else f"今日新闻早报（{index}/{len(chunks)}）\n\n{chunk}"
            last = await self._send_chunk(body)
        return last or MessageResult(provider="wecom_group_bot")

    async def _send_chunk(self, content: str) -> MessageResult:
        for attempt in range(self.max_retries + 1):
            started = time.perf_counter()
            try:
                if self._sender is not None:
                    return await self._sender(self.message_type, content, self.webhook or "")
                if not self.webhook:
                    raise ChannelError("Enterprise WeChat webhook is not configured")
                payload: dict[str, Any]
                if self.message_type == "markdown":
                    payload = {"msgtype": "markdown", "markdown": {"content": content}}
                else:
                    payload = {"msgtype": "text", "text": {"content": content}}
                context: Any = (
                    httpx.AsyncClient(timeout=self.timeout) if self._client is None else _ClientContext(self._client)
                )
                async with context as client:
                    response = await client.post(self.webhook, json=payload)
                    if response.status_code == 429 or response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            "retryable Enterprise WeChat response",
                            request=response.request,
                            response=response,
                        )
                    response.raise_for_status()
                    result = response.json() if response.content else {}
                    if result.get("errcode", 0) != 0:
                        raise ChannelError("Enterprise WeChat rejected the message")
                    return MessageResult(provider="wecom_group_bot")
            except ChannelError:
                raise
            except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
                if attempt >= self.max_retries:
                    raise ChannelError("Enterprise WeChat delivery failed after retries") from exc
                await asyncio.sleep(self.backoff_factor * 2**attempt)
            finally:
                elapsed = time.perf_counter() - started
                _ = elapsed  # Keep timing available for tracing without logging secrets.
        raise ChannelError("Enterprise WeChat delivery failed")


class _ClientContext:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


__all__ = ["WeComGroupBotAdapter"]

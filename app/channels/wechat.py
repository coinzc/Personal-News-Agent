"""Wechat-compatible outbound adapter with retry and message chunking."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.channels.base import ChannelError, MessageChannel, MessageResult


class WeChatAdapter(MessageChannel):
    """Send text through a configured WeChat gateway/webhook.

    The adapter deliberately does not assume a personal-WeChat SDK. A gateway
    callable or HTTP endpoint can be injected, making this safe to test and
    replace with the deployment's approved WeChat integration.
    """

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        token: str | None = None,
        timeout: float = 15.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        max_chars: int = 3_500,
        client: httpx.AsyncClient | None = None,
        sender: Callable[[str, str, str | None], Awaitable[MessageResult]] | None = None,
    ) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        self.endpoint = endpoint
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.max_chars = max_chars
        self._client = client
        self._sender = sender

    def split_message(self, content: str) -> list[str]:
        """Split on line boundaries while preserving readable chunks."""

        if not content:
            raise ValueError("content must not be empty")
        chunks: list[str] = []
        current = ""
        for line in content.splitlines(keepends=True):
            if len(current) + len(line) <= self.max_chars:
                current += line
                continue
            if current:
                chunks.append(current.rstrip())
                current = ""
            while len(line) > self.max_chars:
                chunks.append(line[: self.max_chars])
                line = line[self.max_chars :]
            current = line
        if current:
            chunks.append(current.rstrip())
        return chunks or [content[: self.max_chars]]

    async def send_text(self, recipient: str, content: str) -> MessageResult:
        chunks = self.split_message(content)
        last: MessageResult | None = None
        for chunk in chunks:
            last = await self._send_chunk(recipient, chunk)
        return last or MessageResult(provider="wechat")

    async def _send_chunk(self, recipient: str, content: str) -> MessageResult:
        for attempt in range(self.max_retries + 1):
            try:
                if self._sender is not None:
                    return await self._sender(recipient, content, self.token)
                if not self.endpoint:
                    raise ChannelError("WeChat endpoint is not configured")
                client_context: Any = (
                    httpx.AsyncClient(timeout=self.timeout) if self._client is None else _ClientContext(self._client)
                )
                async with client_context as client:
                    response = await client.post(
                        self.endpoint,
                        json={"recipient": recipient, "content": content},
                        headers={"Authorization": f"Bearer {self.token}"} if self.token else None,
                    )
                    if response.status_code == 429 or response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            "retryable WeChat response", request=response.request, response=response
                        )
                    response.raise_for_status()
                    payload: dict[str, Any] = response.json() if response.content else {}
                    return MessageResult(
                        message_id=str(payload.get("message_id")) if payload.get("message_id") else None,
                        provider="wechat",
                    )
            except ChannelError:
                raise
            except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
                if attempt >= self.max_retries:
                    raise ChannelError("WeChat delivery failed after retries") from exc
                await asyncio.sleep(self.backoff_factor * 2**attempt)
        raise ChannelError("WeChat delivery failed")


class _ClientContext:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


__all__ = ["WeChatAdapter"]

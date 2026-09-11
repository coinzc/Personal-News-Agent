from __future__ import annotations

import httpx
import pytest
from app.channels.base import ChannelError, MessageResult
from app.channels.wechat import WeChatAdapter


@pytest.mark.asyncio
async def test_wechat_adapter_chunks_and_sends_in_order() -> None:
    sent: list[str] = []

    async def sender(recipient: str, content: str, token: str | None) -> MessageResult:
        assert recipient == "open-id"
        assert token == "secret"
        sent.append(content)
        return MessageResult(message_id=str(len(sent)), provider="wechat")

    adapter = WeChatAdapter(token="secret", max_chars=12, sender=sender)
    result = await adapter.send_text("open-id", "12345\n67890\nabc")
    assert sent == ["12345\n67890", "abc"]
    assert result.message_id == "2"


@pytest.mark.asyncio
async def test_wechat_adapter_retries_429() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, request=request)
        return httpx.Response(200, json={"message_id": "ok"}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = WeChatAdapter(endpoint="https://wechat.test/send", client=client, backoff_factor=0)
    result = await adapter.send_text("open-id", "hello")
    await client.aclose()
    assert attempts == 2
    assert result.message_id == "ok"


@pytest.mark.asyncio
async def test_wechat_adapter_requires_endpoint_or_sender() -> None:
    with pytest.raises(ChannelError, match="endpoint"):
        await WeChatAdapter().send_text("open-id", "hello")

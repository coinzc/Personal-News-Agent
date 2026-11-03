from __future__ import annotations

import json

import httpx
import pytest
from app.channels.base import ChannelError
from app.channels.wecom import WeComGroupBotAdapter


@pytest.mark.asyncio
async def test_wecom_sends_markdown_and_chunks_utf8() -> None:
    requests: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = WeComGroupBotAdapter(
        webhook="https://qyapi.test/cgi-bin/webhook/send?key=secret", client=client, max_chars=20
    )
    result = await adapter.send_text("ignored", "标题\n这是较长的一段中文内容")
    await client.aclose()
    assert result.provider == "wecom_group_bot"
    assert all(item["msgtype"] == "markdown" for item in requests)
    assert len(requests) > 1
    assert all(len(item["markdown"]["content"].encode("utf-8")) <= 20 for item in requests)


@pytest.mark.asyncio
async def test_wecom_retries_http_429() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, request=request)
        return httpx.Response(200, json={"errcode": 0}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await WeComGroupBotAdapter(webhook="https://qyapi.test/send", client=client, backoff_factor=0).send_text(
        "x", "hello"
    )
    await client.aclose()
    assert attempts == 2


@pytest.mark.asyncio
async def test_wecom_rejects_api_error_without_leaking_webhook() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 40001, "errmsg": "bad"}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ChannelError, match="rejected"):
        await WeComGroupBotAdapter(webhook="https://qyapi.test/send?key=secret", client=client).send_text("x", "hello")
    await client.aclose()

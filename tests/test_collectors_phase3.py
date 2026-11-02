from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from app.collectors.base import CollectorHTTPError, InvalidFeedError
from app.collectors.rss import RSSCollector

RSS = """<rss version="2.0"><channel><item><title>Example &amp; release</title>
<link>HTTPS://Example.com/a/?utm_source=x#f</link><author>Jane</author>
<pubDate>Tue, 02 Jan 2024 03:04:05 GMT</pubDate>
<description><![CDATA[<p>Useful <b>summary</b>.</p><script>x</script>]]></description>
</item></channel></rss>"""


def source(url: str = "https://feed.test/rss", enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), url=url, enabled=enabled, language="en", category="technology")


@pytest.mark.asyncio
async def test_parse_clean_and_normalize() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS.encode(), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        item = (await RSSCollector(client=client, backoff_factor=0).collect(source()))[0]
    assert item.title == "Example & release"
    assert item.url == "https://example.com/a"
    assert item.author == "Jane"
    assert item.content == "Useful summary."
    assert item.published_at is not None
    assert item.published_at.isoformat() == "2024-01-02T03:04:05+00:00"


@pytest.mark.asyncio
async def test_follow_redirects() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rss":
            return httpx.Response(307, headers={"location": "/feed"}, request=request)
        return httpx.Response(200, content=RSS.encode(), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await RSSCollector(client=client, backoff_factor=0).collect(source("https://feed.test/rss"))
    assert len(items) == 1


def test_helpers() -> None:
    assert RSSCollector.normalize_url("HTTP://Example.COM:80/p/?utm_x=1&ok=2#f") == "http://example.com/p?ok=2"
    assert RSSCollector.clean_html("<p>A</p><script>x</script>") == "A"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,retries", [(404, 0), (503, 2)])
async def test_http_errors(status: int, retries: int) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CollectorHTTPError) as error:
            await RSSCollector(client=client, max_retries=retries, backoff_factor=0).collect(source())
    assert error.value.status_code == status
    assert calls == retries + 1


@pytest.mark.asyncio
async def test_dns_retry_and_source_isolation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("bad"):
            return httpx.Response(200, content=b"invalid", request=request)
        raise httpx.ConnectError("dns", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = RSSCollector(client=client, max_retries=1, backoff_factor=0)
        with pytest.raises(CollectorHTTPError):
            await collector.collect(source("https://feed.test/dns"))
        bad = source("https://feed.test/bad")
        good = source("https://feed.test/good")
        result = await collector.collect_many([bad, good])
    assert isinstance(result[str(bad.id)], InvalidFeedError)
    assert isinstance(result[str(good.id)], CollectorHTTPError)

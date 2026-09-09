from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from app.collectors.rss import RSSCollector

ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom article</title>
<link href="https://example.test/atom/1"/><updated>2024-02-03T04:05:06+08:00</updated>
<summary>Atom summary</summary></entry></feed>"""


@pytest.mark.asyncio
async def test_three_mock_sources_and_atom_feed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=ATOM.encode(), request=request)

    sources = [
        SimpleNamespace(
            id=uuid4(),
            url=f"https://feed.test/source-{number}",
            enabled=True,
            language="en",
            category="technology",
        )
        for number in range(1, 4)
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await RSSCollector(client=client, backoff_factor=0).collect_many(sources)
    assert all(len(items) == 1 for items in results.values())
    assert all(items[0].title == "Atom article" for items in results.values())

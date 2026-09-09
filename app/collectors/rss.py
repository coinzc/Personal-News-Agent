"""Asynchronous RSS collector."""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.collectors.base import BaseCollector, CollectedNews, CollectorHTTPError, InvalidFeedError

logger = logging.getLogger(__name__)


class RSSCollector(BaseCollector):
    def __init__(
        self,
        *,
        timeout: float = 15.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.timeout, self.max_retries, self.backoff_factor, self._client = timeout, max_retries, backoff_factor, client

    async def collect(self, source: Any) -> list[CollectedNews]:
        if not getattr(source, "enabled", True):
            return []
        source_url = str(source.url)
        payload = await self._fetch(source_url)
        feed = feedparser.parse(payload)
        if not feed.entries:
            raise InvalidFeedError(f"invalid or empty RSS feed: {source_url}")
        items: list[CollectedNews] = []
        for entry in feed.entries:
            title = html.unescape(str(entry.get("title", "")).strip())
            url = self.normalize_url(str(entry.get("link", "")))
            if not title or not url:
                continue
            items.append(
                CollectedNews(
                    title=title,
                    url=url,
                    author=entry.get("author"),
                    published_at=self._published_at(entry),
                    content=self.clean_html(self._raw_content(entry)),
                    language=getattr(source, "language", None) or "en",
                    category=getattr(source, "category", None) or "technology",
                    image_url=self._image_url(entry),
                    content_hash=hashlib.sha256(url.encode()).hexdigest(),
                )
            )
        return items

    async def _fetch(self, url: str) -> bytes:
        owns = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.get(url, timeout=self.timeout)
                    status = response.status_code
                    if 400 <= status < 500 and status != 429:
                        raise CollectorHTTPError(status, url)
                    if status >= 400:
                        if attempt >= self.max_retries:
                            raise CollectorHTTPError(status, url)
                    else:
                        response.raise_for_status()
                        return response.content
                except CollectorHTTPError:
                    raise
                except (httpx.TimeoutException, httpx.RequestError) as exc:
                    if attempt >= self.max_retries:
                        raise CollectorHTTPError(None, url) from exc
                    logger.warning("RSS fetch failed for %s: %s", url, exc)
                if attempt < self.max_retries:
                    await asyncio.sleep(self.backoff_factor * 2**attempt)
            raise CollectorHTTPError(None, url)
        finally:
            if owns:
                await client.aclose()

    @staticmethod
    def _raw_content(entry: Any) -> str:
        value = entry.get("content") or entry.get("summary") or entry.get("description") or ""
        if isinstance(value, list):
            value = value[0].get("value", "") if value else ""
        return str(value)

    @staticmethod
    def clean_html(value: str) -> str:
        soup = BeautifulSoup(value or "", "html.parser")
        for tag in soup(("script", "style", "noscript")):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
        return re.sub(r"\s+([,.;:!?])", r"\1", text)

    @staticmethod
    def normalize_url(value: str) -> str:
        parts = urlsplit(value.strip())
        scheme = parts.scheme.lower()
        if scheme not in {"http", "https"} or not parts.hostname:
            return ""
        host, port = parts.hostname.lower(), parts.port
        is_default_port = not port or (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
        netloc = host if is_default_port else f"{host}:{port}"
        query = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
        ]
        path = parts.path or "/"
        return urlunsplit((scheme, netloc, path if path == "/" else path.rstrip("/"), urlencode(query), ""))

    @staticmethod
    def _published_at(entry: Any) -> datetime | None:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            return datetime(
                int(parsed[0]),
                int(parsed[1]),
                int(parsed[2]),
                int(parsed[3]),
                int(parsed[4]),
                int(parsed[5]),
                tzinfo=UTC,
            )
        raw = entry.get("published") or entry.get("updated")
        if raw:
            try:
                return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(UTC)
            except ValueError:
                return None
        return None

    @classmethod
    def _image_url(cls, entry: Any) -> str | None:
        for field in ("media_content", "media_thumbnail"):
            values = entry.get(field) or []
            if values and values[0].get("url"):
                return cls.normalize_url(str(values[0]["url"])) or str(values[0]["url"])
        for enclosure in entry.get("enclosures", []) or []:
            if str(enclosure.get("type", "")).startswith("image/") and enclosure.get("href"):
                return cls.normalize_url(str(enclosure["href"])) or str(enclosure["href"])
        return None

    async def to_news_item(self, source: Any, item: CollectedNews) -> Any:
        from app.models.news import NewsItem

        return NewsItem(
            title=item.title,
            url=item.url,
            source_id=getattr(source, "id", None),
            author=item.author,
            published_at=item.published_at,
            content=item.content,
            summary=None,
            language=item.language,
            category=item.category,
            tags=item.tags,
            image_url=item.image_url,
            content_hash=item.content_hash,
        )

"""Pluggable news collectors."""

from app.collectors.base import (
    BaseCollector,
    CollectedNews,
    CollectorError,
    CollectorHTTPError,
    InvalidFeedError,
)
from app.collectors.rss import RSSCollector

__all__ = [
    "BaseCollector",
    "CollectedNews",
    "CollectorError",
    "CollectorHTTPError",
    "InvalidFeedError",
    "RSSCollector",
]

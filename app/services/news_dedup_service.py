"""Multi-stage news duplicate detection.

The service deliberately does not delete articles.  It only compares article
identity/title signals so that :class:`NewsClusteringService` can retain every
source as a member of one ``NewsEvent``.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from typing import Literal, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.config import get_settings
from app.models.news import NewsItem

logger = logging.getLogger(__name__)

DeduplicationStage = Literal["url_hash", "normalized_title", "title_similarity", "embedding"]


# These aliases are intentionally small and explainable.  They make the
# lexical strategy useful for mixed Chinese/English headlines without
# pretending that lexical similarity is a replacement for a real embedding
# model.  The mapping is configurable through ``DeduplicationConfig``.
DEFAULT_TITLE_ALIASES: dict[str, str] = {
    "发布了": "announce",
    "推出了": "announce",
    "宣布了": "announce",
    "公布了": "announce",
    "发布": "announce",
    "推出": "announce",
    "宣布": "announce",
    "公布": "announce",
    "亮相": "announce",
    "announcing": "announce",
    "announced": "announce",
    "announces": "announce",
    "announce": "announce",
    "unveiling": "announce",
    "unveiled": "announce",
    "unveils": "announce",
    "unveil": "announce",
    "introducing": "announce",
    "introduced": "announce",
    "introduces": "announce",
    "introduce": "announce",
    "revealed": "announce",
    "reveals": "announce",
    "reveal": "announce",
    "launching": "announce",
    "launched": "announce",
    "launches": "announce",
    "launch": "announce",
    "released": "announce",
    "releases": "announce",
    "release": "announce",
    "最新": "new",
    "新": "new",
    "newest": "new",
    "latest": "new",
    "模型": "model",
    "model": "model",
    "人工智能": "ai",
    "ai": "ai",
}

DEFAULT_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "this",
        "to",
        "with",
        "了",
        "的",
        "和",
        "与",
    }
)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_NON_WORD_RE = re.compile(r"[^\w\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+", re.UNICODE)


class EmbeddingSimilarityProvider(Protocol):
    """Async extension point for a future embedding service."""

    async def similarity(self, left: str, right: str) -> float | None:
        """Return a 0..1 similarity, or ``None`` when unavailable."""


class NullEmbeddingProvider:
    """Default provider used until an embedding API is configured."""

    async def similarity(self, left: str, right: str) -> float | None:
        del left, right
        return None


class MockEmbeddingProvider:
    """Small deterministic provider useful in unit tests and local demos."""

    def __init__(self, scores: Mapping[tuple[str, str], float] | None = None, default: float | None = None) -> None:
        self.scores = dict(scores or {})
        self.default = default

    async def similarity(self, left: str, right: str) -> float | None:
        return self.scores.get((left, right), self.scores.get((right, left), self.default))


@dataclass(slots=True)
class DeduplicationConfig:
    """Tunable duplicate detection parameters.

    ``0.78`` is intentionally conservative for the lexical score used here:
    exact normalized titles are handled before this threshold, while a title
    must share most of its meaningful tokens to pass the fuzzy stage.
    """

    similarity_threshold: float = 0.78
    embedding_threshold: float = 0.85
    aliases: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_TITLE_ALIASES))
    stopwords: frozenset[str] = DEFAULT_STOPWORDS

    def __post_init__(self) -> None:
        for name in ("similarity_threshold", "embedding_threshold"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class TitleMatch:
    """Evidence that two titles describe the same event."""

    stage: DeduplicationStage
    score: float


@dataclass(frozen=True, slots=True)
class DeduplicationMatch:
    """A matched candidate article and the strongest matching evidence."""

    candidate: NewsItem
    stage: DeduplicationStage
    score: float


def normalize_url(value: str) -> str:
    """Canonicalize a URL for identity hashing.

    This mirrors the collector's safety behavior but lives here as a pure
    utility so deduplication does not depend on a particular collector.
    """

    parts = urlsplit(value.strip())
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.hostname:
        return value.strip()
    host = parts.hostname.lower()
    port = parts.port
    default_port = not port or (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if default_port else f"{host}:{port}"
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def url_hash(url: str) -> str:
    """Return a stable SHA-256 identity hash for a normalized article URL."""

    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def _replace_aliases(value: str, aliases: Mapping[str, str]) -> str:
    # Longest-first prevents ``发布`` from consuming ``发布了`` before the
    # more specific mapping can be applied.  ASCII aliases use word boundaries
    # so e.g. ``release`` does not alter ``releasedness``.
    result = value
    for source, target in sorted(aliases.items(), key=lambda pair: len(pair[0]), reverse=True):
        if not source:
            continue
        escaped = re.escape(source)
        if all(ord(character) < 128 for character in source):
            pattern = rf"(?<!\w){escaped}(?!\w)"
        else:
            pattern = escaped
        result = re.sub(pattern, f" {target} ", result, flags=re.IGNORECASE)
    return result


def title_tokens(
    title: str,
    *,
    aliases: Mapping[str, str] = DEFAULT_TITLE_ALIASES,
    stopwords: frozenset[str] = DEFAULT_STOPWORDS,
) -> tuple[str, ...]:
    """Create comparable multilingual lexical tokens from a headline."""

    value = html.unescape(unicodedata.normalize("NFKC", title)).casefold().strip()
    value = _replace_aliases(value, aliases)
    value = _NON_WORD_RE.sub(" ", value)
    tokens: list[str] = []
    for chunk in value.split():
        if _CJK_RE.search(chunk):
            # Character tokens provide a safe fallback for Chinese/Japanese
            # headlines not covered by the small configurable alias dictionary.
            tokens.extend(character for character in chunk if _CJK_RE.fullmatch(character))
            tokens.extend(part for part in re.findall(r"[a-z0-9]+", chunk) if part)
        else:
            tokens.append(chunk)
    return tuple(token for token in tokens if token not in stopwords)


def normalize_title(
    title: str,
    *,
    aliases: Mapping[str, str] = DEFAULT_TITLE_ALIASES,
    stopwords: frozenset[str] = DEFAULT_STOPWORDS,
) -> str:
    """Return the normalized title key used by the exact-text stage."""

    return " ".join(title_tokens(title, aliases=aliases, stopwords=stopwords))


def lexical_title_similarity(
    left: str,
    right: str,
    *,
    aliases: Mapping[str, str] = DEFAULT_TITLE_ALIASES,
    stopwords: frozenset[str] = DEFAULT_STOPWORDS,
) -> float:
    """Calculate a deterministic 0..1 score from normalized title tokens.

    The score combines token Jaccard overlap, token sequence similarity and
    overlap containment.  Combining all three avoids accepting a title merely
    because it shares one entity while tolerating punctuation, word order and
    minor wording changes.
    """

    left_tokens = title_tokens(left, aliases=aliases, stopwords=stopwords)
    right_tokens = title_tokens(right, aliases=aliases, stopwords=stopwords)
    if not left_tokens or not right_tokens:
        return 0.0
    if left_tokens == right_tokens:
        return 1.0
    left_set, right_set = set(left_tokens), set(right_tokens)
    union = left_set | right_set
    intersection = left_set & right_set
    jaccard = len(intersection) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, left_tokens, right_tokens).ratio()
    containment = len(intersection) / min(len(left_set), len(right_set)) if intersection else 0.0
    return (0.60 * jaccard) + (0.25 * sequence) + (0.15 * containment)


class NewsDedupService:
    """Apply URL, normalized-title, fuzzy-title and optional embedding checks."""

    def __init__(
        self,
        *,
        config: DeduplicationConfig | None = None,
        similarity_threshold: float | None = None,
        embedding_threshold: float | None = None,
        embedding_provider: EmbeddingSimilarityProvider | None = None,
    ) -> None:
        if config is None:
            settings = get_settings()
            selected = DeduplicationConfig(
                similarity_threshold=settings.dedup_similarity_threshold,
                embedding_threshold=settings.dedup_embedding_threshold,
            )
        else:
            selected = config
        if similarity_threshold is not None or embedding_threshold is not None:
            self.config = replace(
                selected,
                similarity_threshold=(
                    similarity_threshold if similarity_threshold is not None else selected.similarity_threshold
                ),
                embedding_threshold=(
                    embedding_threshold if embedding_threshold is not None else selected.embedding_threshold
                ),
            )
        else:
            self.config = selected
        self.embedding_provider = embedding_provider

    @staticmethod
    def url_hash(url: str) -> str:
        return url_hash(url)

    def title_tokens(self, title: str) -> tuple[str, ...]:
        return title_tokens(title, aliases=self.config.aliases, stopwords=self.config.stopwords)

    def normalize_title(self, title: str) -> str:
        return normalize_title(title, aliases=self.config.aliases, stopwords=self.config.stopwords)

    def title_similarity(self, left: str, right: str) -> float:
        return lexical_title_similarity(
            left,
            right,
            aliases=self.config.aliases,
            stopwords=self.config.stopwords,
        )

    async def compare_titles(self, left: str, right: str) -> TitleMatch | None:
        """Return the first passing lexical/embedding match, if any."""

        left_key = self.normalize_title(left)
        right_key = self.normalize_title(right)
        if left_key and left_key == right_key:
            return TitleMatch("normalized_title", 1.0)

        lexical_score = self.title_similarity(left, right)
        if lexical_score >= self.config.similarity_threshold:
            return TitleMatch("title_similarity", lexical_score)

        if self.embedding_provider is not None:
            try:
                embedding_score = await self.embedding_provider.similarity(left, right)
            except Exception:  # pragma: no cover - defensive boundary for external providers
                logger.exception("Embedding similarity provider failed")
            else:
                if embedding_score is not None:
                    bounded_score = max(0.0, min(1.0, float(embedding_score)))
                    if bounded_score >= self.config.embedding_threshold:
                        return TitleMatch("embedding", bounded_score)
        return None

    async def find_duplicate(
        self,
        item: NewsItem,
        candidates: Sequence[NewsItem],
    ) -> DeduplicationMatch | None:
        """Find the strongest duplicate candidate without deleting either row."""

        item_id = getattr(item, "id", None)
        item_url_key = self.url_hash(item.url)
        for candidate in candidates:
            if item_id is not None and item_id == getattr(candidate, "id", None):
                continue
            if item_url_key == self.url_hash(candidate.url):
                return DeduplicationMatch(candidate, "url_hash", 1.0)

        item_key = self.normalize_title(item.title)
        if item_key:
            for candidate in candidates:
                if item_id is not None and item_id == getattr(candidate, "id", None):
                    continue
                if item_key == self.normalize_title(candidate.title):
                    return DeduplicationMatch(candidate, "normalized_title", 1.0)

        best: DeduplicationMatch | None = None
        for candidate in candidates:
            if item_id is not None and item_id == getattr(candidate, "id", None):
                continue
            match = await self.compare_titles(item.title, candidate.title)
            if match is None:
                continue
            if best is None or match.score > best.score:
                best = DeduplicationMatch(candidate, match.stage, match.score)
        return best

    async def deduplicate(self, items: Iterable[NewsItem]) -> list[list[NewsItem]]:
        """Group a batch into duplicate clusters while retaining every item."""

        clusters: list[list[NewsItem]] = []
        for item in items:
            candidates = [candidate for cluster in clusters for candidate in cluster]
            match = await self.find_duplicate(item, candidates)
            if match is None:
                clusters.append([item])
                continue
            for cluster in clusters:
                if any(candidate is match.candidate or candidate.id == match.candidate.id for candidate in cluster):
                    cluster.append(item)
                    break
        return clusters


__all__ = [
    "DEFAULT_STOPWORDS",
    "DEFAULT_TITLE_ALIASES",
    "DeduplicationConfig",
    "DeduplicationMatch",
    "DeduplicationStage",
    "EmbeddingSimilarityProvider",
    "MockEmbeddingProvider",
    "NewsDedupService",
    "NullEmbeddingProvider",
    "TitleMatch",
    "lexical_title_similarity",
    "normalize_title",
    "normalize_url",
    "title_tokens",
    "url_hash",
]

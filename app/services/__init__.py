"""Application services."""

from app.services.news_clustering_service import NewsClusteringService
from app.services.news_dedup_service import (
    DeduplicationConfig,
    DeduplicationMatch,
    EmbeddingSimilarityProvider,
    MockEmbeddingProvider,
    NewsDedupService,
    NullEmbeddingProvider,
    TitleMatch,
)

__all__ = [
    "DeduplicationConfig",
    "DeduplicationMatch",
    "EmbeddingSimilarityProvider",
    "MockEmbeddingProvider",
    "NewsClusteringService",
    "NewsDedupService",
    "NullEmbeddingProvider",
    "TitleMatch",
]

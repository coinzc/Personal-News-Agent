"""Application services."""

from app.services.digest_service import (
    DEFAULT_CATEGORIES,
    DailyDigestService,
    DigestAlreadyRunning,
    DigestGenerationError,
)
from app.services.news_clustering_service import NewsClusteringService
from app.services.news_collection_service import NewsCollectionService
from app.services.news_dedup_service import (
    DeduplicationConfig,
    DeduplicationMatch,
    EmbeddingSimilarityProvider,
    MockEmbeddingProvider,
    NewsDedupService,
    NullEmbeddingProvider,
    TitleMatch,
)
from app.services.news_llm_service import NewsClassifier, NewsRanker, NewsSummarizer
from app.services.news_query_service import SQLAlchemyNewsToolService

__all__ = [
    "DEFAULT_CATEGORIES",
    "DailyDigestService",
    "DigestAlreadyRunning",
    "DigestGenerationError",
    "DeduplicationConfig",
    "DeduplicationMatch",
    "EmbeddingSimilarityProvider",
    "MockEmbeddingProvider",
    "NewsClusteringService",
    "NewsCollectionService",
    "NewsClassifier",
    "NewsDedupService",
    "NewsRanker",
    "NewsSummarizer",
    "SQLAlchemyNewsToolService",
    "NullEmbeddingProvider",
    "TitleMatch",
]

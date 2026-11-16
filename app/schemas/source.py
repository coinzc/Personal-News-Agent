from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NewsSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2_000)
    source_type: str = Field(default="rss", min_length=1, max_length=32)
    category: str = Field(min_length=1, max_length=64)
    language: str = Field(default="en", min_length=2, max_length=16)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    enabled: bool = True
    priority: int = Field(default=0, ge=0, le=10_000)
    config: dict[str, object] = Field(default_factory=dict)


class NewsSourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: str | None = Field(default=None, min_length=1, max_length=2_000)
    source_type: str | None = Field(default=None, min_length=1, max_length=32)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    language: str | None = Field(default=None, min_length=2, max_length=16)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10_000)
    config: dict[str, object] | None = None


class NewsSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    url: str
    source_type: str
    category: str
    language: str
    country: str | None
    enabled: bool
    priority: int
    last_collected_at: datetime | None

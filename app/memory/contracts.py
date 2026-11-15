"""Validated public and agent contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MemoryType(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    PREFERENCE = "preference"
    PROJECT = "project"


class Source(Contract):
    source_id: str = Field(min_length=1, max_length=200)
    source_type: str = Field(default="manual", max_length=50)
    quote: str = Field(min_length=1, max_length=50000)
    chunk_id: str | None = None
    document_id: str | None = None
    page: int | None = Field(default=None, ge=1)


class EntityInput(Contract):
    name: str = Field(min_length=1, max_length=200)
    entity_type: Literal[
        "person",
        "organization",
        "project",
        "location",
        "event",
        "technology",
        "concept",
        "document",
        "task",
        "skill",
    ]


class RelationInput(Contract):
    subject: str = Field(min_length=1, max_length=200)
    predicate: Literal[
        "WORKS_ON",
        "CREATED",
        "PARTICIPATED_IN",
        "STUDIED",
        "USES",
        "RELATED_TO",
        "OCCURRED_AT",
        "BELONGS_TO",
        "DEPENDS_ON",
        "MENTIONED_IN",
        "SUPERSEDES",
    ]
    object: str = Field(min_length=1, max_length=200)
    confidence: float = Field(default=0.5, ge=0, le=1)


class MemoryInput(Contract):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=50000)
    memory_type: MemoryType = MemoryType.SEMANTIC
    summary: str = Field(default="", max_length=5000)
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=0.5, ge=0, le=1)
    relevance: float = Field(default=0.5, ge=0, le=1)
    tags: list[str] = Field(default_factory=list, max_length=50)
    sources: list[Source] = Field(min_length=1, max_length=100)
    subject: str = Field(default="", max_length=200)
    predicate: str = Field(default="", max_length=200)
    object: str = Field(default="", max_length=2000)
    inferred: bool = False
    sensitivity: Literal["public", "personal", "sensitive"] = "personal"
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    expiration_policy: Literal["retain", "archive"] = "retain"
    entities: list[EntityInput] = Field(default_factory=list, max_length=100)
    relationships: list[RelationInput] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def temporal_bounds(self) -> Any:
        for value in (self.valid_from, self.valid_until):
            if value and value.tzinfo is None:
                raise ValueError("Validity timestamps require a timezone")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must follow valid_from")
        return self


class Extraction(Contract):
    candidates: list[MemoryInput] = Field(default_factory=list, max_length=100)


class Classification(Contract):
    memory_type: MemoryType
    tags: list[str] = Field(default_factory=list, max_length=50)
    importance: float = Field(ge=0, le=1)


class MemoryPatch(Contract):
    expected_version: int = Field(ge=1)
    memory: MemoryInput


class SearchRequest(Contract):
    query: str = Field(min_length=1, max_length=4000)
    mode: Literal["hybrid", "keyword", "semantic"] = "hybrid"
    top_k: int = Field(default=10, ge=1, le=100)
    memory_type: MemoryType | None = None
    tags: list[str] = Field(default_factory=list)
    source_id: str | None = None
    after: datetime | None = None
    before: datetime | None = None
    minimum_similarity: float = Field(default=0, ge=-1, le=1)
    context_tokens: int = Field(default=2000, ge=64, le=16000)
    allow_keyword_fallback: bool = True


class IngestionRequest(Contract):
    content: str = Field(min_length=1, max_length=200000)
    source_type: Literal["text", "conversation"] = "text"
    background: bool = True


class ConsolidationRequest(Contract):
    dry_run: bool = True
    limit: int = Field(default=500, ge=1, le=5000)


class ReviewRequest(Contract):
    action: Literal["keep_both", "supersede", "reject", "higher_confidence"]


class KeyRequest(Contract):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[Literal["read", "write", "execute", "admin"]] = Field(min_length=1)


class OperationalSettings(Contract):
    conflict_policy: Literal["review", "keep_both", "supersede", "higher_confidence"] = "review"
    minimum_confidence: float = Field(default=0.3, ge=0, le=1)
    consolidation_interval_hours: int = Field(default=0, ge=0, le=8760)
    retention_days: int = Field(default=0, ge=0, le=36500)
    rrf_k: int = Field(default=60, ge=1, le=1000)

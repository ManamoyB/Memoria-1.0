"""Standardized MemoriaOS Document Reader output schemas (Pydantic v2)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import BlockType, DocumentFormat, ExtractionStatus, OcrStatus


class DocumentSource(BaseModel):
    """Provenance metadata describing the ingested raw document artifact."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(..., description="Sanitized original filename.")
    extension: str = Field(..., description="Normalized lowercase extension with dot.")
    format: DocumentFormat
    mime_type: str = Field(..., description="Resolved MIME type of the input file.")
    byte_size: int = Field(..., ge=0)
    content_hash: str = Field(
        ..., description="SHA-256 hex digest of raw bytes prefixed with 'sha256:'."
    )
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class DocumentBlock(BaseModel):
    """Atomic structural unit extracted from a document in reading order."""

    model_config = ConfigDict(extra="forbid")

    block_id: str = Field(..., description="Deterministic block identifier.")
    type: BlockType
    text: str = Field(..., description="Normalized UTF-8 NFC text content.")
    order_index: int = Field(..., ge=0)
    level: int | None = Field(
        default=None,
        ge=1,
        le=6,
        description="Heading level (1-6) or list nesting depth when applicable.",
    )
    page_number: int | None = Field(
        default=None,
        ge=1,
        description="1-based page number for paginated documents such as PDF.",
    )
    parent_section_id: str | None = Field(
        default=None,
        description="Identifier of the enclosing SectionNode for hierarchical RAG chunking.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extractor-specific structural hints (e.g., code language, style, list marker).",
    )


class SectionNode(BaseModel):
    """Hierarchical section node derived from document headings."""

    model_config = ConfigDict(extra="forbid")

    section_id: str
    title: str
    level: int = Field(..., ge=1, le=6)
    order_index: int = Field(..., ge=0)
    page_number: int | None = Field(default=None, ge=1)
    block_ids: list[str] = Field(default_factory=list)
    children: list[SectionNode] = Field(default_factory=list)


class PageReference(BaseModel):
    """Per-page extraction telemetry and OCR readiness reference for paginated documents."""

    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(..., ge=1)
    char_count: int = Field(default=0, ge=0)
    word_count: int = Field(default=0, ge=0)
    block_count: int = Field(default=0, ge=0)
    is_empty: bool = Field(default=False)
    potentially_scanned: bool = Field(default=False)
    has_images: bool = Field(default=False)
    ocr_applied: bool = Field(default=False)


class TableData(BaseModel):
    """Normalized tabular payload extracted from CSV, DOCX, Markdown, or PDF."""

    model_config = ConfigDict(extra="forbid")

    table_id: str
    name: str | None = Field(default=None)
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    records: list[dict[str, str]] = Field(default_factory=list)
    column_types: dict[str, str] = Field(default_factory=dict)
    row_count: int = Field(..., ge=0)
    total_row_count: int | None = Field(default=None, ge=0)
    column_count: int = Field(..., ge=0)
    truncated: bool = Field(default=False)
    page_number: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkingConfig(BaseModel):
    """Configurable parameters controlling paragraph-aware document chunking."""

    model_config = ConfigDict(extra="forbid")

    chunk_size: int = Field(default=3000, ge=100, le=50000)
    chunk_overlap: int = Field(default=300, ge=0, le=10000)
    preserve_paragraphs: bool = Field(default=True)

    @model_validator(mode="after")
    def validate_overlap(self) -> ChunkingConfig:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be strictly smaller than chunk_size.")
        return self


class DocumentChunk(BaseModel):
    """Deterministic text chunk prepared for downstream RAG & Qdrant embedding agents."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    document_id: str
    chunk_index: int = Field(..., ge=0)
    text: str = Field(..., min_length=1)
    char_count: int = Field(..., ge=1)
    word_count: int = Field(..., ge=0)
    start_char: int = Field(..., ge=0)
    end_char: int = Field(..., ge=0)
    page_numbers: list[int] = Field(default_factory=list)
    block_ids: list[str] = Field(default_factory=list)
    section_id: str | None = Field(default=None)
    section_title: str | None = Field(default=None)


class DocumentMetadata(BaseModel):
    """Normalized descriptive and structural statistics for a document."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None)
    author: str | None = Field(default=None)
    created_at: str | None = Field(default=None)
    modified_at: str | None = Field(default=None)
    page_count: int | None = Field(default=None, ge=1)
    block_count: int = Field(default=0, ge=0)
    section_count: int = Field(default=0, ge=0)
    table_count: int = Field(default=0, ge=0)
    chunk_count: int = Field(default=0, ge=0)
    word_count: int = Field(default=0, ge=0)
    char_count: int = Field(default=0, ge=0)
    line_count: int = Field(default=0, ge=0)
    encoding: str | None = Field(default=None)
    extractor_name: str
    custom_properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Format-native properties (e.g., Markdown frontmatter, CSV delimiter, DOCX styles).",
    )


class OcrMetadata(BaseModel):
    """OCR diagnostics and readiness signals for scanned or image-heavy documents."""

    model_config = ConfigDict(extra="forbid")

    status: OcrStatus = Field(default=OcrStatus.NOT_NEEDED)
    ocr_enabled: bool = Field(default=False)
    ocr_applied: bool = Field(default=False)
    ocr_engine: str | None = Field(default=None)
    pages_requiring_ocr: list[int] = Field(
        default_factory=list,
        description="1-based page numbers flagged with low extractable text density.",
    )
    empty_pages: list[int] = Field(
        default_factory=list,
        description="1-based page numbers containing zero selectable characters.",
    )
    notes: list[str] = Field(default_factory=list)


class ProcessingStatistics(BaseModel):
    """Deterministic processing metrics captured across extraction, normalization, and chunking."""

    model_config = ConfigDict(extra="forbid")

    extraction_time_ms: float = Field(default=0.0, ge=0.0)
    normalization_time_ms: float = Field(default=0.0, ge=0.0)
    chunking_time_ms: float = Field(default=0.0, ge=0.0)
    total_time_ms: float = Field(default=0.0, ge=0.0)
    char_count: int = Field(default=0, ge=0)
    word_count: int = Field(default=0, ge=0)
    line_count: int = Field(default=0, ge=0)
    block_count: int = Field(default=0, ge=0)
    section_count: int = Field(default=0, ge=0)
    table_count: int = Field(default=0, ge=0)
    chunk_count: int = Field(default=0, ge=0)
    page_count: int | None = Field(default=None, ge=1)
    empty_page_count: int = Field(default=0, ge=0)
    scanned_page_count: int = Field(default=0, ge=0)
    records_extracted: int | None = Field(default=None, ge=0)
    truncated: bool = Field(default=False)


class NormalizedDocument(BaseModel):
    """Standardized MemoriaOS Document Reader output contract.

    Designed for direct consumption by downstream MemoriaOS agents (LangGraph
    orchestrators, Qdrant vector indexing, knowledge graph extraction, and
    Obsidian formatting).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0")
    agent: str = Field(default="memoria-document-reader")
    document_id: str = Field(
        ...,
        description="Deterministic UUID derived from content hash for idempotent ingestion.",
    )
    filename: str = Field(..., description="Sanitized original filename.")
    document_type: DocumentFormat
    status: ExtractionStatus = Field(default=ExtractionStatus.SUCCESS)
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source: DocumentSource
    metadata: DocumentMetadata
    content: str = Field(
        ...,
        description="Canonical UTF-8 NFC full-document text assembled in reading order.",
    )
    blocks: list[DocumentBlock] = Field(default_factory=list)
    sections: list[SectionNode] = Field(default_factory=list)
    tables: list[TableData] = Field(default_factory=list)
    pages: list[PageReference] = Field(default_factory=list)
    chunks: list[DocumentChunk] = Field(default_factory=list)
    ocr: OcrMetadata = Field(default_factory=OcrMetadata)
    processing_statistics: ProcessingStatistics = Field(
        default_factory=ProcessingStatistics
    )
    extraction_warnings: list[str] = Field(default_factory=list)
    processing_time_ms: float = Field(..., ge=0.0)


class BatchExtractionItem(BaseModel):
    """Outcome wrapper for an individual file in a batch extraction request."""

    model_config = ConfigDict(extra="forbid")

    filename: str
    status: ExtractionStatus
    document: NormalizedDocument | None = None
    error_code: str | None = None
    error_message: str | None = None


class BatchExtractionResponse(BaseModel):
    """Response payload for multi-document batch extraction."""

    model_config = ConfigDict(extra="forbid")

    total_files: int = Field(..., ge=0)
    succeeded: int = Field(..., ge=0)
    failed: int = Field(..., ge=0)
    results: list[BatchExtractionItem] = Field(default_factory=list)

"""Shared enums and operational response schemas (health, formats, errors)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentFormat(StrEnum):
    """Canonical document formats supported by the Document Reader Agent."""

    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MARKDOWN = "markdown"
    CSV = "csv"


class BlockType(StrEnum):
    """Structural block types preserved during extraction and normalization."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    CODE_BLOCK = "code_block"
    QUOTE = "quote"
    TABLE = "table"
    PAGE_BREAK = "page_break"
    FRONTMATTER = "frontmatter"


class ExtractionStatus(StrEnum):
    """Execution outcome status for a document extraction request."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class OcrStatus(StrEnum):
    """State of OCR readiness/execution on the processed document."""

    NOT_NEEDED = "not_needed"
    DEFERRED_DISABLED = "deferred_disabled"
    APPLIED = "applied"
    UNAVAILABLE = "unavailable"


class ErrorResponse(BaseModel):
    """Standardized error envelope returned by centralized exception handlers."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="error")
    error_code: str = Field(..., description="Machine-readable error identifier.")
    message: str = Field(..., description="Human-readable error description.")
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = Field(default=None)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class HealthResponse(BaseModel):
    """Service liveness and capability status response."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="ok")
    agent: str = Field(default="memoria-document-reader")
    version: str
    environment: str
    ocr_enabled: bool
    ocr_engine: str
    supported_formats: list[DocumentFormat]
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ServiceInfoResponse(BaseModel):
    """Top-level service metadata and operational status response."""

    model_config = ConfigDict(extra="forbid")

    service: str = Field(default="MemoriaOS Document Reader Agent")
    agent: str = Field(default="memoria-document-reader")
    version: str
    environment: str
    status: str = Field(default="running")
    api_prefix: str
    docs_url: str = Field(default="/docs")
    supported_formats: list[DocumentFormat]
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class DocumentStatusResponse(BaseModel):
    """Processing status record for a previously ingested document ID."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    filename: str
    document_type: DocumentFormat
    status: ExtractionStatus
    chunk_count: int = Field(default=0, ge=0)
    block_count: int = Field(default=0, ge=0)
    processing_time_ms: float = Field(default=0.0, ge=0.0)
    warnings: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class FormatCapability(BaseModel):
    """Capability descriptor for a single registered document format."""

    model_config = ConfigDict(extra="forbid")

    format: DocumentFormat
    extensions: list[str]
    mime_types: list[str]
    extractor_name: str
    preserves_structure: bool = True
    supports_tables: bool = False
    ocr_fallback_ready: bool = False


class SupportedFormatsResponse(BaseModel):
    """Registry listing of supported formats and extractor capabilities."""

    model_config = ConfigDict(extra="forbid")

    formats: list[FormatCapability]

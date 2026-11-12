"""Base interfaces, shared file validation, and unified extraction DTOs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.exceptions import (
    DocumentNotFoundError,
    EmptyDocumentError,
    FileTooLargeError,
)
from app.schemas.common import BlockType, DocumentFormat, OcrStatus


@dataclass(slots=True)
class RawBlock:
    """Intermediate structural block produced by an extractor before normalization."""

    type: BlockType
    text: str
    level: int | None = None
    page_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RawTable:
    """Intermediate tabular structure extracted from a document."""

    headers: list[str]
    rows: list[list[str]]
    name: str | None = None
    page_number: int | None = None
    column_types: dict[str, str] = field(default_factory=dict)
    records: list[dict[str, str]] = field(default_factory=list)
    total_row_count: int | None = None
    truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RawPageReference:
    """Page-level extraction metrics and scan/empty diagnostics."""

    page_number: int
    char_count: int = 0
    word_count: int = 0
    block_count: int = 0
    is_empty: bool = False
    potentially_scanned: bool = False
    has_images: bool = False
    ocr_applied: bool = False


@dataclass(slots=True)
class RawOcrSignal:
    """OCR readiness and execution diagnostics returned by an extractor."""

    status: OcrStatus = OcrStatus.NOT_NEEDED
    ocr_enabled: bool = False
    ocr_applied: bool = False
    ocr_engine: str | None = None
    pages_requiring_ocr: list[int] = field(default_factory=list)
    empty_pages: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RawStatistics:
    """Processing statistics emitted by an extraction engine."""

    extraction_time_ms: float = 0.0
    char_count: int = 0
    word_count: int = 0
    line_count: int = 0
    block_count: int = 0
    table_count: int = 0
    page_count: int | None = None
    empty_page_count: int = 0
    scanned_page_count: int = 0
    records_extracted: int | None = None
    truncated: bool = False


@dataclass(slots=True)
class ExtractionContext:
    """Runtime options passed into extractors by the ProcessingController."""

    default_encoding: str = "utf-8"
    csv_max_rows: int = 10000
    max_file_size_bytes: int | None = None
    pdf_min_text_chars_per_page: int = 40
    ocr_enabled: bool = False
    ocr_engine_name: str = "tesseract"
    tesseract_lang: str = "eng"


@dataclass(slots=True)
class ExtractedContent:
    """Unified extractor-agnostic payload returned by every format extractor."""

    extractor_name: str
    format: DocumentFormat
    raw_text: str = ""
    blocks: list[RawBlock] = field(default_factory=list)
    tables: list[RawTable] = field(default_factory=list)
    pages: list[RawPageReference] = field(default_factory=list)
    title: str | None = None
    author: str | None = None
    created_at: str | None = None
    modified_at: str | None = None
    page_count: int | None = None
    encoding: str | None = None
    custom_properties: dict[str, Any] = field(default_factory=dict)
    ocr_signal: RawOcrSignal = field(default_factory=RawOcrSignal)
    statistics: RawStatistics = field(default_factory=RawStatistics)
    warnings: list[str] = field(default_factory=list)


class BaseExtractor(ABC):
    """Abstract contract implemented by every independent format extractor.

    Extractors must stay stateless, avoid importing other extractors, never invoke
    LLMs, and never perform summarization, classification, or downstream storage.
    """

    name: str
    supported_format: DocumentFormat
    supported_extensions: tuple[str, ...]
    supported_mime_types: tuple[str, ...]
    supports_tables: bool = False
    ocr_fallback_ready: bool = False

    @staticmethod
    def validate_file(file_path: Path, context: ExtractionContext) -> int:
        """Validate file existence, non-emptiness, and configured byte-size limits.

        Returns:
            File size in bytes.
        """
        if not file_path.exists() or not file_path.is_file():
            raise DocumentNotFoundError(
                f"Document file '{file_path.name}' was not found.",
                details={"filename": file_path.name},
            )

        byte_size = file_path.stat().st_size
        if byte_size == 0:
            raise EmptyDocumentError(
                f"Document '{file_path.name}' is empty (0 bytes).",
                details={"filename": file_path.name},
            )

        if (
            context.max_file_size_bytes is not None
            and byte_size > context.max_file_size_bytes
        ):
            raise FileTooLargeError(
                f"Document '{file_path.name}' ({byte_size} bytes) exceeds maximum limit "
                f"of {context.max_file_size_bytes} bytes.",
                details={
                    "filename": file_path.name,
                    "byte_size": byte_size,
                    "max_bytes": context.max_file_size_bytes,
                },
            )

        return byte_size

    @abstractmethod
    def extract(
        self,
        file_path: Path,
        context: ExtractionContext,
    ) -> ExtractedContent:
        """Extract raw structural blocks, tables, pages, metadata, and stats from ``file_path``."""

"""Extractor registry decoupling format resolution from concrete engines."""

from __future__ import annotations

from app.core.exceptions import UnsupportedFormatError
from app.extractors.base import BaseExtractor
from app.schemas.common import DocumentFormat, FormatCapability


class ExtractorRegistry:
    """Registry mapping canonical DocumentFormat values to independent extractors."""

    def __init__(self) -> None:
        self._extractors: dict[DocumentFormat, BaseExtractor] = {}

    def register(self, extractor: BaseExtractor) -> None:
        """Register an extractor for its declared ``supported_format``."""
        self._extractors[extractor.supported_format] = extractor

    def get(self, document_format: DocumentFormat) -> BaseExtractor:
        """Retrieve the extractor for ``document_format`` or raise UnsupportedFormatError."""
        extractor = self._extractors.get(document_format)
        if extractor is None:
            raise UnsupportedFormatError(
                f"No extractor registered for format '{document_format.value}'.",
                details={"format": document_format.value},
            )
        return extractor

    def list_formats(self) -> list[DocumentFormat]:
        """Return all registered DocumentFormat enum values."""
        return list(self._extractors.keys())

    def list_capabilities(self) -> list[FormatCapability]:
        """Return structured capability descriptors for API discovery endpoints."""
        return [
            FormatCapability(
                format=extractor.supported_format,
                extensions=list(extractor.supported_extensions),
                mime_types=list(extractor.supported_mime_types),
                extractor_name=extractor.name,
                preserves_structure=True,
                supports_tables=extractor.supports_tables,
                ocr_fallback_ready=extractor.ocr_fallback_ready,
            )
            for extractor in self._extractors.values()
        ]

"""Pure-Python domain exceptions for the MemoriaOS Document Reader Agent.

Kept intentionally free of FastAPI/Starlette imports so framework-independent
services, extractors, and LangGraph workers never depend on web transport.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any


class MemoriaReaderError(Exception):
    """Base domain exception for all MemoriaOS Document Reader failures."""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    error_code: str = "MEMORIA_READER_ERROR"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if status_code is not None:
            self.status_code = int(status_code)
        if error_code is not None:
            self.error_code = error_code


class UnsupportedFormatError(MemoriaReaderError):
    """Raised when the uploaded document format is unsupported or unregistered."""

    status_code = HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    error_code = "UNSUPPORTED_DOCUMENT_FORMAT"


class FileTooLargeError(MemoriaReaderError):
    """Raised when an uploaded document exceeds the configured maximum file size."""

    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    error_code = "FILE_TOO_LARGE"


class EmptyDocumentError(MemoriaReaderError):
    """Raised when an uploaded file has zero bytes or yields no extractable content."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    error_code = "EMPTY_DOCUMENT"


class CorruptedDocumentError(MemoriaReaderError):
    """Raised when an input document is malformed or cannot be opened by its extractor."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    error_code = "CORRUPTED_DOCUMENT"


class PasswordProtectedDocumentError(MemoriaReaderError):
    """Raised when a document (e.g., encrypted PDF) requires a password to read."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    error_code = "PASSWORD_PROTECTED_DOCUMENT"


class InvalidEncodingError(MemoriaReaderError):
    """Raised when text bytes cannot be safely decoded into a valid character encoding."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    error_code = "INVALID_ENCODING"


class DocumentNotFoundError(MemoriaReaderError):
    """Raised when a target document path does not exist or is not a regular file."""

    status_code = HTTPStatus.NOT_FOUND
    error_code = "DOCUMENT_FILE_NOT_FOUND"


class DocumentStatusNotFoundError(MemoriaReaderError):
    """Raised when no tracked processing status exists for a given document ID."""

    status_code = HTTPStatus.NOT_FOUND
    error_code = "DOCUMENT_STATUS_NOT_FOUND"


class RequestTimeoutError(MemoriaReaderError):
    """Raised when an API request exceeds the configured processing timeout."""

    status_code = HTTPStatus.REQUEST_TIMEOUT
    error_code = "REQUEST_TIMEOUT"


class ExtractionError(MemoriaReaderError):
    """Raised when an extraction engine encounters an unexpected processing failure."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    error_code = "EXTRACTION_FAILED"


class StorageError(MemoriaReaderError):
    """Raised when temporary upload persistence or cleanup fails."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    error_code = "STORAGE_ERROR"


class OcrNotConfiguredError(MemoriaReaderError):
    """Raised when OCR fallback is explicitly requested without an active OCR engine."""

    status_code = HTTPStatus.NOT_IMPLEMENTED
    error_code = "OCR_NOT_CONFIGURED"


class ObsidianPersistenceError(MemoriaReaderError):
    """Raised when persisting a normalized document to an Obsidian vault fails."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    error_code = "OBSIDIAN_PERSISTENCE_ERROR"


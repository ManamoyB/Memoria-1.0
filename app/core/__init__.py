"""Core infrastructure: configuration, structured logging, and centralized exceptions."""

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    CorruptedDocumentError,
    DocumentNotFoundError,
    DocumentStatusNotFoundError,
    EmptyDocumentError,
    ExtractionError,
    FileTooLargeError,
    InvalidEncodingError,
    MemoriaReaderError,
    ObsidianPersistenceError,
    OcrNotConfiguredError,
    PasswordProtectedDocumentError,
    RequestTimeoutError,
    StorageError,
    UnsupportedFormatError,
)
from app.core.logging import configure_logging, get_logger

__all__ = [
    "Settings",
    "get_settings",
    "MemoriaReaderError",
    "UnsupportedFormatError",
    "FileTooLargeError",
    "EmptyDocumentError",
    "CorruptedDocumentError",
    "PasswordProtectedDocumentError",
    "InvalidEncodingError",
    "DocumentNotFoundError",
    "DocumentStatusNotFoundError",
    "RequestTimeoutError",
    "ExtractionError",
    "StorageError",
    "OcrNotConfiguredError",
    "ObsidianPersistenceError",
    "configure_logging",
    "get_logger",
]

"""File validation guardrails: size limits, allowed types, MIME checks, and path traversal safety."""

from __future__ import annotations

from pathlib import Path

from app.core.exceptions import (
    DocumentNotFoundError,
    EmptyDocumentError,
    FileTooLargeError,
    StorageError,
    UnsupportedFormatError,
)
from app.schemas.common import DocumentFormat
from app.services.file_detector import DetectedFileType, FileDetector
from app.utils.file_utils import MIME_TO_FORMAT, sanitize_filename

_GENERIC_MIMES = {"", "application/octet-stream", "binary/octet-stream"}


class FileValidator:
    """Enforces upload/file security and format guardrails before extraction."""

    def __init__(
        self,
        *,
        max_file_size_bytes: int,
        allowed_formats: set[DocumentFormat] | None = None,
        detector: FileDetector | None = None,
    ) -> None:
        self._max_file_size_bytes = max_file_size_bytes
        self._allowed_formats = allowed_formats or set(DocumentFormat)
        self._detector = detector or FileDetector()

    @property
    def max_file_size_bytes(self) -> int:
        return self._max_file_size_bytes

    def validate_incoming_metadata(
        self,
        *,
        filename: str | None,
        content_type: str | None = None,
    ) -> tuple[str, DocumentFormat, str, str]:
        """Validate filename safety, allowed format, and declared MIME compatibility."""
        if filename and ("\x00" in filename):
            raise StorageError("Filename contains illegal null byte.")

        safe_name = sanitize_filename(filename)
        fmt, ext, resolved_mime = self._detector.detect_from_metadata(
            safe_name, content_type=content_type
        )

        if fmt not in self._allowed_formats:
            raise UnsupportedFormatError(
                f"Format '{fmt.value}' is disabled by configuration.",
                details={
                    "format": fmt.value,
                    "allowed_formats": sorted(f.value for f in self._allowed_formats),
                },
            )

        declared_mime = (content_type or "").split(";")[0].strip().lower()
        if declared_mime and declared_mime not in _GENERIC_MIMES:
            mime_format = MIME_TO_FORMAT.get(declared_mime)
            if mime_format is not None and mime_format != fmt:
                raise UnsupportedFormatError(
                    f"Declared MIME type '{declared_mime}' does not match file extension '{ext}'.",
                    details={
                        "filename": safe_name,
                        "declared_mime": declared_mime,
                        "extension_format": fmt.value,
                    },
                )

        return safe_name, fmt, ext, resolved_mime

    def validate_safe_destination(self, base_dir: Path, target_path: Path) -> Path:
        """Ensure resolved target path remains strictly inside ``base_dir``."""
        resolved_base = base_dir.resolve()
        resolved_target = target_path.resolve()
        if resolved_base != resolved_target and resolved_base not in resolved_target.parents:
            raise StorageError(
                "Path traversal attempt blocked: target path escapes allowed directory."
            )
        return resolved_target

    def validate_size(self, byte_size: int, filename: str) -> None:
        """Enforce non-empty and maximum byte-size limits."""
        if byte_size <= 0:
            raise EmptyDocumentError(
                f"Document '{filename}' is empty (0 bytes).",
                details={"filename": filename},
            )
        if byte_size > self._max_file_size_bytes:
            raise FileTooLargeError(
                f"Document '{filename}' ({byte_size} bytes) exceeds maximum limit of "
                f"{self._max_file_size_bytes} bytes.",
                details={
                    "filename": filename,
                    "byte_size": byte_size,
                    "max_bytes": self._max_file_size_bytes,
                },
            )

    def validate_local_file(
        self,
        file_path: Path,
        *,
        declared_filename: str | None = None,
        content_type: str | None = None,
        allowed_root: Path | None = None,
    ) -> DetectedFileType:
        """Validate an existing file on disk (existence, size, MIME, and magic bytes)."""
        if allowed_root is not None:
            self.validate_safe_destination(allowed_root, file_path)

        if not file_path.exists() or not file_path.is_file():
            raise DocumentNotFoundError(
                f"Document file '{file_path.name}' does not exist.",
                details={"filename": file_path.name},
            )

        safe_name, fmt, ext, mime = self.validate_incoming_metadata(
            filename=declared_filename or file_path.name,
            content_type=content_type,
        )
        byte_size = file_path.stat().st_size
        self.validate_size(byte_size, safe_name)

        self._detector.verify_file_signature(file_path, fmt)
        return DetectedFileType(
            format=fmt,
            extension=ext,
            mime_type=mime,
            signature_verified=True,
        )

"""File format detector combining extension, MIME hints, and magic-byte signatures."""

from __future__ import annotations

import codecs
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import CorruptedDocumentError, UnsupportedFormatError
from app.schemas.common import DocumentFormat
from app.utils.file_utils import detect_document_format

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_BINARY_EXCLUSION_MAGICS = (
    b"\x7fELF",       # Linux ELF
    b"MZ",            # Windows PE/EXE
    b"\x89PNG\r\n",   # PNG image
    b"\xff\xd8\xff",  # JPEG image
    b"GIF87a",        # GIF image
    b"GIF89a",        # GIF image
    b"\x1f\x8b",      # GZIP
    b"Rar!",          # RAR
)


@dataclass(slots=True)
class DetectedFileType:
    """Resolved document format and signature verification details."""

    format: DocumentFormat
    extension: str
    mime_type: str
    signature_verified: bool


class FileDetector:
    """Identifies document formats using both filename extensions and file signatures."""

    def detect_from_metadata(
        self,
        filename: str,
        content_type: str | None = None,
    ) -> tuple[DocumentFormat, str, str]:
        """Resolve candidate DocumentFormat, normalized extension, and MIME type."""
        return detect_document_format(filename, content_type=content_type)

    def verify_file_signature(
        self,
        file_path: Path,
        expected_format: DocumentFormat,
    ) -> bool:
        """Verify that on-disk file magic bytes/content match ``expected_format``."""
        with file_path.open("rb") as handle:
            header = handle.read(4096)

        if not header:
            return False

        if expected_format == DocumentFormat.PDF:
            # Allow optional leading whitespace before %PDF- header per PDF spec tolerance
            if _PDF_MAGIC not in header[:1024]:
                raise CorruptedDocumentError(
                    f"File '{file_path.name}' does not contain a valid %PDF- signature.",
                    details={"expected_format": "pdf"},
                )
            return True

        if expected_format == DocumentFormat.DOCX:
            if not header.startswith(_ZIP_MAGICS):
                raise CorruptedDocumentError(
                    f"File '{file_path.name}' does not contain a valid DOCX/ZIP signature.",
                    details={"expected_format": "docx"},
                )
            try:
                with zipfile.ZipFile(file_path, "r") as archive:
                    names = set(archive.namelist())
                has_content_types = "[Content_Types].xml" in names
                has_word_dir = any(name.startswith("word/") for name in names)
                if not has_content_types or not has_word_dir:
                    raise CorruptedDocumentError(
                        f"DOCX archive '{file_path.name}' is missing required Word OOXML entries.",
                        details={"expected_format": "docx"},
                    )
            except zipfile.BadZipFile as exc:
                raise CorruptedDocumentError(
                    f"File '{file_path.name}' is not a valid ZIP/DOCX container.",
                    details={"reason": str(exc)},
                ) from exc
            return True

        # Text-based formats (TXT, Markdown, CSV): reject binary magic headers
        if header.startswith(_PDF_MAGIC) or header.startswith(_ZIP_MAGICS):
            raise UnsupportedFormatError(
                f"Binary container signature does not match text format '{expected_format.value}'.",
                details={"filename": file_path.name, "expected_format": expected_format.value},
            )
        for magic in _BINARY_EXCLUSION_MAGICS:
            if header.startswith(magic):
                raise UnsupportedFormatError(
                    f"Binary file signature detected for '{file_path.name}'; expected '{expected_format.value}'.",
                    details={"filename": file_path.name, "expected_format": expected_format.value},
                )

        # Allow UTF-16 BOMs (which naturally contain NUL bytes); otherwise NUL implies binary
        has_utf16_bom = header.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
        if b"\x00" in header and not has_utf16_bom:
            raise CorruptedDocumentError(
                f"Binary NUL bytes detected in text document '{file_path.name}'.",
                details={"expected_format": expected_format.value},
            )

        return True

    def detect_and_verify(
        self,
        file_path: Path,
        *,
        declared_filename: str | None = None,
        content_type: str | None = None,
    ) -> DetectedFileType:
        """Detect format from filename/MIME and verify magic bytes against file content."""
        target_name = declared_filename or file_path.name
        fmt, ext, mime = self.detect_from_metadata(target_name, content_type=content_type)
        verified = self.verify_file_signature(file_path, fmt)
        return DetectedFileType(
            format=fmt,
            extension=ext,
            mime_type=mime,
            signature_verified=verified,
        )

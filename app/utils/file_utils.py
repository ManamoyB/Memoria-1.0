"""File system, hashing, filename sanitization, and format detection helpers."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.core.exceptions import UnsupportedFormatError
from app.schemas.common import DocumentFormat

EXTENSION_TO_FORMAT: dict[str, DocumentFormat] = {
    ".pdf": DocumentFormat.PDF,
    ".docx": DocumentFormat.DOCX,
    ".txt": DocumentFormat.TXT,
    ".text": DocumentFormat.TXT,
    ".md": DocumentFormat.MARKDOWN,
    ".markdown": DocumentFormat.MARKDOWN,
    ".csv": DocumentFormat.CSV,
}

MIME_TO_FORMAT: dict[str, DocumentFormat] = {
    "application/pdf": DocumentFormat.PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentFormat.DOCX,
    "text/plain": DocumentFormat.TXT,
    "text/markdown": DocumentFormat.MARKDOWN,
    "text/x-markdown": DocumentFormat.MARKDOWN,
    "text/csv": DocumentFormat.CSV,
    "application/csv": DocumentFormat.CSV,
}

FORMAT_TO_MIME: dict[DocumentFormat, str] = {
    DocumentFormat.PDF: "application/pdf",
    DocumentFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    DocumentFormat.TXT: "text/plain",
    DocumentFormat.MARKDOWN: "text/markdown",
    DocumentFormat.CSV: "text/csv",
}

FORMAT_TO_EXTENSION: dict[DocumentFormat, str] = {
    DocumentFormat.PDF: ".pdf",
    DocumentFormat.DOCX: ".docx",
    DocumentFormat.TXT: ".txt",
    DocumentFormat.MARKDOWN: ".md",
    DocumentFormat.CSV: ".csv",
}

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_PATH_TOKEN_RE = re.compile(r"(?:[A-Za-z]:)?(?:[/\\][^\s:'\",]+)+")


def sanitize_filename(filename: str | None) -> str:
    """Strip directory components (POSIX/Windows) and unsafe characters while preserving extension."""
    if not filename:
        return "untitled"
    normalized_sep = filename.replace("\\", "/")
    base = Path(normalized_sep).name.strip()
    ext = Path(base).suffix.lower()
    stem = Path(base).stem if ext else base
    cleaned_stem = _SAFE_FILENAME_RE.sub("_", stem).strip("._")
    if not cleaned_stem:
        cleaned_stem = "untitled"
    max_stem_len = max(1, 200 - len(ext))
    cleaned_stem = cleaned_stem[:max_stem_len]
    return f"{cleaned_stem}{ext}" if ext else cleaned_stem[:200]


def sanitize_error_reason(exc: Exception, *, replacement_name: str = "<document>") -> str:
    """Redact local filesystem paths from library exception messages before returning API details."""
    raw = str(exc)
    if not raw:
        return type(exc).__name__
    return _PATH_TOKEN_RE.sub(replacement_name, raw)


def detect_document_format(
    filename: str,
    content_type: str | None = None,
) -> tuple[DocumentFormat, str, str]:
    """Resolve canonical DocumentFormat, normalized extension, and MIME type.

    Prioritizes explicit file extension, falling back to HTTP Content-Type when
    an extension is absent. Raises UnsupportedFormatError when unrecognized.
    """
    ext = Path(filename).suffix.lower()
    normalized_mime = (content_type or "").split(";")[0].strip().lower()

    if ext in EXTENSION_TO_FORMAT:
        fmt = EXTENSION_TO_FORMAT[ext]
        resolved_mime = (
            normalized_mime
            if normalized_mime and normalized_mime != "application/octet-stream"
            else FORMAT_TO_MIME[fmt]
        )
        return fmt, ext, resolved_mime

    if normalized_mime in MIME_TO_FORMAT:
        fmt = MIME_TO_FORMAT[normalized_mime]
        return fmt, FORMAT_TO_EXTENSION[fmt], normalized_mime

    raise UnsupportedFormatError(
        f"Unsupported document format for file '{filename}'.",
        details={
            "filename": filename,
            "extension": ext or None,
            "content_type": normalized_mime or None,
            "supported_extensions": sorted(EXTENSION_TO_FORMAT.keys()),
        },
    )


def compute_sha256(file_path: Path, chunk_size: int = 65536) -> str:
    """Compute SHA-256 hex digest of a file on disk using streaming reads."""
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()

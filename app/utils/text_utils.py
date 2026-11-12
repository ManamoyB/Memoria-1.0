"""Pure text decoding, normalization, and metric utilities."""

from __future__ import annotations

import codecs
import re
import unicodedata

from app.core.exceptions import InvalidEncodingError

_MULTI_SPACE_RE = re.compile(r"[^\S\n]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def decode_text_bytes(
    raw_bytes: bytes,
    *,
    preferred: str = "utf-8",
) -> tuple[str, str, list[str]]:
    """Decode raw bytes safely, supporting UTF-8, UTF-8 BOM, UTF-16, and legacy fallbacks.

    Detects non-text binary payloads (such as stray NUL bytes in non-UTF-16 streams)
    and raises ``InvalidEncodingError`` when content cannot be cleanly decoded.

    Returns:
        Tuple of ``(decoded_text, resolved_encoding, warnings)``.
    """
    warnings: list[str] = []

    if raw_bytes.startswith(codecs.BOM_UTF8):
        try:
            return raw_bytes.decode("utf-8-sig"), "utf-8-sig", warnings
        except UnicodeDecodeError as exc:
            raise InvalidEncodingError(
                "Document contains a UTF-8 BOM but has invalid UTF-8 byte sequences.",
                details={"encoding": "utf-8-sig", "reason": str(exc)},
            ) from exc

    if raw_bytes.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return raw_bytes.decode("utf-16"), "utf-16", warnings
        except UnicodeDecodeError as exc:
            raise InvalidEncodingError(
                "Document contains a UTF-16 BOM but could not be decoded as UTF-16.",
                details={"encoding": "utf-16", "reason": str(exc)},
            ) from exc

    # NUL bytes without a UTF-16 BOM strongly indicate a binary or invalidly encoded file.
    if b"\x00" in raw_bytes:
        raise InvalidEncodingError(
            "Document contains binary NUL bytes and cannot be decoded as valid text.",
            details={"reason": "null_bytes_detected"},
        )

    preferred_norm = preferred.strip().lower() or "utf-8"
    candidates = [preferred_norm, "utf-8", "cp1252", "latin-1"]
    seen: set[str] = set()

    for encoding in candidates:
        if encoding in seen:
            continue
        seen.add(encoding)
        try:
            text = raw_bytes.decode(encoding, errors="strict")
            # Reject streams dominated by C0 control bytes (binary garbage mislabeled as latin-1)
            if encoding in {"cp1252", "latin-1"}:
                control_count = sum(
                    1 for ch in text if ord(ch) < 32 and ch not in {"\n", "\r", "\t"}
                )
                if text and (control_count / len(text)) > 0.05:
                    raise InvalidEncodingError(
                        "Document appears to contain binary or corrupted character data.",
                        details={"attempted_encoding": encoding},
                    )
                warnings.append(
                    f"Decoded text using fallback encoding '{encoding}' after '{preferred_norm}' failed."
                )
            return text, encoding, warnings
        except UnicodeDecodeError:
            continue

    raise InvalidEncodingError(
        "Unable to decode document with UTF-8, UTF-8 BOM, UTF-16, CP1252, or Latin-1.",
        details={"attempted_encodings": list(seen)},
    )


def normalize_unicode(text: str) -> str:
    """Normalize text to UTF-8 NFC and strip non-printable control characters."""
    cleaned = unicodedata.normalize("NFC", text)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("\ufeff", "")
    return _CONTROL_CHARS_RE.sub("", cleaned)


def canonicalize_whitespace(text: str, *, preserve_indentation: bool = False) -> str:
    """Canonicalize whitespace while preserving semantic line breaks.

    Args:
        text: Input string to normalize.
        preserve_indentation: When True (e.g. code blocks), keeps leading spaces.
    """
    normalized = normalize_unicode(text)
    if preserve_indentation:
        lines = [line.rstrip() for line in normalized.split("\n")]
        return "\n".join(lines).strip("\n")

    lines = [_MULTI_SPACE_RE.sub(" ", line).strip() for line in normalized.split("\n")]
    joined = "\n".join(lines)
    return _MULTI_NEWLINE_RE.sub("\n\n", joined).strip()


def count_words(text: str) -> int:
    """Count whitespace-delimited words in normalized text."""
    stripped = text.strip()
    if not stripped:
        return 0
    return len(stripped.split())


def count_lines(text: str) -> int:
    """Count lines in normalized text."""
    if not text:
        return 0
    return len(text.split("\n"))

"""Independent plain-text (.txt) extractor with UTF-8/BOM and fallback encoding support."""

from __future__ import annotations

import re
import time
from pathlib import Path

from app.core.exceptions import EmptyDocumentError, ExtractionError, InvalidEncodingError
from app.extractors.base import (
    BaseExtractor,
    ExtractedContent,
    ExtractionContext,
    RawBlock,
    RawStatistics,
)
from app.schemas.common import BlockType, DocumentFormat
from app.utils.text_utils import (
    canonicalize_whitespace,
    count_lines,
    count_words,
    decode_text_bytes,
)

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")


class TextExtractor(BaseExtractor):
    """Extracts paragraph-segmented, normalized text blocks from plain text files."""

    name = "plain_text_extractor"
    supported_format = DocumentFormat.TXT
    supported_extensions = (".txt", ".text")
    supported_mime_types = ("text/plain",)
    supports_tables = False
    ocr_fallback_ready = False

    def extract(
        self,
        file_path: Path,
        context: ExtractionContext,
    ) -> ExtractedContent:
        """Read plain text safely (UTF-8, UTF-8 BOM, fallback encodings) and normalize."""
        started = time.perf_counter()
        self.validate_file(file_path, context)

        try:
            raw_bytes = file_path.read_bytes()
        except OSError as exc:
            raise ExtractionError(
                f"Failed to read text file '{file_path.name}'.",
                details={"reason": str(exc)},
            ) from exc

        decoded, used_encoding, warnings = decode_text_bytes(
            raw_bytes, preferred=context.default_encoding
        )

        normalized_raw = canonicalize_whitespace(decoded)
        if not normalized_raw:
            raise EmptyDocumentError(
                f"Text document '{file_path.name}' contains only whitespace."
            )

        paragraphs = [
            chunk.strip()
            for chunk in _PARAGRAPH_SPLIT_RE.split(normalized_raw)
            if chunk.strip()
        ]
        blocks = [
            RawBlock(type=BlockType.PARAGRAPH, text=paragraph)
            for paragraph in paragraphs
        ]

        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return ExtractedContent(
            extractor_name=self.name,
            format=self.supported_format,
            raw_text=normalized_raw,
            blocks=blocks,
            encoding=used_encoding,
            statistics=RawStatistics(
                extraction_time_ms=elapsed_ms,
                char_count=len(normalized_raw),
                word_count=count_words(normalized_raw),
                line_count=count_lines(normalized_raw),
                block_count=len(blocks),
            ),
            warnings=warnings,
        )

"""Independent structural Markdown extractor with UTF-8/BOM and Setext/ATX support."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from app.core.exceptions import EmptyDocumentError, ExtractionError
from app.extractors.base import (
    BaseExtractor,
    ExtractedContent,
    ExtractionContext,
    RawBlock,
    RawStatistics,
    RawTable,
)
from app.schemas.common import BlockType, DocumentFormat
from app.utils.text_utils import (
    canonicalize_whitespace,
    count_lines,
    count_words,
    decode_text_bytes,
    normalize_unicode,
)

_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
_SETEXT_H1_RE = re.compile(r"^={3,}\s*$")
_SETEXT_H2_RE = re.compile(r"^-{3,}\s*$")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})(.*)$")
_LIST_ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.+)$")
_BLOCKQUOTE_RE = re.compile(r"^>\s?(.*)$")
_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$")


class MarkdownExtractor(BaseExtractor):
    """Extracts frontmatter, ATX/Setext headings, line breaks, lists, code, and tables from Markdown."""

    name = "markdown_structural_extractor"
    supported_format = DocumentFormat.MARKDOWN
    supported_extensions = (".md", ".markdown")
    supported_mime_types = ("text/markdown", "text/x-markdown")
    supports_tables = True
    ocr_fallback_ready = False

    def extract(
        self,
        file_path: Path,
        context: ExtractionContext,
    ) -> ExtractedContent:
        """Decode Markdown safely and extract ordered structural blocks, tables, and frontmatter."""
        started = time.perf_counter()
        self.validate_file(file_path, context)

        try:
            raw_bytes = file_path.read_bytes()
        except OSError as exc:
            raise ExtractionError(
                f"Failed to read Markdown file '{file_path.name}'.",
                details={"reason": str(exc)},
            ) from exc

        decoded, used_encoding, warnings = decode_text_bytes(
            raw_bytes, preferred=context.default_encoding
        )

        normalized = normalize_unicode(decoded)
        if not normalized.strip():
            raise EmptyDocumentError(
                f"Markdown document '{file_path.name}' contains only whitespace."
            )

        lines = normalized.split("\n")
        idx = 0
        blocks: list[RawBlock] = []
        tables: list[RawTable] = []
        custom_props: dict[str, Any] = {}
        title: str | None = None

        # Extract optional YAML frontmatter block
        if lines and lines[0].strip() == "---":
            fm_end = self._find_frontmatter_end(lines)
            if fm_end is not None:
                fm_lines = lines[1:fm_end]
                fm_text = "\n".join(fm_lines).strip()
                frontmatter = self._parse_simple_frontmatter(fm_lines)
                if frontmatter:
                    custom_props["frontmatter"] = frontmatter
                    if isinstance(frontmatter.get("title"), str):
                        title = frontmatter["title"]
                if fm_text:
                    blocks.append(
                        RawBlock(
                            type=BlockType.FRONTMATTER,
                            text=fm_text,
                            metadata={"format": "yaml"},
                        )
                    )
                idx = fm_end + 1

        paragraph_buf: list[str] = []

        def flush_paragraph() -> None:
            if paragraph_buf:
                # Preserve intentional line breaks within paragraphs
                joined = "\n".join(part.strip() for part in paragraph_buf if part.strip())
                if joined:
                    blocks.append(RawBlock(type=BlockType.PARAGRAPH, text=joined))
                paragraph_buf.clear()

        while idx < len(lines):
            line = lines[idx]
            stripped = line.strip()

            if not stripped:
                flush_paragraph()
                idx += 1
                continue

            # Fenced code block
            fence_match = _FENCE_RE.match(stripped)
            if fence_match:
                flush_paragraph()
                fence_token = fence_match.group(1)
                language = fence_match.group(2).strip() or None
                code_lines: list[str] = []
                idx += 1
                closed = False
                while idx < len(lines):
                    if lines[idx].strip().startswith(fence_token[0] * len(fence_token)):
                        idx += 1
                        closed = True
                        break
                    code_lines.append(lines[idx])
                    idx += 1
                if not closed:
                    warnings.append("Unclosed fenced code block encountered; parsed through EOF.")
                blocks.append(
                    RawBlock(
                        type=BlockType.CODE_BLOCK,
                        text="\n".join(code_lines),
                        metadata={"language": language} if language else {},
                    )
                )
                continue

            # ATX Heading
            heading_match = _ATX_HEADING_RE.match(stripped)
            if heading_match:
                flush_paragraph()
                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()
                if title is None and level == 1:
                    title = heading_text
                blocks.append(
                    RawBlock(
                        type=BlockType.HEADING,
                        text=heading_text,
                        level=level,
                    )
                )
                idx += 1
                continue

            # Setext Heading (Title\n=== or Subtitle\n---)
            if idx + 1 < len(lines) and not paragraph_buf:
                next_stripped = lines[idx + 1].strip()
                if _SETEXT_H1_RE.match(next_stripped) or _SETEXT_H2_RE.match(next_stripped):
                    level = 1 if _SETEXT_H1_RE.match(next_stripped) else 2
                    if title is None and level == 1:
                        title = stripped
                    blocks.append(
                        RawBlock(
                            type=BlockType.HEADING,
                            text=stripped,
                            level=level,
                            metadata={"heading_style": "setext"},
                        )
                    )
                    idx += 2
                    continue

            # Pipe Table
            if (
                "|" in line
                and idx + 1 < len(lines)
                and _TABLE_SEP_RE.match(lines[idx + 1].strip())
            ):
                flush_paragraph()
                headers = self._split_pipe_row(line)
                idx += 2
                rows: list[list[str]] = []
                while idx < len(lines) and "|" in lines[idx] and lines[idx].strip():
                    rows.append(self._split_pipe_row(lines[idx]))
                    idx += 1
                records = [
                    {
                        headers[c] if c < len(headers) else f"col_{c + 1}": (
                            row[c] if c < len(row) else ""
                        )
                        for c in range(max(len(headers), len(row)))
                    }
                    for row in rows
                ]
                table = RawTable(
                    name=f"Table {len(tables) + 1}",
                    headers=headers,
                    rows=rows,
                    records=records,
                    total_row_count=len(rows),
                )
                tables.append(table)
                blocks.append(
                    RawBlock(
                        type=BlockType.TABLE,
                        text="\n".join(
                            [" | ".join(headers), *[" | ".join(r) for r in rows]]
                        ),
                        metadata={"table_index": len(tables) - 1},
                    )
                )
                continue

            # Blockquote
            quote_match = _BLOCKQUOTE_RE.match(stripped)
            if quote_match:
                flush_paragraph()
                quote_lines: list[str] = [quote_match.group(1)]
                idx += 1
                while idx < len(lines):
                    next_quote = _BLOCKQUOTE_RE.match(lines[idx].strip())
                    if not next_quote:
                        break
                    quote_lines.append(next_quote.group(1))
                    idx += 1
                blocks.append(
                    RawBlock(
                        type=BlockType.QUOTE,
                        text="\n".join(quote_lines).strip(),
                    )
                )
                continue

            # List item
            list_match = _LIST_ITEM_RE.match(line)
            if list_match:
                flush_paragraph()
                indent = len(list_match.group(1).replace("\t", "  "))
                marker = list_match.group(2)
                item_text = list_match.group(3).strip()
                nesting = min(6, (indent // 2) + 1)
                blocks.append(
                    RawBlock(
                        type=BlockType.LIST_ITEM,
                        text=item_text,
                        level=nesting,
                        metadata={"marker": marker},
                    )
                )
                idx += 1
                continue

            paragraph_buf.append(line)
            idx += 1

        flush_paragraph()

        if not blocks:
            raise EmptyDocumentError(
                f"Markdown document '{file_path.name}' yielded no structural blocks."
            )

        raw_text = canonicalize_whitespace(normalized)
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)

        return ExtractedContent(
            extractor_name=self.name,
            format=self.supported_format,
            raw_text=raw_text,
            blocks=blocks,
            tables=tables,
            title=title,
            encoding=used_encoding,
            custom_properties=custom_props,
            statistics=RawStatistics(
                extraction_time_ms=elapsed_ms,
                char_count=len(raw_text),
                word_count=count_words(raw_text),
                line_count=count_lines(raw_text),
                block_count=len(blocks),
                table_count=len(tables),
            ),
            warnings=warnings,
        )

    @staticmethod
    def _find_frontmatter_end(lines: list[str]) -> int | None:
        for i in range(1, min(len(lines), 100)):
            if lines[i].strip() == "---":
                return i
        return None

    @staticmethod
    def _parse_simple_frontmatter(lines: list[str]) -> dict[str, str]:
        data: dict[str, str] = {}
        for line in lines:
            if ":" not in line or line.strip().startswith("#"):
                continue
            key, _, val = line.partition(":")
            cleaned_key = key.strip()
            cleaned_val = val.strip().strip("'\"")
            if cleaned_key and cleaned_val:
                data[cleaned_key] = cleaned_val
        return data

    @staticmethod
    def _split_pipe_row(line: str) -> list[str]:
        stripped = line.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        return [cell.strip() for cell in stripped.split("|")]

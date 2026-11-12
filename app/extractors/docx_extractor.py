"""Independent DOCX extractor powered by python-docx."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

from docx import Document as load_docx
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.core.exceptions import CorruptedDocumentError, EmptyDocumentError, ExtractionError
from app.extractors.base import (
    BaseExtractor,
    ExtractedContent,
    ExtractionContext,
    RawBlock,
    RawStatistics,
    RawTable,
)
from app.schemas.common import BlockType, DocumentFormat
from app.utils.file_utils import sanitize_error_reason
from app.utils.text_utils import count_lines, count_words


class DocxExtractor(BaseExtractor):
    """Extracts reading-order paragraphs, styles, headings, tables, and core props from DOCX files."""

    name = "python_docx_extractor"
    supported_format = DocumentFormat.DOCX
    supported_extensions = (".docx",)
    supported_mime_types = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    supports_tables = True
    ocr_fallback_ready = False

    def extract(
        self,
        file_path: Path,
        context: ExtractionContext,
    ) -> ExtractedContent:
        """Extract structured blocks, tables, styles, and core properties in document order."""
        started = time.perf_counter()
        self.validate_file(file_path, context)

        try:
            doc = load_docx(str(file_path))
        except Exception as exc:
            raise CorruptedDocumentError(
                f"Failed to open DOCX document '{file_path.name}'.",
                details={"reason": sanitize_error_reason(exc, replacement_name=file_path.name)},
            ) from exc

        try:
            blocks: list[RawBlock] = []
            tables: list[RawTable] = []
            style_counts: Counter[str] = Counter()
            warnings: list[str] = []

            for item in self._iter_body_items(doc):
                if isinstance(item, Paragraph):
                    block = self._paragraph_to_block(item)
                    if block is not None:
                        style_name = block.metadata.get("style")
                        if isinstance(style_name, str) and style_name:
                            style_counts[style_name] += 1
                        blocks.append(block)
                elif isinstance(item, Table):
                    raw_table = self._extract_table(item, len(tables) + 1)
                    if raw_table is not None:
                        tables.append(raw_table)
                        blocks.append(
                            RawBlock(
                                type=BlockType.TABLE,
                                text=self._table_to_text(raw_table),
                                metadata={
                                    "table_index": len(tables) - 1,
                                    "row_count": len(raw_table.rows),
                                    "column_count": len(raw_table.headers),
                                },
                            )
                        )
                    else:
                        warnings.append(f"Skipped empty table at document position {len(blocks)}.")

            if not blocks and not tables:
                raise EmptyDocumentError(
                    f"DOCX document '{file_path.name}' contains no extractable text or tables."
                )

            core = doc.core_properties
            custom_props: dict[str, Any] = {}
            for attr in (
                "subject",
                "category",
                "keywords",
                "comments",
                "last_modified_by",
                "language",
                "content_status",
            ):
                val = getattr(core, attr, None)
                if val:
                    custom_props[attr] = val
            if getattr(core, "revision", None) is not None:
                custom_props["revision"] = core.revision
            if style_counts:
                custom_props["paragraph_styles"] = dict(style_counts)

            raw_text = "\n\n".join(b.text for b in blocks if b.text.strip())
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)

            return ExtractedContent(
                extractor_name=self.name,
                format=self.supported_format,
                raw_text=raw_text,
                blocks=blocks,
                tables=tables,
                title=core.title or None,
                author=core.author or None,
                created_at=core.created.isoformat() if core.created else None,
                modified_at=core.modified.isoformat() if core.modified else None,
                encoding="utf-8",
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
        except EmptyDocumentError:
            raise
        except Exception as exc:
            raise ExtractionError(
                f"Unexpected error while extracting DOCX '{file_path.name}'.",
                details={"reason": sanitize_error_reason(exc, replacement_name=file_path.name)},
            ) from exc

    def _iter_body_items(self, doc: DocxDocument) -> Iterator[Paragraph | Table]:
        """Yield Paragraph and Table instances in true XML document order."""
        body = doc.element.body
        for child in body.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, doc)
            elif isinstance(child, CT_Tbl):
                yield Table(child, doc)

    def _paragraph_to_block(self, paragraph: Paragraph) -> RawBlock | None:
        text = paragraph.text.strip()
        if not text:
            return None

        style_name = (paragraph.style.name if paragraph.style else "") or ""
        style_lower = style_name.lower()

        if style_lower.startswith("heading"):
            level = self._parse_heading_level(style_lower)
            return RawBlock(
                type=BlockType.HEADING,
                text=text,
                level=level,
                metadata={"style": style_name},
            )

        if style_lower == "title":
            return RawBlock(
                type=BlockType.HEADING,
                text=text,
                level=1,
                metadata={"style": style_name},
            )

        if style_lower == "subtitle":
            return RawBlock(
                type=BlockType.HEADING,
                text=text,
                level=2,
                metadata={"style": style_name},
            )

        if "list" in style_lower or self._has_numbering_xml(paragraph):
            return RawBlock(
                type=BlockType.LIST_ITEM,
                text=text,
                level=1,
                metadata={"style": style_name} if style_name else {},
            )

        if "quote" in style_lower:
            return RawBlock(
                type=BlockType.QUOTE,
                text=text,
                metadata={"style": style_name},
            )

        return RawBlock(
            type=BlockType.PARAGRAPH,
            text=text,
            metadata={"style": style_name} if style_name else {},
        )

    @staticmethod
    def _parse_heading_level(style_lower: str) -> int:
        for token in style_lower.split():
            if token.isdigit():
                return max(1, min(6, int(token)))
        return 1

    @staticmethod
    def _has_numbering_xml(paragraph: Paragraph) -> bool:
        p_pr = paragraph._p.pPr
        return p_pr is not None and p_pr.numPr is not None

    @staticmethod
    def _extract_table(table: Table, index: int) -> RawTable | None:
        matrix: list[list[str]] = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                matrix.append(cells)

        if not matrix:
            return None

        max_cols = max(len(r) for r in matrix)
        padded = [r + [""] * (max_cols - len(r)) for r in matrix]
        headers = padded[0]
        rows = padded[1:] if len(padded) > 1 else []
        records = [
            {
                headers[col_idx] or f"column_{col_idx + 1}": row[col_idx]
                for col_idx in range(max_cols)
            }
            for row in rows
        ]

        return RawTable(
            name=f"Table {index}",
            headers=headers,
            rows=rows,
            records=records,
            total_row_count=len(rows),
        )

    @staticmethod
    def _table_to_text(table: RawTable) -> str:
        lines = [" | ".join(table.headers)]
        for row in table.rows:
            lines.append(" | ".join(row))
        return "\n".join(lines)

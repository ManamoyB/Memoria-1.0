"""Content and structural normalizer producing MemoriaOS-compatible schemas."""

from __future__ import annotations

import time
import uuid
from typing import Iterable

from app.extractors.base import ExtractedContent, RawBlock, RawPageReference, RawTable
from app.schemas.common import BlockType, ExtractionStatus, OcrStatus
from app.schemas.document import (
    ChunkingConfig,
    DocumentBlock,
    DocumentMetadata,
    DocumentSource,
    NormalizedDocument,
    OcrMetadata,
    PageReference,
    ProcessingStatistics,
    SectionNode,
    TableData,
)
from app.services.chunker import DocumentChunker
from app.utils.text_utils import (
    canonicalize_whitespace,
    count_lines,
    count_words,
    normalize_unicode,
)

_MEMORIA_NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


class DocumentNormalizer:
    """Transforms raw extractor output into the standardized NormalizedDocument contract.

    Preserves paragraphs, headings, tables, page numbers, source provenance, and
    reading order without removing meaningful information.
    """

    def __init__(self, chunker: DocumentChunker | None = None) -> None:
        self._chunker = chunker or DocumentChunker()

    def normalize(
        self,
        *,
        extracted: ExtractedContent,
        source: DocumentSource,
        total_started_perf: float | None = None,
        chunking_config: ChunkingConfig | None = None,
    ) -> NormalizedDocument:
        """Normalize text, build section hierarchy, generate chunks, and compute stats."""
        norm_started = time.perf_counter()
        document_id = str(
            uuid.uuid5(_MEMORIA_NAMESPACE, f"memoriaos:document:{source.content_hash}")
        )

        blocks, sections = self._normalize_blocks_and_sections(
            raw_blocks=extracted.blocks,
            document_id=document_id,
        )
        tables = self._normalize_tables(extracted.tables, document_id=document_id)
        pages = self._normalize_pages(extracted.pages)

        content = self._assemble_normalized_text(blocks)
        title = self._resolve_title(extracted.title, blocks, source.filename)

        norm_elapsed_ms = round((time.perf_counter() - norm_started) * 1000.0, 2)

        chunk_started = time.perf_counter()
        chunks = self._chunker.chunk_document(
            document_id=document_id,
            blocks=blocks,
            sections=sections,
            config=chunking_config,
        )
        chunk_elapsed_ms = round((time.perf_counter() - chunk_started) * 1000.0, 2)

        ocr_signal = extracted.ocr_signal
        ocr_metadata = OcrMetadata(
            status=ocr_signal.status,
            ocr_enabled=ocr_signal.ocr_enabled,
            ocr_applied=ocr_signal.ocr_applied,
            ocr_engine=ocr_signal.ocr_engine,
            pages_requiring_ocr=ocr_signal.pages_requiring_ocr,
            empty_pages=ocr_signal.empty_pages,
            notes=[canonicalize_whitespace(note) for note in ocr_signal.notes if note.strip()],
        )

        status = ExtractionStatus.SUCCESS
        if ocr_signal.status == OcrStatus.DEFERRED_DISABLED and not content.strip():
            status = ExtractionStatus.PARTIAL

        word_count = count_words(content)
        char_count = len(content)
        line_count = count_lines(content)
        section_count = self._count_sections(sections)

        total_elapsed_ms = (
            round((time.perf_counter() - total_started_perf) * 1000.0, 2)
            if total_started_perf is not None
            else round(
                extracted.statistics.extraction_time_ms + norm_elapsed_ms + chunk_elapsed_ms,
                2,
            )
        )

        metadata = DocumentMetadata(
            title=title,
            author=canonicalize_whitespace(extracted.author) if extracted.author else None,
            created_at=extracted.created_at,
            modified_at=extracted.modified_at,
            page_count=extracted.page_count,
            block_count=len(blocks),
            section_count=section_count,
            table_count=len(tables),
            chunk_count=len(chunks),
            word_count=word_count,
            char_count=char_count,
            line_count=line_count,
            encoding=extracted.encoding,
            extractor_name=extracted.extractor_name,
            custom_properties=extracted.custom_properties,
        )

        stats = ProcessingStatistics(
            extraction_time_ms=extracted.statistics.extraction_time_ms,
            normalization_time_ms=norm_elapsed_ms,
            chunking_time_ms=chunk_elapsed_ms,
            total_time_ms=total_elapsed_ms,
            char_count=char_count,
            word_count=word_count,
            line_count=line_count,
            block_count=len(blocks),
            section_count=section_count,
            table_count=len(tables),
            chunk_count=len(chunks),
            page_count=extracted.page_count,
            empty_page_count=extracted.statistics.empty_page_count,
            scanned_page_count=extracted.statistics.scanned_page_count,
            records_extracted=extracted.statistics.records_extracted,
            truncated=extracted.statistics.truncated,
        )

        return NormalizedDocument(
            document_id=document_id,
            filename=source.filename,
            document_type=source.format,
            status=status,
            ingested_at=source.ingested_at,
            source=source,
            metadata=metadata,
            content=content,
            blocks=blocks,
            sections=sections,
            tables=tables,
            pages=pages,
            chunks=chunks,
            ocr=ocr_metadata,
            processing_statistics=stats,
            extraction_warnings=list(extracted.warnings),
            processing_time_ms=total_elapsed_ms,
        )

    def _normalize_blocks_and_sections(
        self,
        *,
        raw_blocks: list[RawBlock],
        document_id: str,
    ) -> tuple[list[DocumentBlock], list[SectionNode]]:
        """Normalize raw blocks and construct a nested SectionNode hierarchy."""
        blocks: list[DocumentBlock] = []
        root_sections: list[SectionNode] = []
        section_stack: list[SectionNode] = []
        section_counter = 0

        for raw in raw_blocks:
            preserve_indent = raw.type in {BlockType.CODE_BLOCK, BlockType.FRONTMATTER}
            text = canonicalize_whitespace(raw.text, preserve_indentation=preserve_indent)
            if not text and not raw.metadata.get("ocr_pending"):
                continue

            order_index = len(blocks)
            block_id = f"{document_id[:8]}-blk-{order_index:04d}"

            if raw.type == BlockType.HEADING:
                level = max(1, min(6, raw.level or 1))
                section_counter += 1
                section_id = f"{document_id[:8]}-sec-{section_counter:04d}"
                section_node = SectionNode(
                    section_id=section_id,
                    title=text,
                    level=level,
                    order_index=order_index,
                    page_number=raw.page_number,
                    block_ids=[block_id],
                )
                while section_stack and section_stack[-1].level >= level:
                    section_stack.pop()

                if section_stack:
                    section_stack[-1].children.append(section_node)
                else:
                    root_sections.append(section_node)

                section_stack.append(section_node)
                parent_section_id = section_id
            else:
                parent_section_id = section_stack[-1].section_id if section_stack else None
                if section_stack:
                    section_stack[-1].block_ids.append(block_id)

            blocks.append(
                DocumentBlock(
                    block_id=block_id,
                    type=raw.type,
                    text=text,
                    order_index=order_index,
                    level=raw.level,
                    page_number=raw.page_number,
                    parent_section_id=parent_section_id,
                    metadata=raw.metadata,
                )
            )

        return blocks, root_sections

    def _normalize_tables(
        self, raw_tables: Iterable[RawTable], *, document_id: str
    ) -> list[TableData]:
        normalized: list[TableData] = []
        for idx, raw_table in enumerate(raw_tables):
            headers = [canonicalize_whitespace(h) for h in raw_table.headers]
            rows = [
                [canonicalize_whitespace(cell) for cell in row]
                for row in raw_table.rows
            ]
            records = [
                {
                    canonicalize_whitespace(k): canonicalize_whitespace(v)
                    for k, v in rec.items()
                }
                for rec in raw_table.records
            ]
            col_count = max(
                [len(headers), *[len(r) for r in rows]],
                default=0,
            )
            normalized.append(
                TableData(
                    table_id=f"{document_id[:8]}-tbl-{idx + 1:03d}",
                    name=canonicalize_whitespace(raw_table.name) if raw_table.name else None,
                    headers=headers,
                    rows=rows,
                    records=records,
                    column_types=dict(raw_table.column_types),
                    row_count=len(rows),
                    total_row_count=(
                        raw_table.total_row_count
                        if raw_table.total_row_count is not None
                        else len(rows)
                    ),
                    column_count=col_count,
                    truncated=raw_table.truncated,
                    page_number=raw_table.page_number,
                    metadata=raw_table.metadata,
                )
            )
        return normalized

    @staticmethod
    def _normalize_pages(raw_pages: list[RawPageReference]) -> list[PageReference]:
        return [
            PageReference(
                page_number=page.page_number,
                char_count=page.char_count,
                word_count=page.word_count,
                block_count=page.block_count,
                is_empty=page.is_empty,
                potentially_scanned=page.potentially_scanned,
                has_images=page.has_images,
                ocr_applied=page.ocr_applied,
            )
            for page in raw_pages
        ]

    @staticmethod
    def _assemble_normalized_text(blocks: list[DocumentBlock]) -> str:
        parts: list[str] = []
        for block in blocks:
            if not block.text:
                continue
            if block.type == BlockType.FRONTMATTER:
                continue
            if block.type == BlockType.HEADING:
                prefix = "#" * (block.level or 1)
                parts.append(f"{prefix} {block.text}")
            elif block.type == BlockType.LIST_ITEM:
                parts.append(f"- {block.text}")
            else:
                parts.append(block.text)
        return normalize_unicode("\n\n".join(parts)).strip()

    @staticmethod
    def _resolve_title(
        explicit_title: str | None,
        blocks: list[DocumentBlock],
        fallback_filename: str,
    ) -> str:
        if explicit_title and explicit_title.strip():
            return canonicalize_whitespace(explicit_title)
        for block in blocks:
            if block.type == BlockType.HEADING and block.text:
                return block.text
        return fallback_filename

    def _count_sections(self, sections: list[SectionNode]) -> int:
        total = 0
        for section in sections:
            total += 1 + self._count_sections(section.children)
        return total

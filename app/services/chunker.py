"""Configurable paragraph-aware document chunker for downstream RAG pipelines."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.schemas.common import BlockType
from app.schemas.document import ChunkingConfig, DocumentBlock, DocumentChunk, SectionNode
from app.utils.text_utils import count_words

_CHUNK_NAMESPACE = uuid.UUID("6ba7b812-9dad-11d1-80b4-00c04fd430c8")


@dataclass(slots=True)
class _SpanUnit:
    """Formatted block unit tracked during paragraph-aware chunk assembly."""

    block_id: str
    text: str
    page_number: int | None
    section_id: str | None


class DocumentChunker:
    """Splits normalized document blocks into overlapping, structure-aware chunks.

    Designed for large documents and downstream Qdrant / LangGraph indexing:
    - Defaults to ``chunk_size=3000`` characters and ``chunk_overlap=300`` characters.
    - Preserves paragraph/block boundaries where possible.
    - Preserves 1-based page numbers, enclosing section metadata, and block IDs.
    - Generates deterministic unique chunk IDs and never emits empty chunks.
    """

    def __init__(self, default_config: ChunkingConfig | None = None) -> None:
        self._default_config = default_config or ChunkingConfig()

    def chunk_document(
        self,
        *,
        document_id: str,
        blocks: list[DocumentBlock],
        sections: list[SectionNode],
        config: ChunkingConfig | None = None,
    ) -> list[DocumentChunk]:
        """Partition ordered ``blocks`` into non-empty ``DocumentChunk`` instances."""
        cfg = config or self._default_config
        section_titles = self._index_section_titles(sections)
        units = self._build_units(blocks)
        if not units:
            return []

        chunks: list[DocumentChunk] = []
        current_units: list[_SpanUnit] = []
        current_len = 0
        cursor_char = 0

        for unit in units:
            # Oversized single unit: flush existing buffer first, then slice cleanly
            if len(unit.text) > cfg.chunk_size:
                if current_units:
                    chunk = self._finalize_chunk(
                        document_id=document_id,
                        chunk_index=len(chunks),
                        units=current_units,
                        start_char=cursor_char,
                        section_titles=section_titles,
                    )
                    chunks.append(chunk)
                    cursor_char = max(0, chunk.end_char - cfg.chunk_overlap)
                    current_units = []
                    current_len = 0

                for slice_text in self._split_oversized_text(
                    unit.text,
                    chunk_size=cfg.chunk_size,
                    chunk_overlap=cfg.chunk_overlap,
                    preserve_paragraphs=cfg.preserve_paragraphs,
                ):
                    slice_unit = _SpanUnit(
                        block_id=unit.block_id,
                        text=slice_text,
                        page_number=unit.page_number,
                        section_id=unit.section_id,
                    )
                    chunk = self._finalize_chunk(
                        document_id=document_id,
                        chunk_index=len(chunks),
                        units=[slice_unit],
                        start_char=cursor_char,
                        section_titles=section_titles,
                    )
                    chunks.append(chunk)
                    cursor_char = max(0, chunk.end_char - cfg.chunk_overlap)
                continue

            separator_len = 2 if current_units else 0
            projected_len = current_len + separator_len + len(unit.text)

            if current_units and projected_len > cfg.chunk_size:
                chunk = self._finalize_chunk(
                    document_id=document_id,
                    chunk_index=len(chunks),
                    units=current_units,
                    start_char=cursor_char,
                    section_titles=section_titles,
                )
                chunks.append(chunk)
                cursor_char = max(0, chunk.end_char - cfg.chunk_overlap)

                current_units = self._retain_overlap_units(
                    current_units,
                    overlap_budget=cfg.chunk_overlap,
                    max_size=cfg.chunk_size - len(unit.text) - 2,
                )
                current_len = self._measure_units(current_units)

            current_units.append(unit)
            current_len = self._measure_units(current_units)

        if current_units:
            chunks.append(
                self._finalize_chunk(
                    document_id=document_id,
                    chunk_index=len(chunks),
                    units=current_units,
                    start_char=cursor_char,
                    section_titles=section_titles,
                )
            )

        return chunks

    @staticmethod
    def _build_units(blocks: list[DocumentBlock]) -> list[_SpanUnit]:
        units: list[_SpanUnit] = []
        for block in blocks:
            if block.type == BlockType.FRONTMATTER:
                continue
            raw_text = block.text.strip()
            if not raw_text:
                continue
            if block.type == BlockType.HEADING:
                formatted = f"{'#' * (block.level or 1)} {raw_text}"
            elif block.type == BlockType.LIST_ITEM:
                formatted = f"- {raw_text}"
            else:
                formatted = raw_text

            units.append(
                _SpanUnit(
                    block_id=block.block_id,
                    text=formatted,
                    page_number=block.page_number,
                    section_id=block.parent_section_id,
                )
            )
        return units

    @staticmethod
    def _measure_units(units: list[_SpanUnit]) -> int:
        if not units:
            return 0
        return sum(len(u.text) for u in units) + 2 * (len(units) - 1)

    @staticmethod
    def _retain_overlap_units(
        units: list[_SpanUnit],
        *,
        overlap_budget: int,
        max_size: int,
    ) -> list[_SpanUnit]:
        if overlap_budget <= 0 or max_size <= 0:
            return []
        retained: list[_SpanUnit] = []
        total = 0
        budget = min(overlap_budget, max_size)
        for unit in reversed(units):
            added_len = len(unit.text) + (2 if retained else 0)
            if total + added_len > budget:
                break
            retained.insert(0, unit)
            total += added_len
        return retained

    @staticmethod
    def _split_oversized_text(
        text: str,
        *,
        chunk_size: int,
        chunk_overlap: int,
        preserve_paragraphs: bool,
    ) -> list[str]:
        """Split an oversized single block along line/sentence/word boundaries."""
        segments: list[str] = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + chunk_size, text_len)
            if end < text_len and preserve_paragraphs:
                # Prefer newline, then sentence boundary, then whitespace
                split_at = text.rfind("\n", start + chunk_size // 2, end)
                if split_at == -1:
                    split_at = text.rfind(". ", start + chunk_size // 2, end)
                    if split_at != -1:
                        split_at += 1
                if split_at == -1:
                    split_at = text.rfind(" ", start + chunk_size // 2, end)
                if split_at > start:
                    end = split_at

            piece = text[start:end].strip()
            if piece:
                segments.append(piece)

            if end >= text_len:
                break
            next_start = max(start + 1, end - chunk_overlap)
            start = next_start

        return segments

    def _index_section_titles(self, sections: list[SectionNode]) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for section in sections:
            mapping[section.section_id] = section.title
            if section.children:
                mapping.update(self._index_section_titles(section.children))
        return mapping

    @staticmethod
    def _finalize_chunk(
        *,
        document_id: str,
        chunk_index: int,
        units: list[_SpanUnit],
        start_char: int,
        section_titles: dict[str, str],
    ) -> DocumentChunk:
        text = "\n\n".join(u.text for u in units).strip()
        page_numbers = sorted({u.page_number for u in units if u.page_number is not None})
        block_ids = list(dict.fromkeys(u.block_id for u in units))
        section_id = next((u.section_id for u in units if u.section_id is not None), None)
        section_title = section_titles.get(section_id) if section_id else None
        chunk_id = str(
            uuid.uuid5(_CHUNK_NAMESPACE, f"{document_id}:chunk:{chunk_index}:{text[:64]}")
        )
        return DocumentChunk(
            chunk_id=chunk_id,
            document_id=document_id,
            chunk_index=chunk_index,
            text=text,
            char_count=len(text),
            word_count=count_words(text),
            start_char=start_char,
            end_char=start_char + len(text),
            page_numbers=page_numbers,
            block_ids=block_ids,
            section_id=section_id,
            section_title=section_title,
        )

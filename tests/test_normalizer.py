"""Unit tests for DocumentNormalizer structural normalization and MemoriaOS contract."""

from __future__ import annotations

from app.extractors.base import ExtractedContent, RawBlock, RawPageReference, RawTable
from app.schemas.common import BlockType, DocumentFormat, ExtractionStatus
from app.schemas.document import ChunkingConfig, DocumentSource
from app.services.normalizer import DocumentNormalizer


def test_normalizer_builds_hierarchical_sections_chunks_and_deterministic_id() -> None:
    extracted = ExtractedContent(
        extractor_name="markdown_structural_extractor",
        format=DocumentFormat.MARKDOWN,
        blocks=[
            RawBlock(type=BlockType.HEADING, text="Root   Topic", level=1, page_number=1),
            RawBlock(type=BlockType.PARAGRAPH, text="Cafe\u0301   overview\r\nline.", page_number=1),
            RawBlock(type=BlockType.HEADING, text="Subtopic", level=2, page_number=2),
            RawBlock(type=BlockType.CODE_BLOCK, text="  def run():\n      return 1", page_number=2),
        ],
        tables=[RawTable(name="Summary", headers=["K", "V"], rows=[["a", "1"]])],
        pages=[
            RawPageReference(page_number=1, char_count=30, word_count=4, block_count=2),
            RawPageReference(page_number=2, char_count=35, word_count=5, block_count=2),
        ],
        warnings=["Sample extraction warning"],
    )
    source = DocumentSource(
        filename="sample.md",
        extension=".md",
        format=DocumentFormat.MARKDOWN,
        mime_type="text/markdown",
        byte_size=128,
        content_hash="sha256:abc123",
    )

    normalizer = DocumentNormalizer()
    doc_a = normalizer.normalize(
        extracted=extracted,
        source=source,
        chunking_config=ChunkingConfig(chunk_size=120, chunk_overlap=20),
    )
    doc_b = normalizer.normalize(
        extracted=extracted,
        source=source,
        chunking_config=ChunkingConfig(chunk_size=120, chunk_overlap=20),
    )

    assert doc_a.document_id == doc_b.document_id
    assert doc_a.filename == "sample.md"
    assert doc_a.document_type == DocumentFormat.MARKDOWN
    assert doc_a.status == ExtractionStatus.SUCCESS
    assert doc_a.metadata.section_count == 2
    assert doc_a.metadata.table_count == 1
    assert doc_a.metadata.chunk_count == len(doc_a.chunks)
    assert len(doc_a.pages) == 2
    assert len(doc_a.chunks) >= 1
    assert doc_a.extraction_warnings == ["Sample extraction warning"]

    assert len(doc_a.sections) == 1
    assert doc_a.sections[0].title == "Root Topic"
    assert len(doc_a.sections[0].children) == 1
    assert doc_a.sections[0].children[0].title == "Subtopic"

    assert doc_a.blocks[1].text == "Café overview\nline."
    assert doc_a.blocks[3].text.startswith("  def run():")
    assert doc_a.blocks[3].parent_section_id == doc_a.sections[0].children[0].section_id

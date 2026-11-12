"""Unit tests for FileDetector, FileValidator, DocumentChunker, and framework-free ProcessingController."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.exceptions import (
    CorruptedDocumentError,
    DocumentNotFoundError,
    FileTooLargeError,
    StorageError,
    UnsupportedFormatError,
)
from app.extractors import (
    CsvExtractor,
    DocxExtractor,
    ExtractorRegistry,
    MarkdownExtractor,
    PdfExtractor,
    TextExtractor,
)
from app.schemas.common import BlockType, DocumentFormat
from app.schemas.document import ChunkingConfig, DocumentBlock, SectionNode
from app.services import (
    DocumentChunker,
    DocumentNormalizer,
    FileDetector,
    FileValidator,
    ProcessingController,
    UploadStorageService,
)


def _build_controller(tmp_path: Path, max_mb: int = 1) -> ProcessingController:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        environment="test",
        upload_dir=upload_dir,
        max_file_size_mb=max_mb,
        chunk_size=3000,
        chunk_overlap=300,
    )
    registry = ExtractorRegistry()
    registry.register(PdfExtractor())
    registry.register(DocxExtractor())
    registry.register(TextExtractor())
    registry.register(MarkdownExtractor())
    registry.register(CsvExtractor())
    detector = FileDetector()
    validator = FileValidator(
        max_file_size_bytes=settings.max_file_size_bytes,
        detector=detector,
    )
    storage = UploadStorageService(
        upload_dir=settings.upload_dir,
        max_file_size_bytes=settings.max_file_size_bytes,
    )
    normalizer = DocumentNormalizer(
        chunker=DocumentChunker(
            default_config=ChunkingConfig(chunk_size=3000, chunk_overlap=300)
        )
    )
    return ProcessingController(
        settings=settings,
        registry=registry,
        storage=storage,
        normalizer=normalizer,
        detector=detector,
        validator=validator,
    )


def test_file_detector_verifies_magic_bytes_and_rejects_spoofed_files(tmp_path: Path) -> None:
    detector = FileDetector()
    fake_pdf = tmp_path / "spoofed.pdf"
    fake_pdf.write_text("Not actually a PDF", encoding="utf-8")
    with pytest.raises(CorruptedDocumentError):
        detector.detect_and_verify(fake_pdf)

    fake_txt = tmp_path / "malware.txt"
    fake_txt.write_bytes(b"MZ\x90\x00\x03\x00binary")
    with pytest.raises(UnsupportedFormatError):
        detector.detect_and_verify(fake_txt)


def test_file_validator_blocks_path_traversal_and_mime_mismatch(tmp_path: Path) -> None:
    validator = FileValidator(
        max_file_size_bytes=1024,
        allowed_formats={DocumentFormat.TXT, DocumentFormat.MARKDOWN},
    )
    with pytest.raises(StorageError):
        validator.validate_safe_destination(tmp_path / "uploads", tmp_path / "outside.txt")

    with pytest.raises(UnsupportedFormatError):
        validator.validate_incoming_metadata(
            filename="report.pdf",
            content_type="application/pdf",
        )

    with pytest.raises(UnsupportedFormatError):
        validator.validate_incoming_metadata(
            filename="notes.txt",
            content_type="text/csv",
        )

    with pytest.raises(DocumentNotFoundError):
        validator.validate_local_file(tmp_path / "missing.txt")


def test_chunker_preserves_paragraphs_pages_and_handles_large_documents() -> None:
    chunker = DocumentChunker(ChunkingConfig(chunk_size=3000, chunk_overlap=300))
    blocks = [
        DocumentBlock(
            block_id=f"doc12345-blk-{i:04d}",
            type=BlockType.HEADING if i == 0 else BlockType.PARAGRAPH,
            text=("Introduction" if i == 0 else f"Paragraph {i}: " + ("knowledge " * 40)),
            order_index=i,
            level=1 if i == 0 else None,
            page_number=(i // 3) + 1,
            parent_section_id="doc12345-sec-0001",
        )
        for i in range(18)
    ]
    sections = [
        SectionNode(
            section_id="doc12345-sec-0001",
            title="Introduction",
            level=1,
            order_index=0,
            page_number=1,
            block_ids=[b.block_id for b in blocks],
        )
    ]

    chunks = chunker.chunk_document(
        document_id="doc12345-0000-5000-8000-000000000000",
        blocks=blocks,
        sections=sections,
    )
    assert len(chunks) >= 2
    assert all(c.text.strip() for c in chunks)
    assert all(c.char_count <= 3000 for c in chunks)
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    assert chunks[0].section_title == "Introduction"
    assert chunks[0].page_numbers

    # Oversized single paragraph fallback splitting
    oversized_block = [
        DocumentBlock(
            block_id="doc12345-blk-0000",
            type=BlockType.PARAGRAPH,
            text="Sentence one. " * 400,
            order_index=0,
            page_number=4,
        )
    ]
    split_chunks = chunker.chunk_document(
        document_id="doc12345-0000-5000-8000-000000000000",
        blocks=oversized_block,
        sections=[],
        config=ChunkingConfig(chunk_size=500, chunk_overlap=50),
    )
    assert len(split_chunks) > 3
    assert all(c.page_numbers == [4] for c in split_chunks)


def test_processing_controller_works_without_fastapi(
    tmp_path: Path, sample_md_path: Path
) -> None:
    controller = _build_controller(tmp_path)

    # 1. File path invocation (e.g. LangGraph local node)
    file_doc = controller.process_file(sample_md_path)
    assert file_doc.filename == "design.md"
    assert file_doc.document_type == DocumentFormat.MARKDOWN
    assert file_doc.processing_statistics.chunk_count >= 1
    assert file_doc.content

    # 2. In-memory bytes invocation + temp upload cleanup verification
    bytes_doc = controller.process_bytes(
        b"First line\n\nSecond paragraph.",
        filename="langgraph_note.txt",
        content_type="text/plain",
    )
    assert bytes_doc.document_type == DocumentFormat.TXT
    assert list((tmp_path / "uploads").iterdir()) == []

    # 3. Binary stream invocation
    stream_doc = controller.process_stream(
        io.BytesIO(b"col_a,col_b\n1,hello\n"),
        filename="stream.csv",
    )
    assert stream_doc.document_type == DocumentFormat.CSV
    assert stream_doc.tables[0].column_types == {"col_a": "integer", "col_b": "string"}

    # 4. Oversized bytes check
    with pytest.raises(FileTooLargeError):
        controller.process_bytes(
            b"X" * (1024 * 1024 + 5),
            filename="too_big.txt",
        )

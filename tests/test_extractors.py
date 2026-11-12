"""Unit tests for all independent format extractors (PDF, DOCX, TXT, Markdown, CSV)."""

from __future__ import annotations

import codecs
from pathlib import Path

import fitz
import pytest
from docx import Document as DocxBuilder

from app.core.exceptions import (
    CorruptedDocumentError,
    DocumentNotFoundError,
    EmptyDocumentError,
    FileTooLargeError,
    InvalidEncodingError,
    PasswordProtectedDocumentError,
)
from app.extractors import (
    CsvExtractor,
    DocxExtractor,
    ExtractionContext,
    MarkdownExtractor,
    OcrResult,
    PdfExtractor,
    TextExtractor,
)
from app.schemas.common import BlockType, DocumentFormat, OcrStatus


class StubOcrEngine:
    """Deterministic test double implementing the OcrEngine protocol."""

    engine_name = "tesseract"

    def is_available(self) -> bool:
        return True

    def extract_text_from_image_bytes(
        self, image_bytes: bytes, *, language: str = "eng"
    ) -> OcrResult:
        assert len(image_bytes) > 0
        return OcrResult(text=f"OCR extracted text ({language})", engine=self.engine_name)


def test_pdf_extractor_multipage_metadata_and_empty_pages(
    tmp_path: Path, extraction_context: ExtractionContext
) -> None:
    pdf_path = tmp_path / "multipage.pdf"
    pdf = fitz.open()
    page1 = pdf.new_page()
    page1.insert_text((72, 72), "MemoriaOS Overview", fontsize=20)
    page1.insert_text((72, 110), "Deterministic PDF extraction preserves page numbers.", fontsize=11)
    pdf.new_page()  # Page 2 intentionally empty
    pdf.set_metadata({"title": "MultiPage Spec", "author": "Architect", "subject": "RAG"})
    pdf.save(str(pdf_path))
    pdf.close()

    result = PdfExtractor().extract(pdf_path, extraction_context)
    assert result.format == DocumentFormat.PDF
    assert result.page_count == 2
    assert result.title == "MultiPage Spec"
    assert result.author == "Architect"
    assert result.custom_properties["subject"] == "RAG"
    assert len(result.pages) == 2
    assert result.pages[0].page_number == 1
    assert result.pages[0].is_empty is False
    assert result.pages[1].page_number == 2
    assert result.pages[1].is_empty is True
    assert result.ocr_signal.empty_pages == [2]
    assert result.ocr_signal.pages_requiring_ocr == [2]
    assert result.statistics.empty_page_count == 1
    assert any("Page 2 contains no selectable text" in w for w in result.warnings)


def test_pdf_extractor_password_protected_raises(
    tmp_path: Path, extraction_context: ExtractionContext
) -> None:
    locked_path = tmp_path / "locked.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Confidential content")
    pdf.save(
        str(locked_path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )
    pdf.close()

    with pytest.raises(PasswordProtectedDocumentError):
        PdfExtractor().extract(locked_path, extraction_context)


def test_pdf_extractor_flags_scanned_and_invokes_ocr_hook(
    scanned_pdf_path: Path, extraction_context: ExtractionContext
) -> None:
    deferred = PdfExtractor().extract(scanned_pdf_path, extraction_context)
    assert deferred.ocr_signal.status == OcrStatus.DEFERRED_DISABLED
    assert deferred.ocr_signal.pages_requiring_ocr == [1]

    enabled_ctx = ExtractionContext(ocr_enabled=True, pdf_min_text_chars_per_page=20)
    applied = PdfExtractor(ocr_engine=StubOcrEngine()).extract(scanned_pdf_path, enabled_ctx)
    assert applied.ocr_signal.status == OcrStatus.APPLIED
    assert applied.ocr_signal.ocr_applied is True
    assert applied.pages[0].ocr_applied is True
    assert any("OCR extracted text" in b.text for b in applied.blocks)


def test_docx_extractor_preserves_order_styles_tables_and_properties(
    tmp_path: Path, extraction_context: ExtractionContext
) -> None:
    docx_path = tmp_path / "ordered.docx"
    doc = DocxBuilder()
    doc.core_properties.title = "MemoriaOS Brief"
    doc.core_properties.author = "Engineering"
    doc.core_properties.subject = "Architecture"
    doc.core_properties.keywords = "rag,obsidian,qdrant"

    doc.add_heading("Section Alpha", level=1)
    doc.add_paragraph("First paragraph before table.")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Format"
    table.cell(0, 1).text = "Engine"
    table.cell(1, 0).text = "DOCX"
    table.cell(1, 1).text = "python-docx"
    doc.add_paragraph("Trailing paragraph after table.")
    doc.save(str(docx_path))

    result = DocxExtractor().extract(docx_path, extraction_context)
    assert result.format == DocumentFormat.DOCX
    assert result.title == "MemoriaOS Brief"
    assert result.custom_properties["subject"] == "Architecture"
    assert "paragraph_styles" in result.custom_properties

    block_types = [b.type for b in result.blocks]
    assert block_types == [
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.TABLE,
        BlockType.PARAGRAPH,
    ]
    assert result.blocks[1].metadata["style"] == "Normal"
    assert len(result.tables) == 1
    assert result.tables[0].records == [{"Format": "DOCX", "Engine": "python-docx"}]
    assert result.statistics.table_count == 1


def test_text_extractor_bom_fallback_and_invalid_encoding(
    tmp_path: Path, extraction_context: ExtractionContext
) -> None:
    bom_path = tmp_path / "bom.txt"
    bom_path.write_bytes(codecs.BOM_UTF8 + "First line\nSecond line\n\nNext para.".encode("utf-8"))
    bom_result = TextExtractor().extract(bom_path, extraction_context)
    assert bom_result.encoding == "utf-8-sig"
    assert "First line\nSecond line" in bom_result.raw_text
    assert len(bom_result.blocks) == 2

    cp1252_path = tmp_path / "legacy.txt"
    cp1252_path.write_bytes("Smart quote \x93hello\x94".encode("latin-1"))
    cp_result = TextExtractor().extract(cp1252_path, extraction_context)
    assert cp_result.encoding == "cp1252"
    assert len(cp_result.warnings) >= 1

    binary_path = tmp_path / "binary.txt"
    binary_path.write_bytes(b"\x00\x01\x02\xff\xfe\x00binary")
    with pytest.raises(InvalidEncodingError):
        TextExtractor().extract(binary_path, extraction_context)


def test_markdown_extractor_bom_setext_and_structure(
    tmp_path: Path, extraction_context: ExtractionContext
) -> None:
    md_path = tmp_path / "setext.md"
    payload = (
        "Setext Title\n"
        "============\n\n"
        "Line one\nLine two\n\n"
        "## ATX Subheading\n\n"
        "- Bullet A\n"
    )
    md_path.write_bytes(codecs.BOM_UTF8 + payload.encode("utf-8"))
    result = MarkdownExtractor().extract(md_path, extraction_context)
    assert result.format == DocumentFormat.MARKDOWN
    assert result.encoding == "utf-8-sig"
    assert result.title == "Setext Title"
    assert result.blocks[0].type == BlockType.HEADING
    assert result.blocks[0].level == 1
    assert "Line one\nLine two" in result.blocks[1].text


def test_csv_extractor_types_records_limits_and_malformed(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "typed.csv"
    csv_path.write_text(
        "id,score,active,created,note\n"
        "1,98.5,true,2026-01-01,alpha\n"
        "2,87.0,false,2026-01-02,beta\n"
        "3,76.25,true,2026-01-03,gamma\n",
        encoding="utf-8",
    )

    limited_ctx = ExtractionContext(csv_max_rows=2)
    result = CsvExtractor().extract(csv_path, limited_ctx)
    assert result.format == DocumentFormat.CSV
    assert len(result.tables) == 1
    table = result.tables[0]
    assert table.headers == ["id", "score", "active", "created", "note"]
    assert table.column_types == {
        "id": "integer",
        "score": "float",
        "active": "boolean",
        "created": "datetime",
        "note": "string",
    }
    assert len(table.rows) == 2
    assert table.total_row_count == 3
    assert table.truncated is True
    assert result.statistics.records_extracted == 2
    assert result.statistics.truncated is True
    assert any("truncated" in w.lower() for w in result.warnings)

    malformed_path = tmp_path / "malformed.csv"
    malformed_path.write_text("a,b\n1,2,3,4\n5,6\n", encoding="utf-8")
    with pytest.raises(CorruptedDocumentError):
        CsvExtractor().extract(malformed_path, limited_ctx)

    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("   \n", encoding="utf-8")
    with pytest.raises(EmptyDocumentError):
        CsvExtractor().extract(empty_csv, limited_ctx)


def test_base_validation_handles_missing_and_oversized_files(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.txt"
    ctx = ExtractionContext(max_file_size_bytes=16)
    with pytest.raises(DocumentNotFoundError):
        TextExtractor().extract(missing, ctx)

    oversized = tmp_path / "big.txt"
    oversized.write_text("X" * 64, encoding="utf-8")
    with pytest.raises(FileTooLargeError):
        TextExtractor().extract(oversized, ctx)

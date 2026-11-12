"""Comprehensive edge-case and security QA tests for MemoriaOS Document Reader Agent."""

from __future__ import annotations

import asyncio
import codecs
import zipfile
from pathlib import Path

import fitz
import pytest
from docx import Document as DocxBuilder
from fastapi.testclient import TestClient

from app.api.dependencies import get_app_settings, get_processing_controller
from app.core.config import Settings
from app.core.exceptions import (
    CorruptedDocumentError,
    EmptyDocumentError,
    PasswordProtectedDocumentError,
    UnsupportedFormatError,
)
from app.extractors import CsvExtractor, DocxExtractor, ExtractionContext, PdfExtractor
from app.main import create_app
from app.services.file_detector import FileDetector
from app.utils.file_utils import sanitize_filename


def test_empty_documents_across_all_formats(
    tmp_path: Path, client: TestClient, extraction_context: ExtractionContext
) -> None:
    for fname, mime in [
        ("blank.txt", "text/plain"),
        ("blank.md", "text/markdown"),
        ("blank.csv", "text/csv"),
        ("blank.pdf", "application/pdf"),
        (
            "blank.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ]:
        res = client.post(
            "/api/v1/documents/process",
            files={"file": (fname, b"", mime)},
        )
        assert res.status_code == 422
        assert res.json()["error_code"] == "EMPTY_DOCUMENT"

    # Whitespace-only DOCX (valid container, zero text/tables)
    empty_docx = tmp_path / "empty_body.docx"
    doc = DocxBuilder()
    doc.add_paragraph("   ")
    doc.save(str(empty_docx))
    with pytest.raises(EmptyDocumentError):
        DocxExtractor().extract(empty_docx, extraction_context)


def test_corrupted_pdf_and_corrupted_docx(
    tmp_path: Path, client: TestClient
) -> None:
    bad_pdf = client.post(
        "/api/v1/documents/process",
        files={"file": ("corrupt.pdf", b"%PDF-1.7\n%%EOFcorrupted-garbage", "application/pdf")},
    )
    assert bad_pdf.status_code == 422
    assert bad_pdf.json()["error_code"] == "CORRUPTED_DOCUMENT"

    bad_docx = tmp_path / "corrupt.docx"
    bad_docx.write_bytes(b"PK\x03\x04corrupted-zip-data")
    res_docx = client.post(
        "/api/v1/documents/process",
        files={
            "file": (
                "corrupt.docx",
                bad_docx.read_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res_docx.status_code == 422
    assert res_docx.json()["error_code"] == "CORRUPTED_DOCUMENT"


def test_incorrect_file_signatures_rejected(tmp_path: Path) -> None:
    detector = FileDetector()

    # Valid ZIP (e.g. .xlsx disguised as .docx) lacking word/ directory must fail
    spoofed_docx = tmp_path / "fake.docx"
    with zipfile.ZipFile(spoofed_docx, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types></Types>")
        zf.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(CorruptedDocumentError):
        detector.detect_and_verify(spoofed_docx)

    # PNG disguised as .txt must fail
    spoofed_txt = tmp_path / "image.txt"
    spoofed_txt.write_bytes(b"\x89PNG\r\n\x1a\nbinary-png-payload")
    with pytest.raises(UnsupportedFormatError):
        detector.detect_and_verify(spoofed_txt)

    # PDF magic disguised as .md must fail
    spoofed_md = tmp_path / "notes.md"
    spoofed_md.write_bytes(b"%PDF-1.4\nfake")
    with pytest.raises(UnsupportedFormatError):
        detector.detect_and_verify(spoofed_md)


def test_password_protected_pdf_edge_case(
    tmp_path: Path, extraction_context: ExtractionContext
) -> None:
    locked = tmp_path / "encrypted.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Protected payload")
    pdf.save(
        str(locked),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner123",
        user_pw="user123",
    )
    pdf.close()

    with pytest.raises(PasswordProtectedDocumentError):
        PdfExtractor().extract(locked, extraction_context)


def test_very_large_pdf_preserves_all_pages_and_chunks(client: TestClient, tmp_path: Path) -> None:
    large_pdf = tmp_path / "large_120_pages.pdf"
    pdf = fitz.open()
    for page_num in range(1, 121):
        page = pdf.new_page()
        page.insert_text((72, 72), f"Section Page {page_num}", fontsize=16)
        page.insert_text(
            (72, 110),
            f"Deterministic content block on page {page_num} " + ("memoriaos " * 18),
            fontsize=10,
        )
    pdf.save(str(large_pdf))
    pdf.close()

    res = client.post(
        "/api/v1/documents/process?chunk_size=2500&chunk_overlap=250",
        files={"file": ("large_120_pages.pdf", large_pdf.read_bytes(), "application/pdf")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["metadata"]["page_count"] == 120
    assert len(body["pages"]) == 120
    assert body["pages"][0]["page_number"] == 1
    assert body["pages"][-1]["page_number"] == 120
    assert len(body["chunks"]) >= 5
    # Verify page numbers are propagated into chunks
    covered_pages = {p for chunk in body["chunks"] for p in chunk["page_numbers"]}
    assert 1 in covered_pages
    assert 120 in covered_pages


def test_pdf_mixed_scanned_and_selectable_pages(
    client: TestClient, tmp_path: Path
) -> None:
    mixed_pdf = tmp_path / "mixed_scan.pdf"
    pdf = fitz.open()
    p1 = pdf.new_page()
    p1.insert_text((72, 72), "Selectable page one text exceeding threshold chars easily.", fontsize=12)
    pdf.new_page()  # Page 2 has zero text -> scanned/empty
    pdf.save(str(mixed_pdf))
    pdf.close()

    res = client.post(
        "/api/v1/documents/process",
        files={"file": ("mixed_scan.pdf", mixed_pdf.read_bytes(), "application/pdf")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ocr"]["status"] == "deferred_disabled"
    assert body["ocr"]["empty_pages"] == [2]
    assert body["ocr"]["pages_requiring_ocr"] == [2]
    assert body["processing_statistics"]["empty_page_count"] == 1
    assert body["processing_statistics"]["scanned_page_count"] == 1


def test_docx_with_multiple_tables_and_sparse_cells(
    client: TestClient, tmp_path: Path
) -> None:
    docx_path = tmp_path / "tables.docx"
    doc = DocxBuilder()
    doc.add_heading("Financial & Agent Matrix", level=1)
    t1 = doc.add_table(rows=3, cols=3)
    t1.cell(0, 0).text = "Agent"
    t1.cell(0, 1).text = "Format"
    t1.cell(0, 2).text = "Notes"
    t1.cell(1, 0).text = "Agent-01"
    t1.cell(1, 1).text = "DOCX"
    t1.cell(1, 2).text = ""
    t1.cell(2, 0).text = "Agent-02"
    t1.cell(2, 1).text = "PDF"
    t1.cell(2, 2).text = "OCR ready"
    doc.save(str(docx_path))

    res = client.post(
        "/api/v1/documents/process",
        files={
            "file": (
                "tables.docx",
                docx_path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["metadata"]["table_count"] == 1
    assert body["tables"][0]["headers"] == ["Agent", "Format", "Notes"]
    assert body["tables"][0]["row_count"] == 2
    assert body["tables"][0]["records"][0]["Notes"] == ""


def test_csv_missing_values_and_header_only_edge_cases(
    tmp_path: Path, extraction_context: ExtractionContext
) -> None:
    csv_missing = tmp_path / "missing_vals.csv"
    csv_missing.write_text(
        "id,score,flag,note\n"
        "1,10.5,true,alpha\n"
        "2,N/A,null,\n"
        "3,nan,false,none\n",
        encoding="utf-8",
    )
    result = CsvExtractor().extract(csv_missing, extraction_context)
    table = result.tables[0]
    assert table.column_types == {
        "id": "integer",
        "score": "float",
        "flag": "boolean",
        "note": "string",
    }
    assert result.custom_properties["missing_value_counts"] == {
        "id": 0,
        "score": 2,
        "flag": 1,
        "note": 2,
    }

    header_only = tmp_path / "headers_only.csv"
    header_only.write_text("col_a,col_b,col_c\n", encoding="utf-8")
    header_res = CsvExtractor().extract(header_only, extraction_context)
    assert header_res.tables[0].headers == ["col_a", "col_b", "col_c"]
    assert header_res.tables[0].rows == []
    assert any("zero data rows" in w.lower() for w in header_res.warnings)


def test_unicode_normalization_and_utf16_bom(client: TestClient) -> None:
    # Decomposed NFD + CJK + Emoji
    nfd_payload = "Cafe\u0301 \u65e5\u672c\u8a9e \U0001f9e0 MemoriaOS".encode("utf-8")
    res = client.post(
        "/api/v1/documents/process",
        files={"file": ("unicode.txt", nfd_payload, "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert "Café 日本語 🧠 MemoriaOS" in body["content"]

    utf16_payload = codecs.BOM_UTF16_LE + "UTF-16 MemoriaOS Note".encode("utf-16-le")
    res_utf16 = client.post(
        "/api/v1/documents/process",
        files={"file": ("utf16.txt", utf16_payload, "text/plain")},
    )
    assert res_utf16.status_code == 200
    assert res_utf16.json()["metadata"]["encoding"] == "utf-16"


def test_duplicate_filenames_and_filename_sanitization(
    client: TestClient, test_settings: Settings
) -> None:
    res1 = client.post(
        "/api/v1/documents/process",
        files={"file": ("notes.txt", b"Version A content", "text/plain")},
    )
    res2 = client.post(
        "/api/v1/documents/process",
        files={"file": ("notes.txt", b"Version B content", "text/plain")},
    )
    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res1.json()["document_id"] != res2.json()["document_id"]

    # Batch with duplicate filenames must succeed independently
    batch_res = client.post(
        "/api/v1/documents/extract-batch",
        files=[
            ("files", ("dup.txt", b"First duplicate file", "text/plain")),
            ("files", ("dup.txt", b"Second duplicate file", "text/plain")),
        ],
    )
    assert batch_res.status_code == 200
    assert batch_res.json()["succeeded"] == 2
    assert list(test_settings.upload_dir.iterdir()) == []

    # Windows path traversal and >200 char filename extension preservation
    assert sanitize_filename("..\\..\\Windows\\System32\\secret.docx") == "secret.docx"
    long_name = ("a" * 250) + ".markdown"
    sanitized_long = sanitize_filename(long_name)
    assert len(sanitized_long) <= 200
    assert sanitized_long.endswith(".markdown")


def test_request_timeout_returns_408(tmp_path: Path) -> None:
    upload_dir = tmp_path / "timeout_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    short_timeout_settings = Settings(
        environment="test",
        upload_dir=upload_dir,
        request_timeout_seconds=0.1,
    )

    class SlowController:
        async def process_async_chunks(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.35)
            return None

    app = create_app(settings=short_timeout_settings)
    app.dependency_overrides[get_app_settings] = lambda: short_timeout_settings
    app.dependency_overrides[get_processing_controller] = lambda: SlowController()

    with TestClient(app) as client:
        res = client.post(
            "/api/v1/documents/process",
            files={"file": ("slow.txt", b"slow body", "text/plain")},
        )
    assert res.status_code == 408
    assert res.json()["error_code"] == "REQUEST_TIMEOUT"

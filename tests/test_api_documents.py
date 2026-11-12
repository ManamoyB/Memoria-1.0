"""Integration tests for document processing, status tracking, security, and error handling."""

from __future__ import annotations

from pathlib import Path

import fitz
import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings


@pytest.mark.anyio
async def test_process_markdown_async_httpx_and_status_lookup(
    async_client: httpx.AsyncClient,
    sample_md_path: Path,
    test_settings: Settings,
) -> None:
    with sample_md_path.open("rb") as handle:
        response = await async_client.post(
            "/api/v1/documents/process",
            files={"file": ("design.md", handle, "text/markdown")},
        )

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    payload = response.json()
    assert payload["schema_version"] == "1.0.0"
    assert payload["agent"] == "memoria-document-reader"
    assert payload["filename"] == "design.md"
    assert payload["document_type"] == "markdown"
    assert payload["content"]
    assert len(payload["chunks"]) >= 1
    assert payload["processing_statistics"]["chunk_count"] == len(payload["chunks"])
    assert payload["metadata"]["section_count"] >= 2
    assert payload["metadata"]["table_count"] == 1
    # Temp upload must be cleaned up automatically
    assert list(test_settings.upload_dir.iterdir()) == []

    # Verify status tracking endpoint
    status_res = await async_client.get(
        f"/api/v1/documents/{payload['document_id']}/status"
    )
    assert status_res.status_code == 200
    status_body = status_res.json()
    assert status_body["document_id"] == payload["document_id"]
    assert status_body["filename"] == "design.md"
    assert status_body["status"] == "success"


def test_unknown_document_status_returns_404(client: TestClient) -> None:
    res = client.get("/api/v1/documents/00000000-0000-0000-0000-000000000000/status")
    assert res.status_code == 404
    assert res.json()["error_code"] == "DOCUMENT_STATUS_NOT_FOUND"


def test_process_pdf_docx_csv_endpoints(
    client: TestClient,
    sample_pdf_path: Path,
    sample_docx_path: Path,
    sample_csv_path: Path,
) -> None:
    for path, mime, expected_fmt in [
        (sample_pdf_path, "application/pdf", "pdf"),
        (
            sample_docx_path,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
        ),
        (sample_csv_path, "text/csv", "csv"),
    ]:
        with path.open("rb") as handle:
            res = client.post(
                "/api/v1/documents/process",
                files={"file": (path.name, handle, mime)},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["document_type"] == expected_fmt
        assert body["source"]["format"] == expected_fmt


def test_process_with_custom_chunking_params(
    client: TestClient,
) -> None:
    long_text = "\n\n".join(f"Paragraph {i}: " + ("memoria " * 30) for i in range(10))
    res = client.post(
        "/api/v1/documents/process?chunk_size=400&chunk_overlap=50",
        files={"file": ("long.txt", long_text.encode("utf-8"), "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body["chunks"]) >= 3
    assert all(c["char_count"] <= 400 for c in body["chunks"])

    invalid = client.post(
        "/api/v1/documents/process?chunk_size=200&chunk_overlap=250",
        files={"file": ("long.txt", b"hello world", "text/plain")},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "INVALID_CHUNKING_CONFIG"


def test_untrusted_filename_is_sanitized_and_no_local_paths_leaked(
    client: TestClient,
) -> None:
    res = client.post(
        "/api/v1/documents/process",
        files={"file": ("../../etc/passwd.txt", b"safe text body", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert "/" not in body["filename"]
    assert ".." not in body["filename"]
    assert body["filename"] == "passwd.txt"

    # Error responses must never leak internal directory paths
    err_res = client.post(
        "/api/v1/documents/process",
        files={"file": ("../../secret/broken.pdf", b"bad-pdf", "application/pdf")},
    )
    assert err_res.status_code == 422
    err_text = err_res.text
    assert "/tmp/" not in err_text
    assert "storage/uploads" not in err_text


def test_reject_unsupported_format(client: TestClient) -> None:
    response = client.post(
        "/api/v1/documents/process",
        files={"file": ("malware.exe", b"MZ...", "application/octet-stream")},
    )
    assert response.status_code == 415
    body = response.json()
    assert body["status"] == "error"
    assert body["error_code"] == "UNSUPPORTED_DOCUMENT_FORMAT"


def test_reject_empty_file(client: TestClient) -> None:
    response = client.post(
        "/api/v1/documents/process",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "EMPTY_DOCUMENT"


def test_reject_oversized_file(client: TestClient) -> None:
    oversized = b"A" * (1024 * 1024 + 10)
    response = client.post(
        "/api/v1/documents/process",
        files={"file": ("huge.txt", oversized, "text/plain")},
    )
    assert response.status_code == 413
    assert response.json()["error_code"] == "FILE_TOO_LARGE"


def test_reject_corrupted_and_password_protected_pdf(
    client: TestClient, tmp_path: Path
) -> None:
    response = client.post(
        "/api/v1/documents/process",
        files={"file": ("broken.pdf", b"not-a-valid-pdf", "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "CORRUPTED_DOCUMENT"

    locked_pdf = tmp_path / "locked.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Secret")
    pdf.save(
        str(locked_pdf),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="user",
    )
    pdf.close()

    locked_res = client.post(
        "/api/v1/documents/process",
        files={"file": ("locked.pdf", locked_pdf.read_bytes(), "application/pdf")},
    )
    assert locked_res.status_code == 422
    assert locked_res.json()["error_code"] == "PASSWORD_PROTECTED_DOCUMENT"


def test_batch_extraction_isolates_failures(
    client: TestClient,
    sample_txt_path: Path,
) -> None:
    files = [
        ("files", ("notes.txt", sample_txt_path.read_bytes(), "text/plain")),
        ("files", ("bad.bin", b"binary", "application/octet-stream")),
    ]
    response = client.post("/api/v1/documents/extract-batch", files=files)
    assert response.status_code == 200
    body = response.json()
    assert body["total_files"] == 2
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    assert body["results"][0]["status"] == "success"
    assert body["results"][1]["status"] == "failed"
    assert body["results"][1]["error_code"] == "UNSUPPORTED_DOCUMENT_FORMAT"

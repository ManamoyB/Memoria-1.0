"""Tests for root service info, operational health, and supported-formats endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_root_service_info_endpoint(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["agent"] == "memoria-document-reader"
    assert payload["status"] == "running"
    assert payload["docs_url"] == "/docs"
    assert payload["api_prefix"] == "/api/v1"
    assert set(payload["supported_formats"]) == {"pdf", "docx", "txt", "markdown", "csv"}


def test_health_endpoints(client: TestClient) -> None:
    for path in ("/health", "/api/v1/health"):
        response = client.get(path)
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["agent"] == "memoria-document-reader"
        assert payload["ocr_enabled"] is False
        assert payload["ocr_engine"] == "tesseract"
        assert set(payload["supported_formats"]) == {"pdf", "docx", "txt", "markdown", "csv"}


def test_supported_formats_endpoints(client: TestClient) -> None:
    for path in ("/api/v1/documents/supported-formats", "/api/v1/formats"):
        response = client.get(path)
        assert response.status_code == 200
        payload = response.json()
        formats = {item["format"]: item for item in payload["formats"]}
        assert ".pdf" in formats["pdf"]["extensions"]
        assert formats["pdf"]["ocr_fallback_ready"] is True
        assert formats["csv"]["supports_tables"] is True
        assert formats["docx"]["supports_tables"] is True

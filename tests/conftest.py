"""Pytest fixtures for unit and HTTPX integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import fitz
import httpx
import pytest
from docx import Document as DocxBuilder
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_app_settings
from app.core.config import Settings
from app.extractors.base import ExtractionContext
from app.main import create_app


@pytest.fixture()
def test_settings(tmp_path: Path) -> Settings:
    """Provide isolated test Settings pointing upload_dir at a temporary directory."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        environment="test",
        upload_dir=upload_dir,
        max_file_size_mb=1,
        max_batch_files=3,
        cleanup_temp_uploads=True,
        ocr_enabled=False,
        pdf_min_text_chars_per_page=20,
    )


@pytest.fixture()
def extraction_context() -> ExtractionContext:
    """Default ExtractionContext for unit-testing extractors directly."""
    return ExtractionContext(
        default_encoding="utf-8",
        pdf_min_text_chars_per_page=20,
        ocr_enabled=False,
        ocr_engine_name="tesseract",
        tesseract_lang="eng",
    )


@pytest.fixture()
def app_instance(test_settings: Settings) -> FastAPI:
    """Create a FastAPI app with test settings injected via FastAPI dependency overrides."""
    application = create_app(settings=test_settings)
    application.dependency_overrides[get_app_settings] = lambda: test_settings
    return application


@pytest.fixture()
def client(app_instance: FastAPI) -> Iterator[TestClient]:
    """Synchronous FastAPI TestClient."""
    with TestClient(app_instance) as test_client:
        yield test_client


@pytest.fixture()
async def async_client(app_instance: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Asynchronous HTTPX client bound directly to ASGI app."""
    transport = httpx.ASGITransport(app=app_instance)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


@pytest.fixture()
def sample_txt_path(tmp_path: Path) -> Path:
    path = tmp_path / "notes.txt"
    path.write_text(
        "MemoriaOS Architecture Notes\n\nFirst paragraph of raw knowledge.\n\nSecond paragraph.",
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def sample_md_path(tmp_path: Path) -> Path:
    path = tmp_path / "design.md"
    path.write_text(
        """---
title: MemoriaOS Spec
author: Systems Architect
---

# Overview

MemoriaOS separates ingestion from reasoning.

## Pipeline

- Extract raw structure
- Normalize into JSON

```python
print("hello memoria")
```

| Stage | Owner |
| --- | --- |
| Read | Document Reader |
| Index | Qdrant Agent |
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def sample_csv_path(tmp_path: Path) -> Path:
    path = tmp_path / "metrics.csv"
    path.write_text(
        "agent,format,status\ndoc_reader,pdf,ready\ndoc_reader,docx,ready\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def sample_docx_path(tmp_path: Path) -> Path:
    path = tmp_path / "brief.docx"
    doc = DocxBuilder()
    doc.core_properties.title = "MemoriaOS Brief"
    doc.core_properties.author = "Engineering"
    doc.add_heading("Introduction", level=1)
    doc.add_paragraph("Structured document ingestion is foundational for RAG.")
    doc.add_heading("Components", level=2)
    doc.add_paragraph("PyMuPDF handles PDF parsing.", style="List Bullet")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Format"
    table.cell(0, 1).text = "Engine"
    table.cell(1, 0).text = "DOCX"
    table.cell(1, 1).text = "python-docx"
    doc.save(str(path))
    return path


@pytest.fixture()
def sample_pdf_path(tmp_path: Path) -> Path:
    path = tmp_path / "paper.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "MemoriaOS Whitepaper", fontsize=20)
    page.insert_text(
        (72, 110),
        "This document describes deterministic extraction for vector indexing.",
        fontsize=11,
    )
    pdf.set_metadata({"title": "MemoriaOS Whitepaper", "author": "Research Team"})
    pdf.save(str(path))
    pdf.close()
    return path


@pytest.fixture()
def scanned_pdf_path(tmp_path: Path) -> Path:
    """Create a blank-text PDF simulating a scanned image page."""
    path = tmp_path / "scanned.pdf"
    pdf = fitz.open()
    pdf.new_page()
    pdf.save(str(path))
    pdf.close()
    return path

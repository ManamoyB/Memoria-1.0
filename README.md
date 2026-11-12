# MemoriaOS Document Reader Agent

The **Document Reader Agent (`agent-01-document-reader`)** is the first independent ingestion service of **MemoriaOS**—a long-term AI memory system built around document intelligence, knowledge organization, RAG, Obsidian, and Qdrant.

## Scope & Strict Boundaries

This service performs **deterministic ingestion, validation, structural extraction, normalization, and configurable chunking only**:

- **Does**: Accept PDF, DOCX, TXT, Markdown, and CSV documents; verify extensions, MIME types, and magic-byte signatures; extract reading-order blocks, heading hierarchies, tables, column types, and per-page telemetry; normalize text to canonical UTF-8 NFC; chunk content cleanly (default 3,000 chars / 300 overlap); emit standardized `NormalizedDocument` and inter-agent `AgentTaskResponse` JSON; and flag empty/low-text PDF pages for future Tesseract OCR.
- **Does NOT**: Invoke LLMs, perform summarization, semantic classification, knowledge graph generation, embedding generation, Qdrant upserts, or Obsidian vault writes. Those responsibilities belong to downstream MemoriaOS agents (Agents 02–07).
- **Framework-Independent Engine**: `app/services/`, `app/extractors/`, `app/core/`, `app/schemas/`, and `app/utils/` have zero FastAPI/Starlette imports so they can be embedded directly inside LangGraph nodes, background workers, or CLI tools.

---

## Project Structure

```text
app/
├── __init__.py
├── main.py                       # FastAPI factory, lifespan, timeout & CORS middleware
├── api/
│   ├── __init__.py
│   ├── dependencies.py           # Dependency injection providers
│   ├── exception_handlers.py     # Centralized FastAPI ErrorResponse handlers
│   ├── upload_helpers.py         # Shared UploadFile async streaming & chunking query resolver
│   └── routes/
│       ├── __init__.py
│       ├── health.py             # GET /, GET /health, GET /api/v1/health, GET /api/v1/formats
│       ├── documents.py          # GET /supported-formats, POST /process (/extract), /extract-batch, GET /{id}/status
│       └── agent.py              # POST /api/v1/agent/execute (AgentTaskResponse envelope)
├── core/
│   ├── __init__.py
│   ├── config.py                 # Pydantic v2 BaseSettings (PORT + MEMORIA_*)
│   ├── exceptions.py             # Pure-Python domain exception hierarchy
│   └── logging.py                # Structured JSON (staging/prod) & console (dev) logging
├── extractors/
│   ├── __init__.py
│   ├── base.py                   # BaseExtractor ABC, file validation, unified DTOs
│   ├── registry.py               # ExtractorRegistry mapping formats -> engines
│   ├── ocr_engine.py             # OcrEngine protocol & TesseractOcrHook adapter
│   ├── pdf_extractor.py          # PyMuPDF extractor + page telemetry, encryption & scan detection
│   ├── docx_extractor.py         # python-docx extractor preserving reading order, styles & tables
│   ├── text_extractor.py         # Plain-text extractor (UTF-8, UTF-8 BOM, UTF-16, CP1252 fallback)
│   ├── markdown_extractor.py     # Structural Markdown extractor (frontmatter, ATX/Setext, code, tables)
│   └── csv_extractor.py          # Pandas CSV extractor (types, missing values, records & row limits)
├── schemas/
│   ├── __init__.py
│   ├── common.py                 # Enums, ErrorResponse, HealthResponse, DocumentStatusResponse
│   ├── document.py               # NormalizedDocument, DocumentChunk, PageReference, ProcessingStatistics
│   └── agent.py                  # AgentTaskResponse, AgentError, MemoriaAgentId (Agents 01–07)
├── services/
│   ├── __init__.py
│   ├── file_detector.py          # Extension + magic-byte / OOXML ZIP signature verification
│   ├── file_validator.py         # Size limits, MIME checks, allowed formats & path traversal guard
│   ├── chunker.py                # Paragraph-aware DocumentChunker (3000 chars / 300 overlap default)
│   ├── processing_controller.py  # Framework-free central pipeline orchestrator
│   ├── normalizer.py             # Unicode/whitespace normalization & section tree builder
│   ├── status_tracker.py         # Thread-safe bounded in-memory status store
│   ├── storage.py                # Framework-free UploadStorageService with temp cleanup
│   └── agent_service.py          # Reusable DocumentReaderAgentService emitting AgentTaskResponse
└── utils/
    ├── __init__.py
    ├── file_utils.py             # Format detection, filename sanitization, error redaction, SHA-256
    └── text_utils.py             # Safe BOM/fallback byte decoding, NFC normalization, counters
docs/
├── ARCHITECTURE.md               # Architecture, pipeline diagrams, & error matrix
├── AGENT_INTEGRATION.md          # Inter-agent schema, Agents 02–07 routing & LangGraph guide
├── RENDER_DEPLOYMENT.md          # Render deployment & GitHub pre-push checklist
└── TEST_REPORT.md                # Honest QA audit & test execution report
render.yaml                       # Render Blueprint (Python 3.12 + Uvicorn + /health)
requirements.txt                  # Pinned Python 3.12 dependencies
pyproject.toml                    # Package, pytest, ruff, and mypy configuration
storage/
└── uploads/.gitkeep              # Local staging placeholder (ephemeral OS temp used by default)
tests/
├── conftest.py
├── test_agent_contract.py
├── test_api_documents.py
├── test_edge_cases.py
├── test_extractors.py
├── test_health.py
├── test_normalizer.py
└── test_processing_engine.py
```

---

## Requirements

- **Python 3.12+**
- Optional (for future OCR): Tesseract binary (`tesseract-ocr`) + `pytesseract` + `Pillow`

---

## Installation & Local Execution

1. **Create and activate a Python 3.12 virtual environment**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

2. **Install dependencies**

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

3. **Configure environment variables**

```bash
cp .env.example .env
```

4. **Run the FastAPI service with Uvicorn**

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive Swagger UI is served at `http://localhost:8000/docs`.

5. **Run the Pytest suite**

```bash
pytest
```

---

## Key Endpoints

- `GET /` — Service identity, version, status, and docs link
- `GET /health` (and `GET /api/v1/health`) — Liveness & OCR readiness check
- `GET /api/v1/documents/supported-formats` (and `GET /api/v1/formats`) — Supported formats & capabilities
- `POST /api/v1/documents/process` (and `/extract` alias) — Upload, extract, normalize, and chunk a document
- `POST /api/v1/documents/extract-batch` — Process multiple documents with per-file error isolation
- `GET /api/v1/documents/{document_id}/status` — Inspect tracked processing status
- `POST /api/v1/agent/execute` — Execute as MemoriaOS Agent 01 and emit `AgentTaskResponse`

---

## Documentation Index

- [Architecture Specification](docs/ARCHITECTURE.md)
- [Inter-Agent & LangGraph Integration](docs/AGENT_INTEGRATION.md)
- [Render Deployment Guide](docs/RENDER_DEPLOYMENT.md)
- [QA Audit & Test Report](docs/TEST_REPORT.md)

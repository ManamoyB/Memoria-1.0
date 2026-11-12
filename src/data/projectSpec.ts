import type { DocumentFormat } from '../utils/documentNormalizer';

export interface ExtractorSpec {
  format: DocumentFormat;
  label: string;
  extensions: string[];
  engine: string;
  modulePath: string;
  preservesStructure: string;
  tables: boolean;
  ocrReady: boolean;
}

export const EXTRACTOR_SPECS: ExtractorSpec[] = [
  {
    format: 'pdf',
    label: 'PDF',
    extensions: ['.pdf'],
    engine: 'PyMuPDF (fitz)',
    modulePath: 'app/extractors/pdf_extractor.py',
    preservesStructure: 'Pages, font-size heading heuristics, reading-order blocks & scan telemetry',
    tables: false,
    ocrReady: true,
  },
  {
    format: 'docx',
    label: 'DOCX',
    extensions: ['.docx'],
    engine: 'python-docx',
    modulePath: 'app/extractors/docx_extractor.py',
    preservesStructure: 'XML body order: headings, styles, lists, quotes, tables & core props',
    tables: true,
    ocrReady: false,
  },
  {
    format: 'txt',
    label: 'TXT',
    extensions: ['.txt', '.text'],
    engine: 'TextExtractor (stdlib)',
    modulePath: 'app/extractors/text_extractor.py',
    preservesStructure: 'Paragraph segmentation with UTF-8, UTF-8 BOM, UTF-16 & CP1252 fallback',
    tables: false,
    ocrReady: false,
  },
  {
    format: 'markdown',
    label: 'Markdown',
    extensions: ['.md', '.markdown'],
    engine: 'MarkdownExtractor',
    modulePath: 'app/extractors/markdown_extractor.py',
    preservesStructure: 'YAML frontmatter, ATX/Setext H1–H6, lists, fenced code, quotes, tables',
    tables: true,
    ocrReady: false,
  },
  {
    format: 'csv',
    label: 'CSV',
    extensions: ['.csv'],
    engine: 'Pandas (read_csv)',
    modulePath: 'app/extractors/csv_extractor.py',
    preservesStructure: 'Delimiter sniffing, column types, missing-value counts, records & row limits',
    tables: true,
    ocrReady: false,
  },
];

export const REPOSITORY_TREE = `app/
├── __init__.py
├── main.py                       # FastAPI factory, lifespan, timeout & CORS middleware
├── api/
│   ├── __init__.py
│   ├── dependencies.py           # DI providers (Settings, Registry, Storage, Controller, Agent)
│   ├── exception_handlers.py     # Centralized FastAPI ErrorResponse handlers
│   ├── upload_helpers.py         # Shared UploadFile async streaming & chunking resolver
│   └── routes/
│       ├── __init__.py
│       ├── health.py             # GET /, GET /health, GET /api/v1/health, GET /api/v1/formats
│       ├── documents.py          # GET /supported-formats, POST /process, /extract-batch, /{id}/status
│       └── agent.py              # POST /api/v1/agent/execute (AgentTaskResponse envelope)
├── core/
│   ├── __init__.py
│   ├── config.py                 # Pydantic v2 BaseSettings (PORT + MEMORIA_*)
│   ├── exceptions.py             # Pure-Python domain exception hierarchy
│   └── logging.py                # Structured JSON (prod) & console (dev) logging
├── extractors/
│   ├── __init__.py
│   ├── base.py                   # BaseExtractor ABC, file validation, unified DTOs
│   ├── registry.py               # ExtractorRegistry decoupling formats from engines
│   ├── ocr_engine.py             # OcrEngine Protocol & TesseractOcrHook adapter
│   ├── pdf_extractor.py          # PyMuPDF extractor + encryption & scan detection
│   ├── docx_extractor.py         # python-docx reading-order & table extractor
│   ├── text_extractor.py         # Plain text extractor with BOM/fallback decoding
│   ├── markdown_extractor.py     # Structural Markdown (ATX/Setext/frontmatter/tables)
│   └── csv_extractor.py          # Pandas CSV extractor (types, records & row limits)
├── schemas/
│   ├── __init__.py
│   ├── common.py                 # DocumentFormat, ErrorResponse, HealthResponse, DocumentStatusResponse
│   ├── document.py               # NormalizedDocument, DocumentChunk, PageReference, Statistics
│   └── agent.py                  # AgentTaskResponse, AgentError, MemoriaAgentId (Agents 01–07)
├── services/
│   ├── __init__.py
│   ├── file_detector.py          # Extension + magic-byte / OOXML ZIP verification
│   ├── file_validator.py         # Size limits, MIME checks, allowed formats & traversal guard
│   ├── chunker.py                # Paragraph-aware DocumentChunker (3000 chars / 300 overlap)
│   ├── processing_controller.py  # Framework-free central pipeline orchestrator
│   ├── normalizer.py             # Unicode NFC, whitespace, section tree & IDs
│   ├── status_tracker.py         # Bounded thread-safe in-memory status store
│   ├── storage.py                # Framework-free UploadStorageService + temp cleanup
│   └── agent_service.py          # Reusable DocumentReaderAgentService (LangGraph-ready)
└── utils/
    ├── __init__.py
    ├── file_utils.py             # Format detection, filename sanitization, error redaction, SHA-256
    └── text_utils.py             # Safe BOM/fallback decoding, NFC normalization, counters
docs/
├── ARCHITECTURE.md
├── AGENT_INTEGRATION.md
├── RENDER_DEPLOYMENT.md
└── TEST_REPORT.md
render.yaml                       # Render Blueprint (Python 3.12 + Uvicorn + /health)
tests/
├── conftest.py
├── test_agent_contract.py
├── test_api_documents.py
├── test_edge_cases.py
├── test_extractors.py
├── test_health.py
├── test_normalizer.py
└── test_processing_engine.py`;

export interface SamplePreset {
  id: string;
  label: string;
  filename: string;
  format: DocumentFormat;
  pageCount?: number;
  ocrPages?: number[];
  content: string;
}

export const SAMPLE_PRESETS: SamplePreset[] = [
  {
    id: 'markdown',
    label: 'Markdown Spec',
    filename: 'memoria_ingest_spec.md',
    format: 'markdown',
    content: `---
title: MemoriaOS Ingestion Specification
author: Systems Architecture
---

# Overview

MemoriaOS separates raw document ingestion from downstream semantic indexing and Obsidian note generation.

## Pipeline Stages

- Validate file extension, MIME type, and magic-byte signatures
- Dispatch to an independent format extractor
- Normalize Unicode to NFC, build section tree, and chunk (3000 chars / 300 overlap)

\`\`\`python
from app.services.agent_service import DocumentReaderAgentService
\`\`\`

| Component | Downstream Consumer |
| --- | --- |
| DocumentChunk[] | Agent 02 · Context Understanding & Qdrant |
| SectionNode[] | Agent 05 · Knowledge Graph |
| DocumentMetadata | Agent 04 · Knowledge Writer (Obsidian) |`,
  },
  {
    id: 'csv',
    label: 'CSV Telemetry',
    filename: 'agent_benchmarks.csv',
    format: 'csv',
    content: `agent_id,format,extractor,tables_supported
1,pdf,pymupdf_pdf_extractor,false
2,docx,python_docx_extractor,true
3,markdown,markdown_structural_extractor,true
4,csv,pandas_csv_extractor,true`,
  },
  {
    id: 'txt',
    label: 'Plain Text Notes',
    filename: 'research_excerpt.txt',
    format: 'txt',
    content: `MemoriaOS Architecture Journal

Each agent inside MemoriaOS maintains strict responsibility boundaries. The Document Reader Agent never calls an LLM or writes to Obsidian directly.

Instead, it emits deterministic NormalizedDocument and AgentTaskResponse payloads keyed by a SHA-256 derived UUIDv5 so downstream RAG and Qdrant pipelines stay idempotent.`,
  },
  {
    id: 'pdf-ocr',
    label: 'PDF + Scanned Page Signal',
    filename: 'whitepaper_scan.pdf',
    format: 'pdf',
    pageCount: 2,
    ocrPages: [2],
    content: `# MemoriaOS Paper (Page 1 Selectable Text)

Deterministic structural extraction preserves reading order and page numbers for downstream vector chunking.

## Page Density & OCR Hook

Page 2 of this simulated PDF fell below MEMORIA_PDF_MIN_TEXT_CHARS_PER_PAGE (40 chars), so PdfExtractor flagged page 2 in ocr.pages_requiring_ocr for future Tesseract processing.`,
  },
];

export const API_ENDPOINTS = [
  {
    method: 'GET',
    path: '/',
    summary: 'Service identity, version, operational status, API prefix, and docs URL.',
    responseSchema: 'ServiceInfoResponse',
  },
  {
    method: 'GET',
    path: '/health',
    summary: 'Render liveness check, OCR engine readiness, and active formats.',
    responseSchema: 'HealthResponse',
  },
  {
    method: 'GET',
    path: '/api/v1/documents/supported-formats',
    summary: 'Lists registered extractors, extensions, MIME types, and table/OCR capabilities.',
    responseSchema: 'SupportedFormatsResponse',
  },
  {
    method: 'POST',
    path: '/api/v1/documents/process',
    summary: 'Accepts multipart UploadFile, runs ProcessingController, cleans temp files, returns JSON.',
    responseSchema: 'NormalizedDocument',
  },
  {
    method: 'POST',
    path: '/api/v1/documents/extract-batch',
    summary: 'Processes up to MEMORIA_MAX_BATCH_FILES documents with per-file error isolation.',
    responseSchema: 'BatchExtractionResponse',
  },
  {
    method: 'GET',
    path: '/api/v1/documents/{document_id}/status',
    summary: 'Retrieves tracked processing status, counts, and warnings for a document ID.',
    responseSchema: 'DocumentStatusResponse',
  },
  {
    method: 'POST',
    path: '/api/v1/agent/execute',
    summary: 'Executes DocumentReaderAgentService and emits standardized inter-agent envelope.',
    responseSchema: 'AgentTaskResponse',
  },
];

export const ERROR_MATRIX = [
  { http: '400', code: 'EMPTY_BATCH_REQUEST / BATCH_LIMIT_EXCEEDED', trigger: 'Empty batch or exceeds MEMORIA_MAX_BATCH_FILES' },
  { http: '404', code: 'DOCUMENT_STATUS_NOT_FOUND', trigger: 'No tracked status record for supplied document_id' },
  { http: '408', code: 'REQUEST_TIMEOUT', trigger: 'Processing exceeded MEMORIA_REQUEST_TIMEOUT_SECONDS' },
  { http: '413', code: 'FILE_TOO_LARGE', trigger: 'Streaming upload exceeds MEMORIA_MAX_FILE_SIZE_MB' },
  { http: '415', code: 'UNSUPPORTED_DOCUMENT_FORMAT', trigger: 'Extension/MIME unregistered or binary signature mismatch' },
  { http: '422', code: 'EMPTY_DOCUMENT / CORRUPTED_DOCUMENT', trigger: '0-byte upload, malformed PDF/DOCX/CSV, or failed ZIP OOXML check' },
  { http: '422', code: 'PASSWORD_PROTECTED_DOCUMENT / INVALID_ENCODING', trigger: 'Encrypted PDF or binary/undecodable byte stream' },
  { http: '501', code: 'OCR_NOT_CONFIGURED', trigger: 'OCR invoked when Tesseract binary or pytesseract is absent' },
];

export const AGENT_TARGETS = [
  { id: 'agent-01-document-reader', role: 'Document Reader Agent', note: 'Current service: extracts, normalizes, and chunks documents' },
  { id: 'agent-02-context-understanding', role: 'Context Understanding Agent', note: 'Default next_agent on successful extraction' },
  { id: 'agent-03-knowledge-classification', role: 'Knowledge Classification Agent', note: 'Selectable downstream classification target' },
  { id: 'agent-04-knowledge-writer', role: 'Knowledge Writer Agent', note: 'Obsidian & Qdrant persistence target' },
  { id: 'agent-05-knowledge-graph', role: 'Knowledge Graph Agent', note: 'Consumes SectionNode tree & source provenance' },
  { id: 'agent-06-quality-validation', role: 'Quality Validation Agent', note: 'Audits completeness & OCR readiness signals' },
  { id: 'agent-07-orchestrator', role: 'Orchestrator', note: 'Propagates task_id & handles failed/escalated tasks' },
];

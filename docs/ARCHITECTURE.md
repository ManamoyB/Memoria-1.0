# MemoriaOS Document Reader Agent — Architecture Documentation

## 1. Role in MemoriaOS

MemoriaOS separates document intelligence into composable, single-responsibility agents:

1. **Agent 01 — Document Reader Agent (this service)**: Deterministic multi-format ingestion, validation, structural extraction, normalization, and configurable chunking.
2. **Agent 02 — Context Understanding Agent**: Default downstream target (`next_agent`) consuming `NormalizedDocument` chunks and sections.
3. **Agent 03 — Knowledge Classification Agent**: Categorizes normalized documents and chunks.
4. **Agent 04 — Knowledge Writer Agent**: Formats and writes Obsidian notes and Qdrant payloads.
5. **Agent 05 — Knowledge Graph Agent**: Builds entity/section relationships from `sections`, `blocks`, and `source` provenance.
6. **Agent 06 — Quality Validation Agent**: Audits downstream outputs and extraction `ocr` diagnostics.
7. **Agent 07 — Orchestrator**: Coordinates `task_id` propagation and receives failed/escalated tasks.

---

## 2. Layered Module Architecture

```text
HTTP Request (FastAPI)               LangGraph / Python Caller / Worker
   │                                    │
   ▼                                    ▼
app/api/routes/*.py                  app/services/agent_service.py (DocumentReaderAgentService)
   │  async byte chunks                 │  Path / bytes / async stream
   └──────────────────┬─────────────────┘
                      ▼
app/services/processing_controller.py      [Framework-free central orchestrator]
   ├──► app/services/file_validator.py     [Size limits, allowed types, MIME, path safety]
   ├──► app/services/storage.py            [Safe temp staging & guaranteed cleanup]
   ├──► app/services/file_detector.py      [Extension + magic-byte / OOXML signature verification]
   ├──► app/extractors/registry.py         [Format -> independent extractor lookup]
   │       ├── PdfExtractor                (PyMuPDF + encryption, scan & empty-page detection)
   │       ├── DocxExtractor               (python-docx order, styles, tables & core props)
   │       ├── TextExtractor               (UTF-8, UTF-8 BOM, UTF-16, CP1252 fallback)
   │       ├── MarkdownExtractor           (Frontmatter, ATX/Setext, code, tables)
   │       └── CsvExtractor                (Pandas types, missing values, records, row limits)
   ├──► app/services/normalizer.py         [NFC Unicode, section tree, PageReference, stats]
   ├──► app/services/chunker.py            [Paragraph-aware chunking: 3000 chars / 300 overlap]
   └──► app/services/status_tracker.py     [Thread-safe bounded status cache]
```

### Key Architectural Invariants

1. **Zero FastAPI Coupling in Core/Engine Layers**: `app/core/`, `app/schemas/`, `app/utils/`, `app/extractors/`, and `app/services/` contain zero `fastapi` or `starlette` imports. Web exception handlers and upload adapters live strictly inside `app/api/`.
2. **Independent Extraction Engines**: Extractors implement `BaseExtractor`, never import each other, never call LLMs, and return a unified `ExtractedContent` DTO with `format`, `raw_text`, `blocks`, `tables`, `pages`, `statistics`, and `warnings`.
3. **Magic-Byte & Security Guardrails**: `FileValidator` and `FileDetector` enforce size limits, allowed format lists, MIME compatibility, magic-byte signatures (`%PDF-`, ZIP `[Content_Types].xml` + `word/` for DOCX, binary/NUL rejection for text formats), sanitized filenames, path traversal bounds, and exception-reason path redaction.
4. **Configurable Paragraph-Aware Chunking**: `DocumentChunker` defaults to `chunk_size=3000` and `chunk_overlap=300`, preserves paragraph boundaries and page numbers, links `block_ids` and `section_id`/`section_title`, and never emits empty chunks.
5. **Centralized Error Handling**: `app/api/exception_handlers.py` maps domain exceptions into standardized `ErrorResponse` JSON payloads tagged with `X-Request-ID`.

---

## 3. Standardized Output Contract (`NormalizedDocument`)

Top-level fields returned by `ProcessingController` and `POST /api/v1/documents/process`:

- `schema_version` (`"1.0.0"`) & `agent` (`"memoria-document-reader"`)
- `document_id`: Deterministic UUIDv5 derived from `sha256` content hash
- `filename`: Sanitized original filename
- `document_type`: Canonical `DocumentFormat` (`pdf | docx | txt | markdown | csv`)
- `status`: `success | partial | failed`
- `ingested_at`: UTC ISO-8601 timestamp
- `source`: Provenance (`filename`, `extension`, `format`, `mime_type`, `byte_size`, `content_hash`, `ingested_at`)
- `metadata`: Descriptive & format-native metadata (`title`, `author`, `page_count`, `block_count`, `section_count`, `table_count`, `chunk_count`, `word_count`, `char_count`, `line_count`, `encoding`, `extractor_name`, `custom_properties`)
- `content`: Canonical UTF-8 NFC normalized text in reading order
- `blocks`, `sections`, `tables`, `pages`, `chunks`
- `ocr`: `OcrMetadata` (`status`, `pages_requiring_ocr`, `empty_pages`, `notes`)
- `processing_statistics`: `ProcessingStatistics` (extraction/normalization/chunking/total ms, counts, empty/scanned pages, `records_extracted`, `truncated`)
- `extraction_warnings`: Non-fatal warnings recorded during extraction or truncation

---

## 4. Error Code Matrix

| HTTP Status | `error_code` | Trigger |
| --- | --- | --- |
| `400` | `EMPTY_BATCH_REQUEST` / `BATCH_LIMIT_EXCEEDED` | Invalid batch file count |
| `404` | `DOCUMENT_FILE_NOT_FOUND` / `DOCUMENT_STATUS_NOT_FOUND` | Missing local file or unknown document status ID |
| `408` | `REQUEST_TIMEOUT` | Processing exceeded `MEMORIA_REQUEST_TIMEOUT_SECONDS` |
| `413` | `FILE_TOO_LARGE` | Payload exceeds `MEMORIA_MAX_FILE_SIZE_MB` |
| `415` | `UNSUPPORTED_DOCUMENT_FORMAT` | Unregistered format, disabled type, or MIME/binary mismatch |
| `422` | `EMPTY_DOCUMENT` | 0-byte upload or zero extractable content |
| `422` | `CORRUPTED_DOCUMENT` | Malformed PDF/DOCX/CSV or failed signature check |
| `422` | `PASSWORD_PROTECTED_DOCUMENT` | Encrypted PDF requiring a password |
| `422` | `INVALID_ENCODING` | Binary/undecodable text encoding |
| `422` | `INVALID_CHUNKING_CONFIG` | `chunk_overlap >= chunk_size` |
| `501` | `OCR_NOT_CONFIGURED` | Explicit OCR call without Tesseract installed |

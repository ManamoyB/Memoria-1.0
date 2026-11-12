# MemoriaOS Inter-Agent Communication & Integration Guide

The **Document Reader Agent (`agent-01-document-reader`)** is designed to be both an independent FastAPI microservice and an importable Python service (`DocumentReaderAgentService` + `ProcessingController`) with zero dependency on Redis, A2A, or LangGraph packages at this stage.

---

## 1. Future MemoriaOS Integration Targets (`MemoriaAgentId`)

Defined in `app/schemas/agent.py`:

| Agent ID | Role | Relationship to Agent 01 |
| --- | --- | --- |
| `agent-01-document-reader` | **Document Reader Agent** (this service) | Produces standardized `NormalizedDocument` + `AgentTaskResponse` |
| `agent-02-context-understanding` | Context Understanding Agent | Default `next_agent` on successful document extraction |
| `agent-03-knowledge-classification` | Knowledge Classification Agent | Optional target via `next_agent` override |
| `agent-04-knowledge-writer` | Knowledge Writer Agent | Consumes normalized content/sections downstream for Obsidian/Qdrant |
| `agent-05-knowledge-graph` | Knowledge Graph Agent | Consumes `sections`, `blocks`, and `source` provenance |
| `agent-06-quality-validation` | Quality Validation Agent | Audits extraction completeness and `ocr` diagnostics |
| `agent-07-orchestrator` | Orchestrator | Invokes Agent 01, propagates `task_id`, receives failed/escalated tasks (`next_agent`) |

---

## 2. Standardized Inter-Agent Envelope (`AgentTaskResponse`)

Every completed or failed agent invocation emits `AgentTaskResponse` (`app/schemas/agent.py`):

- `task_id`: Unique UUIDv4 (or upstream Orchestrator `task_id` propagated verbatim).
- `agent_id`: `"agent-01-document-reader"`.
- `document_id`: Deterministic UUIDv5 derived from SHA-256 content hash (`null` if failed before hashing).
- `status`: `"success" | "partial" | "failed"`.
- `output_type`: `"normalized_document"`.
- `output`: Complete `NormalizedDocument` payload (with `source`, `metadata`, `content`, `blocks`, `sections`, `tables`, `pages`, `chunks`, `ocr`, `processing_statistics`, `extraction_warnings`).
- `errors`: List of `AgentError` entries (`error_code`, `message`, `details`, `recoverable`).
- `metadata`: Compact routing summary (`source_filename`, `document_type`, `content_hash`, `byte_size`, `chunk_count`, `block_count`, `page_count`, `processing_time_ms`, `ocr_status`).
- `next_agent`: Recommended downstream target (`"agent-02-context-understanding"` on success, or `"agent-07-orchestrator"` on failure).
- `timestamp`: UTC ISO-8601 timestamp.

---

## 3. Calling from Another Python Application (No FastAPI Required)

```python
from pathlib import Path
from app.core.config import get_settings
from app.extractors import (
    CsvExtractor,
    DocxExtractor,
    ExtractorRegistry,
    MarkdownExtractor,
    PdfExtractor,
    TextExtractor,
)
from app.services import (
    DocumentChunker,
    DocumentNormalizer,
    DocumentReaderAgentService,
    FileDetector,
    FileValidator,
    ProcessingController,
    UploadStorageService,
)

settings = get_settings()
registry = ExtractorRegistry()
for extractor in (
    PdfExtractor(),
    DocxExtractor(),
    TextExtractor(),
    MarkdownExtractor(),
    CsvExtractor(),
):
    registry.register(extractor)

detector = FileDetector()
controller = ProcessingController(
    settings=settings,
    registry=registry,
    storage=UploadStorageService(settings.upload_dir, settings.max_file_size_bytes),
    normalizer=DocumentNormalizer(DocumentChunker()),
    detector=detector,
    validator=FileValidator(max_file_size_bytes=settings.max_file_size_bytes, detector=detector),
)
agent_service = DocumentReaderAgentService(controller=controller)

response = agent_service.execute_file(
    Path("architecture_notes.md"),
    task_id="orch-task-42",
)
print(response.model_dump_json(indent=2))
```

---

## 4. Future LangGraph Node Pattern (Zero Coupling Today)

Because `DocumentReaderAgentService` and `ProcessingController` have zero FastAPI, Redis, or LangGraph imports, wrapping Agent 01 inside a LangGraph graph node later requires only a lightweight adapter:

```python
from pathlib import Path
from typing import Any, TypedDict


class MemoriaGraphState(TypedDict, total=False):
    task_id: str
    file_path: str
    agent_response: dict[str, Any]
    next_agent: str | None


def document_reader_node(
    state: MemoriaGraphState,
    *,
    agent_service,  # DocumentReaderAgentService
) -> MemoriaGraphState:
    envelope = agent_service.execute_file(
        Path(state["file_path"]),
        task_id=state.get("task_id"),
    )
    return {
        "task_id": envelope.task_id,
        "agent_response": envelope.model_dump(mode="json"),
        "next_agent": envelope.next_agent,
    }
```

---

## 5. HTTP Inter-Agent Contract (`POST /api/v1/agent/execute`)

### Example Request

```bash
curl -sS -X POST \
  "http://localhost:8000/api/v1/agent/execute?task_id=task-orch-101&next_agent=agent-02-context-understanding" \
  -F "file=@architecture_notes.md"
```

### Example Success Response

```json
{
  "task_id": "task-orch-101",
  "agent_id": "agent-01-document-reader",
  "document_id": "21396d7a-d006-5da4-8139-6d7ad006fda4",
  "status": "success",
  "output_type": "normalized_document",
  "output": {
    "schema_version": "1.0.0",
    "agent": "memoria-document-reader",
    "document_id": "21396d7a-d006-5da4-8139-6d7ad006fda4",
    "filename": "architecture_notes.md",
    "document_type": "markdown",
    "status": "success",
    "content": "# MemoriaOS Architecture\n\nDeterministic extraction and normalization.",
    "chunks": [
      {
        "chunk_id": "9f38b9ef-6df2-5c4d-a1bc-2d232b00e101",
        "document_id": "21396d7a-d006-5da4-8139-6d7ad006fda4",
        "chunk_index": 0,
        "text": "# MemoriaOS Architecture\n\nDeterministic extraction and normalization.",
        "char_count": 70,
        "word_count": 8,
        "start_char": 0,
        "end_char": 70,
        "page_numbers": [],
        "block_ids": ["21396d7a-blk-0000", "21396d7a-blk-0001"],
        "section_id": "21396d7a-sec-0001",
        "section_title": "MemoriaOS Architecture"
      }
    ]
  },
  "errors": [],
  "metadata": {
    "source_filename": "architecture_notes.md",
    "document_type": "markdown",
    "content_hash": "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "byte_size": 70,
    "chunk_count": 1,
    "block_count": 2,
    "page_count": null,
    "processing_time_ms": 1.85,
    "ocr_status": "not_needed"
  },
  "next_agent": "agent-02-context-understanding",
  "timestamp": "2026-11-12T23:10:00Z"
}
```

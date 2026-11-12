"""Unit and integration tests for MemoriaOS inter-agent communication contract."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.extractors import (
    CsvExtractor,
    DocxExtractor,
    ExtractorRegistry,
    MarkdownExtractor,
    PdfExtractor,
    TextExtractor,
)
from app.schemas.agent import MemoriaAgentId
from app.schemas.common import ExtractionStatus
from app.services import (
    DocumentChunker,
    DocumentNormalizer,
    DocumentReaderAgentService,
    FileDetector,
    FileValidator,
    ProcessingController,
    UploadStorageService,
)


def _build_agent_service(tmp_path: Path) -> DocumentReaderAgentService:
    upload_dir = tmp_path / "agent_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(environment="test", upload_dir=upload_dir, max_file_size_mb=2)
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
    normalizer = DocumentNormalizer(chunker=DocumentChunker())
    controller = ProcessingController(
        settings=settings,
        registry=registry,
        storage=storage,
        normalizer=normalizer,
        detector=detector,
        validator=validator,
    )
    return DocumentReaderAgentService(controller=controller)


def test_agent_service_execute_bytes_and_file_contract(
    tmp_path: Path, sample_md_path: Path
) -> None:
    agent = _build_agent_service(tmp_path)

    res_bytes = agent.execute_bytes(
        b"# Memory Entry\n\nAgent 01 produces normalized JSON.",
        filename="entry.md",
        task_id="task-orch-001",
    )
    assert res_bytes.task_id == "task-orch-001"
    assert res_bytes.agent_id == MemoriaAgentId.DOCUMENT_READER.value
    assert res_bytes.status == ExtractionStatus.SUCCESS
    assert res_bytes.output_type == "normalized_document"
    assert res_bytes.document_id is not None
    assert res_bytes.output is not None
    assert res_bytes.output.document_id == res_bytes.document_id
    assert res_bytes.errors == []
    assert res_bytes.next_agent == MemoriaAgentId.CONTEXT_UNDERSTANDING.value
    assert res_bytes.metadata["source_filename"] == "entry.md"
    assert res_bytes.metadata["chunk_count"] >= 1

    res_file = agent.execute_file(
        sample_md_path,
        next_agent=MemoriaAgentId.KNOWLEDGE_CLASSIFICATION.value,
    )
    assert res_file.task_id
    assert res_file.task_id != res_bytes.task_id
    assert res_file.next_agent == MemoriaAgentId.KNOWLEDGE_CLASSIFICATION.value
    assert res_file.status == ExtractionStatus.SUCCESS


def test_agent_service_routes_failures_to_orchestrator(tmp_path: Path) -> None:
    agent = _build_agent_service(tmp_path)

    # Non-recoverable error (unsupported format)
    err_res = agent.execute_bytes(
        b"MZ\x90\x00binary",
        filename="binary.exe",
        task_id="task-err-001",
    )
    assert err_res.task_id == "task-err-001"
    assert err_res.status == ExtractionStatus.FAILED
    assert err_res.document_id is None
    assert err_res.output is None
    assert len(err_res.errors) == 1
    assert err_res.errors[0].error_code == "UNSUPPORTED_DOCUMENT_FORMAT"
    assert err_res.errors[0].recoverable is False
    assert err_res.next_agent == MemoriaAgentId.ORCHESTRATOR.value


def test_agent_execute_http_endpoint(client: TestClient) -> None:
    res = client.post(
        "/api/v1/agent/execute?task_id=orch-999&next_agent=agent-03-knowledge-classification",
        files={"file": ("note.txt", b"Structured memory payload.", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["task_id"] == "orch-999"
    assert body["agent_id"] == "agent-01-document-reader"
    assert body["status"] == "success"
    assert body["output_type"] == "normalized_document"
    assert body["document_id"] == body["output"]["document_id"]
    assert body["errors"] == []
    assert body["next_agent"] == "agent-03-knowledge-classification"
    assert body["metadata"]["source_filename"] == "note.txt"

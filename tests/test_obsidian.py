from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.obsidian.config import ObsidianConfig
from app.obsidian.markdown import MarkdownNoteBuilder
from app.obsidian.writer import ObsidianWriter
from app.schemas.document import NormalizedDocument


def sample_document() -> NormalizedDocument:
    return NormalizedDocument.model_validate(
        {
            "document_id": "doc-test-001",
            "filename": "Research Paper.pdf",
            "document_type": "pdf",
            "source": {
                "filename": "Research Paper.pdf",
                "extension": ".pdf",
                "format": "pdf",
                "mime_type": "application/pdf",
                "byte_size": 1024,
                "content_hash": "sha256:0123456789abcdef0123456789abcdef",
            },
            "metadata": {
                "title": "Research: A Test",
                "author": "Memoria Tester",
                "page_count": 2,
                "block_count": 2,
                "section_count": 1,
                "table_count": 1,
                "chunk_count": 1,
                "word_count": 5,
                "char_count": 25,
                "line_count": 2,
                "extractor_name": "PdfExtractor",
            },
            "content": "# Introduction\n\nOriginal extracted text.\n",
            "sections": [
                {
                    "section_id": "sec-1",
                    "title": "Introduction",
                    "level": 1,
                    "order_index": 0,
                    "block_ids": [],
                    "children": [],
                }
            ],
            "tables": [
                {
                    "table_id": "table-1",
                    "name": "Results",
                    "headers": ["Metric", "Value"],
                    "rows": [["Accuracy", "0.98"]],
                    "records": [],
                    "column_types": {"Metric": "string", "Value": "float"},
                    "row_count": 1,
                    "column_count": 2,
                }
            ],
            "chunks": [],
            "processing_time_ms": 12.5,
        }
    )


def test_vault_structure_and_note_write(tmp_path: Path) -> None:
    vault = tmp_path / "MemoriaOS-Vault"
    writer = ObsidianWriter(ObsidianConfig(vault_path=vault))
    result = writer.ingest(sample_document())

    assert result.created is True
    assert result.status == "created"
    assert result.note_path.is_file()
    assert (vault / "00-Inbox").is_dir()
    assert (vault / "00-Inbox").is_dir()
    note = result.note_path.read_text(encoding="utf-8")
    assert note.startswith("---\n")
    assert 'document_id: "doc-test-001"' in note
    assert 'content_hash: "sha256:0123456789abcdef0123456789abcdef"' in note
    assert "Original extracted text." in note
    assert "| Accuracy | 0.98 |" in note
    assert "- Introduction (level 1)" in note


def test_duplicate_document_and_hash_is_idempotent(tmp_path: Path) -> None:
    writer = ObsidianWriter(ObsidianConfig(vault_path=tmp_path / "vault"))
    document = sample_document()

    first = writer.ingest(document)
    second = writer.ingest(document.model_dump(mode="json"))

    assert first.created is True
    assert second.created is False
    assert second.status == "already_ingested"
    assert first.note_path == second.note_path
    assert len(list((tmp_path / "vault" / "00-Inbox").glob("*.md"))) == 1


def test_changed_hash_preserves_previous_note(tmp_path: Path) -> None:
    writer = ObsidianWriter(ObsidianConfig(vault_path=tmp_path / "vault"))
    original = sample_document()
    first = writer.ingest(original)
    changed_data = original.model_dump(mode="json")
    changed_data["source"]["content_hash"] = "sha256:fedcba9876543210fedcba9876543210"
    changed = NormalizedDocument.model_validate(changed_data)

    second = writer.ingest(changed)

    assert second.created is True
    assert first.note_path != second.note_path
    assert first.note_path.exists()
    assert second.note_path.exists()


def test_unrelated_existing_note_is_never_overwritten(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    folder = vault / "00-Inbox"
    folder.mkdir(parents=True)
    protected = folder / "Research - A Test.md"
    protected.write_text("User-authored note", encoding="utf-8")

    result = ObsidianWriter(ObsidianConfig(vault_path=vault)).ingest(sample_document())

    assert protected.read_text(encoding="utf-8") == "User-authored note"
    assert result.note_path != protected
    assert result.note_path.exists()


def test_markdown_builder_escapes_yaml_and_keeps_unicode() -> None:
    document = sample_document()
    data = document.model_dump(mode="json")
    data["metadata"]["title"] = 'A title: "quoted" — বাংলা'
    document = NormalizedDocument.model_validate(data)

    note = MarkdownNoteBuilder().build(document)

    assert 'title: "A title: \\"quoted\\" — বাংলা"' in note
    assert "বাংলা" in note


def test_ingestion_survives_writer_restart(tmp_path: Path) -> None:
    config = ObsidianConfig(vault_path=tmp_path / "vault")
    first = ObsidianWriter(config).ingest(sample_document())
    second = ObsidianWriter(config).ingest(sample_document())

    assert first.note_path == second.note_path
    assert second.status == "already_ingested"


def test_cli_payload_envelope_shape_is_supported(tmp_path: Path) -> None:
    document = sample_document()
    payload = {"output": document.model_dump(mode="json")}
    input_path = tmp_path / "document.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = json.loads(input_path.read_text(encoding="utf-8"))

    result = ObsidianWriter(ObsidianConfig(vault_path=tmp_path / "vault")).ingest(loaded["output"])
    assert result.created is True


def test_config_rejects_folder_traversal(tmp_path: Path) -> None:
    config = ObsidianConfig(vault_path=tmp_path / "vault", document_folder="../outside")
    with pytest.raises(ValueError):
        config.ensure_vault()
    assert not (tmp_path / "outside").exists()


def test_missing_note_recovery_recreates_note_and_preserves_unrelated_files(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    writer = ObsidianWriter(ObsidianConfig(vault_path=vault))
    document = sample_document()

    first = writer.ingest(document)
    assert first.created is True
    assert first.status == "created"
    assert first.note_path.exists()

    # Simulate user removing the generated note while ledger entry remains.
    first.note_path.unlink()
    assert not first.note_path.exists()

    recovered = writer.ingest(document)
    assert recovered.created is True
    assert recovered.status == "recreated"
    assert recovered.note_path.is_file()
    assert recovered.vault_relative_path.startswith("00-Inbox/")

    # Subsequent ingestion is idempotent again.
    third = writer.ingest(document)
    assert third.created is False
    assert third.status == "already_ingested"
    assert third.note_path == recovered.note_path

    # Unrelated note at collision name must never be overwritten if ledger pointed elsewhere.
    other_vault = tmp_path / "other_vault"
    other_writer = ObsidianWriter(ObsidianConfig(vault_path=other_vault))
    initial = other_writer.ingest(document)
    initial.note_path.unlink()
    # Replace recorded path with a directory to force fallback to _available_destination.
    initial.note_path.mkdir(parents=True)
    protected_file = other_vault / "00-Inbox" / "Research - A Test-0123456789.md"
    protected_file.write_text("Protected user content", encoding="utf-8")

    fallback_recovered = other_writer.ingest(document)
    assert fallback_recovered.created is True
    assert fallback_recovered.status == "recreated"
    assert fallback_recovered.note_path != protected_file
    assert protected_file.read_text(encoding="utf-8") == "Protected user content"


def test_api_obsidian_persistence_disabled_by_default(
    client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("MEMORIA_OBSIDIAN_VAULT_PATH", raising=False)
    monkeypatch.delenv("MEMORIA_OBSIDIAN_DATABASE_PATH", raising=False)

    doc_res = client.post(
        "/api/v1/documents/process",
        files={"file": ("note.txt", b"Opt-in Obsidian persistence test.", "text/plain")},
    )
    assert doc_res.status_code == 200
    assert "X-Obsidian-Status" not in doc_res.headers
    assert "X-Obsidian-Created" not in doc_res.headers
    assert "X-Obsidian-Note-Path" not in doc_res.headers

    agent_res = client.post(
        "/api/v1/agent/execute",
        files={"file": ("note.txt", b"Opt-in Obsidian persistence test.", "text/plain")},
    )
    assert agent_res.status_code == 200
    agent_meta = agent_res.json()["metadata"]
    assert "obsidian_status" not in agent_meta
    assert "obsidian_created" not in agent_meta
    assert "obsidian_note_path" not in agent_meta
    assert not (tmp_path / "vault").exists()


def test_api_documents_process_and_extract_save_to_obsidian_and_duplicate(
    app_instance, client, tmp_path: Path
) -> None:
    from app.api.dependencies import get_obsidian_writer

    vault = tmp_path / "api_vault"
    app_instance.dependency_overrides[get_obsidian_writer] = lambda: ObsidianWriter(
        ObsidianConfig(vault_path=vault)
    )

    payload = b"# Vault Note\n\nSaved to 00-Inbox via API."
    res1 = client.post(
        "/api/v1/documents/process?save_to_obsidian=true",
        files={"file": ("vault_note.md", payload, "text/markdown")},
    )
    assert res1.status_code == 200
    assert res1.headers["X-Obsidian-Status"] == "created"
    assert res1.headers["X-Obsidian-Created"] == "true"
    rel_path = res1.headers["X-Obsidian-Note-Path"]
    assert rel_path.startswith("00-Inbox/")
    assert (vault / rel_path).is_file()
    # Other folders remain untouched (no automatic classification).
    assert list((vault / "03-Semantic-Memory").glob("*")) == []

    # Duplicate ingestion via /extract alias is idempotent.
    res2 = client.post(
        "/api/v1/documents/extract?save_to_obsidian=true",
        files={"file": ("vault_note.md", payload, "text/markdown")},
    )
    assert res2.status_code == 200
    assert res2.headers["X-Obsidian-Status"] == "already_ingested"
    assert res2.headers["X-Obsidian-Created"] == "false"
    assert res2.headers["X-Obsidian-Note-Path"] == rel_path
    assert len(list((vault / "00-Inbox").glob("*.md"))) == 1

    # Missing note recovery via API.
    (vault / rel_path).unlink()
    res3 = client.post(
        "/api/v1/documents/process?save_to_obsidian=true",
        files={"file": ("vault_note.md", payload, "text/markdown")},
    )
    assert res3.status_code == 200
    assert res3.headers["X-Obsidian-Status"] == "recreated"
    assert res3.headers["X-Obsidian-Created"] == "true"
    assert (vault / res3.headers["X-Obsidian-Note-Path"]).is_file()


def test_api_obsidian_dependency_uses_env_when_not_overridden(
    client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault = tmp_path / "env_vault"
    monkeypatch.setenv("MEMORIA_OBSIDIAN_VAULT_PATH", str(vault))

    res = client.post(
        "/api/v1/documents/process?save_to_obsidian=true",
        files={"file": ("env_note.txt", b"Configured via env.", "text/plain")},
    )
    assert res.status_code == 200
    assert res.headers["X-Obsidian-Status"] == "created"
    assert (vault / res.headers["X-Obsidian-Note-Path"]).is_file()


def test_api_obsidian_persistence_failure_is_explicit_and_sanitized(
    app_instance, client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.api.dependencies import get_obsidian_writer

    # 1. Missing vault environment configuration returns OBSIDIAN_PERSISTENCE_ERROR.
    monkeypatch.delenv("MEMORIA_OBSIDIAN_VAULT_PATH", raising=False)
    unconfigured = client.post(
        "/api/v1/documents/process?save_to_obsidian=true",
        files={"file": ("fail.txt", b"Valid extracted content.", "text/plain")},
    )
    assert unconfigured.status_code == 500
    body = unconfigured.json()
    assert body["status"] == "error"
    assert body["error_code"] == "OBSIDIAN_PERSISTENCE_ERROR"

    # 2. Unexpected writer failure does not leak local filesystem paths or raw tracebacks.
    secret_vault = tmp_path / "secret_vault_path_123"

    class FailingWriter(ObsidianWriter):
        def ingest(self, payload):  # type: ignore[override]
            raise OSError(f"Permission denied writing to {secret_vault / '00-Inbox'}")

    app_instance.dependency_overrides[get_obsidian_writer] = lambda: FailingWriter(
        ObsidianConfig(vault_path=secret_vault)
    )
    failed_doc = client.post(
        "/api/v1/documents/process?save_to_obsidian=true",
        files={"file": ("fail.txt", b"Valid extracted content.", "text/plain")},
    )
    assert failed_doc.status_code == 500
    assert failed_doc.json()["error_code"] == "OBSIDIAN_PERSISTENCE_ERROR"
    assert "secret_vault_path_123" not in failed_doc.text
    assert "Traceback" not in failed_doc.text

    # 3. Non-00-Inbox target folder is rejected safely.
    app_instance.dependency_overrides[get_obsidian_writer] = lambda: ObsidianWriter(
        ObsidianConfig(vault_path=secret_vault, document_folder="03-Semantic-Memory")
    )
    wrong_folder = client.post(
        "/api/v1/documents/process?save_to_obsidian=true",
        files={"file": ("fail.txt", b"Valid extracted content.", "text/plain")},
    )
    assert wrong_folder.status_code == 500
    assert wrong_folder.json()["error_code"] == "OBSIDIAN_PERSISTENCE_ERROR"


def test_api_agent_execute_obsidian_metadata_and_failures(
    app_instance, client, tmp_path: Path
) -> None:
    from app.api.dependencies import get_obsidian_writer

    vault = tmp_path / "agent_vault"
    app_instance.dependency_overrides[get_obsidian_writer] = lambda: ObsidianWriter(
        ObsidianConfig(vault_path=vault)
    )

    res = client.post(
        "/api/v1/agent/execute?task_id=obs-001&save_to_obsidian=true",
        files={"file": ("agent_note.txt", b"Agent 01 persistence.", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["task_id"] == "obs-001"
    assert body["status"] == "success"
    assert body["metadata"]["obsidian_status"] == "created"
    assert body["metadata"]["obsidian_created"] is True
    assert body["metadata"]["obsidian_note_path"].startswith("00-Inbox/")
    assert (vault / body["metadata"]["obsidian_note_path"]).is_file()

    # Extraction failure must remain distinguishable and not trigger Obsidian persistence.
    bad_extract = client.post(
        "/api/v1/agent/execute?save_to_obsidian=true",
        files={"file": ("bad.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert bad_extract.status_code == 200
    bad_body = bad_extract.json()
    assert bad_body["status"] == "failed"
    assert bad_body["errors"][0]["error_code"] == "UNSUPPORTED_DOCUMENT_FORMAT"
    assert "obsidian_status" not in bad_body["metadata"]

    # Persistence failure on /agent/execute surfaces OBSIDIAN_PERSISTENCE_ERROR without paths.
    secret_vault = tmp_path / "secret_agent_vault"

    class FailingAgentWriter(ObsidianWriter):
        def ingest(self, payload):  # type: ignore[override]
            raise OSError(f"Disk error in {secret_vault}")

    app_instance.dependency_overrides[get_obsidian_writer] = lambda: FailingAgentWriter(
        ObsidianConfig(vault_path=secret_vault)
    )
    failed_agent = client.post(
        "/api/v1/agent/execute?save_to_obsidian=true",
        files={"file": ("agent_fail.txt", b"Valid body.", "text/plain")},
    )
    assert failed_agent.status_code == 500
    assert failed_agent.json()["error_code"] == "OBSIDIAN_PERSISTENCE_ERROR"
    assert "secret_agent_vault" not in failed_agent.text


def test_api_batch_extraction_remains_unmodified(
    app_instance, client, tmp_path: Path
) -> None:
    from app.api.dependencies import get_obsidian_writer

    vault = tmp_path / "batch_vault"
    app_instance.dependency_overrides[get_obsidian_writer] = lambda: ObsidianWriter(
        ObsidianConfig(vault_path=vault)
    )

    batch_res = client.post(
        "/api/v1/documents/extract-batch",
        files=[("files", ("one.txt", b"Batch body", "text/plain"))],
    )
    assert batch_res.status_code == 200
    assert batch_res.json()["succeeded"] == 1
    assert "X-Obsidian-Status" not in batch_res.headers
    assert not vault.exists()


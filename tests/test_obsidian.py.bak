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
    assert (vault / "01-Raw-Documents").is_dir()
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
    assert len(list((tmp_path / "vault" / "01-Raw-Documents").glob("*.md"))) == 1


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
    folder = vault / "01-Raw-Documents"
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

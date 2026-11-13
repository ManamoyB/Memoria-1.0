"""Safe, idempotent writer for local Obsidian vaults."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.obsidian.config import ObsidianConfig
from app.obsidian.markdown import MarkdownNoteBuilder, safe_filename
from app.obsidian.repository import IngestionRecord, IngestionRepository
from app.schemas.document import NormalizedDocument


@dataclass(frozen=True, slots=True)
class ObsidianIngestionResult:
    document_id: str
    content_hash: str
    note_path: Path
    vault_relative_path: str
    status: str
    created: bool


class ObsidianWriter:
    """Write validated Agent 01 outputs into a configured local vault."""

    def __init__(
        self,
        config: ObsidianConfig,
        *,
        note_builder: MarkdownNoteBuilder | None = None,
        repository: IngestionRepository | None = None,
    ) -> None:
        self.config = config
        self.note_builder = note_builder or MarkdownNoteBuilder()
        self._repository = repository

    @classmethod
    def from_env(cls) -> "ObsidianWriter":
        return cls(ObsidianConfig.from_env())

    def _repository_for_vault(self, vault_root: Path) -> IngestionRepository:
        if self._repository is not None:
            return self._repository
        return IngestionRepository(self.config.resolved_database_path())

    @staticmethod
    def _atomic_write(destination: Path, content: str) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=destination.parent,
                prefix=".memoria-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, destination)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise

    def _available_destination(
        self, vault_root: Path, document: NormalizedDocument
    ) -> Path:
        folder = (vault_root / self.config.document_folder).resolve()
        if vault_root not in folder.parents:
            raise ValueError("Configured document folder escapes the Obsidian vault.")
        folder.mkdir(parents=True, exist_ok=True)
        stem = safe_filename(document.metadata.title or document.filename)
        digest_suffix = document.source.content_hash.removeprefix("sha256:")[:10]
        candidate = folder / f"{stem}.md"
        if candidate.exists():
            candidate = folder / f"{stem}-{digest_suffix}.md"
        counter = 2
        while candidate.exists():
            candidate = folder / f"{stem}-{digest_suffix}-{counter}.md"
            counter += 1
        resolved = candidate.resolve()
        if folder not in resolved.parents:
            raise ValueError("Generated note path escapes the configured document folder.")
        return resolved

    def ingest(
        self, payload: NormalizedDocument | dict[str, object]
    ) -> ObsidianIngestionResult:
        """Validate, render, and persist a normalized document idempotently."""
        try:
            document = (
                payload
                if isinstance(payload, NormalizedDocument)
                else NormalizedDocument.model_validate(payload)
            )
        except ValidationError:
            raise

        vault_root = self.config.ensure_vault()
        repository = self._repository_for_vault(vault_root)
        content_hash = document.source.content_hash
        existing = repository.find(document.document_id, content_hash)
        folder = (vault_root / self.config.document_folder).resolve()
        if existing is not None:
            existing_path = (vault_root / existing.note_path).resolve()
            if vault_root not in existing_path.parents:
                raise ValueError("Stored ingestion path escapes the Obsidian vault.")
            if existing_path.is_file():
                return ObsidianIngestionResult(
                    document_id=document.document_id,
                    content_hash=content_hash,
                    note_path=existing_path,
                    vault_relative_path=existing.note_path,
                    status="already_ingested",
                    created=False,
                )

            # Ledger entry exists, but the recorded Markdown file is missing on disk.
            if (
                not existing_path.exists()
                and not existing_path.is_symlink()
                and (folder == existing_path.parent or folder in existing_path.parents)
            ):
                existing_path.parent.mkdir(parents=True, exist_ok=True)
                destination = existing_path
            else:
                destination = self._available_destination(vault_root, document)

            markdown = self.note_builder.build(document)
            self._atomic_write(destination, markdown)
            relative_path = destination.relative_to(vault_root).as_posix()
            recovered_record = IngestionRecord(
                document_id=document.document_id,
                content_hash=content_hash,
                note_path=relative_path,
                ingested_at=datetime.now(timezone.utc).isoformat(),
            )
            try:
                repository.upsert(recovered_record)
            except Exception:
                destination.unlink(missing_ok=True)
                raise

            return ObsidianIngestionResult(
                document_id=document.document_id,
                content_hash=content_hash,
                note_path=destination,
                vault_relative_path=relative_path,
                status="recreated",
                created=True,
            )

        destination = self._available_destination(vault_root, document)
        markdown = self.note_builder.build(document)
        self._atomic_write(destination, markdown)
        relative_path = destination.relative_to(vault_root).as_posix()
        record = IngestionRecord(
            document_id=document.document_id,
            content_hash=content_hash,
            note_path=relative_path,
            ingested_at=datetime.now(timezone.utc).isoformat(),
        )
        try:
            repository.record(record)
        except Exception:
            destination.unlink(missing_ok=True)
            raise

        return ObsidianIngestionResult(
            document_id=document.document_id,
            content_hash=content_hash,
            note_path=destination,
            vault_relative_path=relative_path,
            status="created",
            created=True,
        )

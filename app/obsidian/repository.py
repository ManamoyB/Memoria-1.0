"""SQLite idempotency ledger for Obsidian note ingestion."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class IngestionRecord:
    document_id: str
    content_hash: str
    note_path: str
    ingested_at: str


class IngestionRepository:
    """Persist document identity and vault-relative note locations."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS obsidian_ingestions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    note_path TEXT NOT NULL,
                    ingested_at TEXT NOT NULL,
                    UNIQUE(document_id, content_hash)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_obsidian_document_id "
                "ON obsidian_ingestions(document_id)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def find(self, document_id: str, content_hash: str) -> IngestionRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT document_id, content_hash, note_path, ingested_at
                   FROM obsidian_ingestions
                   WHERE document_id = ? AND content_hash = ?""",
                (document_id, content_hash),
            ).fetchone()
        return IngestionRecord(**dict(row)) if row else None

    def record(self, record: IngestionRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO obsidian_ingestions
                   (document_id, content_hash, note_path, ingested_at)
                   VALUES (?, ?, ?, ?)""",
                (record.document_id, record.content_hash, record.note_path, record.ingested_at),
            )

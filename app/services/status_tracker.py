"""Thread-safe bounded status tracker for processed document IDs."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from threading import Lock

from app.core.exceptions import DocumentStatusNotFoundError
from app.schemas.common import DocumentStatusResponse
from app.schemas.document import NormalizedDocument


class DocumentStatusTracker:
    """Bounded in-memory status store keyed by deterministic ``document_id``.

    Retains lightweight processing metadata (never raw file paths or file bytes)
    so callers can inspect ingestion outcomes via ``GET /api/v1/documents/{id}/status``.
    """

    def __init__(self, max_entries: int = 1000) -> None:
        self._max_entries = max(1, max_entries)
        self._lock = Lock()
        self._records: OrderedDict[str, DocumentStatusResponse] = OrderedDict()

    def record_document(self, document: NormalizedDocument) -> DocumentStatusResponse:
        """Persist or refresh the status snapshot for a normalized document."""
        snapshot = DocumentStatusResponse(
            document_id=document.document_id,
            filename=document.filename,
            document_type=document.document_type,
            status=document.status,
            chunk_count=document.metadata.chunk_count,
            block_count=document.metadata.block_count,
            processing_time_ms=document.processing_time_ms,
            warnings=list(document.extraction_warnings),
            updated_at=datetime.now(timezone.utc),
        )
        with self._lock:
            if document.document_id in self._records:
                self._records.move_to_end(document.document_id)
            self._records[document.document_id] = snapshot
            while len(self._records) > self._max_entries:
                self._records.popitem(last=False)
        return snapshot

    def get_status(self, document_id: str) -> DocumentStatusResponse:
        """Retrieve tracked processing status or raise DocumentStatusNotFoundError."""
        with self._lock:
            record = self._records.get(document_id)
        if record is None:
            raise DocumentStatusNotFoundError(
                f"No processing status found for document_id '{document_id}'.",
                details={"document_id": document_id},
            )
        return record

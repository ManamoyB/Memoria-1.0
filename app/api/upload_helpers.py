"""Shared multipart upload streaming and query validation helpers for API routes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import UploadFile, status

from app.core.config import Settings
from app.core.exceptions import MemoriaReaderError, ObsidianPersistenceError
from app.core.logging import get_logger
from app.obsidian import ObsidianIngestionResult, ObsidianWriter
from app.schemas.document import ChunkingConfig, NormalizedDocument

_UPLOAD_READ_CHUNK_SIZE = 65536
_ALLOWED_INBOX_FOLDER = "00-Inbox"
logger = get_logger(__name__)


async def iter_upload_chunks(upload_file: UploadFile) -> AsyncIterator[bytes]:
    """Adapt FastAPI UploadFile into a framework-agnostic async byte-chunk stream."""
    try:
        while chunk := await upload_file.read(_UPLOAD_READ_CHUNK_SIZE):
            yield chunk
    finally:
        try:
            await upload_file.seek(0)
        except Exception:
            # Ignore seek failures if the underlying spooled file was already closed.
            pass


def resolve_chunking_config(
    *,
    settings: Settings,
    chunk_size: int | None,
    chunk_overlap: int | None,
) -> ChunkingConfig:
    """Resolve effective chunking config from query overrides and validate overlap."""
    resolved_size = chunk_size if chunk_size is not None else settings.chunk_size
    resolved_overlap = chunk_overlap if chunk_overlap is not None else settings.chunk_overlap
    if resolved_overlap >= resolved_size:
        raise MemoriaReaderError(
            "chunk_overlap must be strictly smaller than chunk_size.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code="INVALID_CHUNKING_CONFIG",
            details={"chunk_size": resolved_size, "chunk_overlap": resolved_overlap},
        )
    return ChunkingConfig(chunk_size=resolved_size, chunk_overlap=resolved_overlap)


async def persist_document_to_obsidian(
    *,
    resolve_writer: Callable[[], Awaitable[ObsidianWriter]],
    document: NormalizedDocument,
    request_id: str | None = None,
) -> ObsidianIngestionResult:
    """Safely persist a NormalizedDocument to 00-Inbox without exposing local paths."""
    try:
        writer = await resolve_writer()
        if writer.config.document_folder != _ALLOWED_INBOX_FOLDER:
            raise ObsidianPersistenceError(
                "Agent 01 Obsidian persistence is restricted to the 00-Inbox folder.",
                details={"allowed_folder": _ALLOWED_INBOX_FOLDER},
            )
        return writer.ingest(document)
    except MemoriaReaderError:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to persist document %s to Obsidian",
            document.document_id,
            extra={"request_id": request_id},
        )
        raise ObsidianPersistenceError(
            "Failed to persist normalized document to the configured Obsidian vault.",
            details={
                "document_id": document.document_id,
                "error_type": type(exc).__name__,
            },
        ) from exc

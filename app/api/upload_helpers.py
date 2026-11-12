"""Shared multipart upload streaming and query validation helpers for API routes."""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import UploadFile, status

from app.core.config import Settings
from app.core.exceptions import MemoriaReaderError
from app.schemas.document import ChunkingConfig

_UPLOAD_READ_CHUNK_SIZE = 65536


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

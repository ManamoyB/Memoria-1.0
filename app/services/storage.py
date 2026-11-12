"""Framework-agnostic temporary upload storage service with streaming limits and cleanup."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, BinaryIO

from app.core.exceptions import EmptyDocumentError, FileTooLargeError, StorageError
from app.utils.file_utils import compute_sha256, sanitize_filename

_CHUNK_SIZE = 65536


@dataclass(slots=True)
class StoredUpload:
    """Descriptor for a safely persisted temporary file artifact."""

    path: Path
    original_filename: str
    sanitized_filename: str
    byte_size: int
    sha256: str


class UploadStorageService:
    """Manages safe temporary file persistence under the configured storage directory.

    Intentionally decoupled from FastAPI so LangGraph, CLI, or queue workers can
    reuse the exact same storage, size-guard, and cleanup guarantees.
    """

    def __init__(self, upload_dir: Path, max_file_size_bytes: int) -> None:
        self._upload_dir = upload_dir
        self._max_file_size_bytes = max_file_size_bytes

    @property
    def upload_dir(self) -> Path:
        return self._upload_dir

    def ensure_ready(self) -> None:
        """Create the upload storage directory if it does not already exist."""
        try:
            self._upload_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(
                "Unable to initialize temporary upload storage directory.",
                details={"reason": type(exc).__name__},
            ) from exc

    def _allocate_destination(self, filename: str, extension: str) -> tuple[str, Path]:
        self.ensure_ready()
        safe_name = sanitize_filename(filename)
        suffix = extension if extension.startswith(".") else f".{extension}"
        unique_name = f"{uuid.uuid4().hex}_{Path(safe_name).stem}{suffix}"
        destination = (self._upload_dir / unique_name).resolve()

        if self._upload_dir.resolve() not in destination.parents:
            raise StorageError("Resolved upload path escaped the configured upload directory.")
        return safe_name, destination

    def save_bytes(
        self,
        data: bytes,
        *,
        filename: str,
        extension: str,
    ) -> StoredUpload:
        """Persist raw bytes safely to temp storage while enforcing size limits."""
        safe_name, destination = self._allocate_destination(filename, extension)
        byte_size = len(data)
        if byte_size == 0:
            raise EmptyDocumentError(
                f"Uploaded file '{safe_name}' is empty (0 bytes).",
                details={"filename": safe_name},
            )
        if byte_size > self._max_file_size_bytes:
            raise FileTooLargeError(
                f"File '{safe_name}' exceeds maximum allowed size of "
                f"{self._max_file_size_bytes} bytes.",
                details={"filename": safe_name, "max_bytes": self._max_file_size_bytes},
            )

        try:
            destination.write_bytes(data)
        except OSError as exc:
            self.cleanup(destination)
            raise StorageError(
                f"Failed to persist file '{safe_name}'.",
                details={"reason": str(exc)},
            ) from exc

        return StoredUpload(
            path=destination,
            original_filename=filename,
            sanitized_filename=safe_name,
            byte_size=byte_size,
            sha256=compute_sha256(destination),
        )

    def save_stream(
        self,
        stream: BinaryIO,
        *,
        filename: str,
        extension: str,
    ) -> StoredUpload:
        """Persist a synchronous binary stream while enforcing size limits."""
        safe_name, destination = self._allocate_destination(filename, extension)
        total_bytes = 0

        try:
            with destination.open("wb") as out_file:
                while chunk := stream.read(_CHUNK_SIZE):
                    total_bytes += len(chunk)
                    if total_bytes > self._max_file_size_bytes:
                        raise FileTooLargeError(
                            f"File '{safe_name}' exceeds maximum allowed size of "
                            f"{self._max_file_size_bytes} bytes.",
                            details={
                                "filename": safe_name,
                                "max_bytes": self._max_file_size_bytes,
                            },
                        )
                    out_file.write(chunk)
        except FileTooLargeError:
            self.cleanup(destination)
            raise
        except OSError as exc:
            self.cleanup(destination)
            raise StorageError(
                f"Failed to persist file '{safe_name}'.",
                details={"reason": str(exc)},
            ) from exc

        if total_bytes == 0:
            self.cleanup(destination)
            raise EmptyDocumentError(
                f"Uploaded file '{safe_name}' is empty (0 bytes).",
                details={"filename": safe_name},
            )

        return StoredUpload(
            path=destination,
            original_filename=filename,
            sanitized_filename=safe_name,
            byte_size=total_bytes,
            sha256=compute_sha256(destination),
        )

    async def save_async_chunks(
        self,
        chunks: AsyncIterator[bytes],
        *,
        filename: str,
        extension: str,
    ) -> StoredUpload:
        """Persist an async stream of byte chunks while enforcing size limits."""
        safe_name, destination = self._allocate_destination(filename, extension)
        total_bytes = 0

        try:
            with destination.open("wb") as out_file:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > self._max_file_size_bytes:
                        raise FileTooLargeError(
                            f"File '{safe_name}' exceeds maximum allowed size of "
                            f"{self._max_file_size_bytes} bytes.",
                            details={
                                "filename": safe_name,
                                "max_bytes": self._max_file_size_bytes,
                            },
                        )
                    out_file.write(chunk)
        except FileTooLargeError:
            self.cleanup(destination)
            raise
        except OSError as exc:
            self.cleanup(destination)
            raise StorageError(
                f"Failed to persist uploaded file '{safe_name}'.",
                details={"reason": str(exc)},
            ) from exc

        if total_bytes == 0:
            self.cleanup(destination)
            raise EmptyDocumentError(
                f"Uploaded file '{safe_name}' is empty (0 bytes).",
                details={"filename": safe_name},
            )

        return StoredUpload(
            path=destination,
            original_filename=filename,
            sanitized_filename=safe_name,
            byte_size=total_bytes,
            sha256=compute_sha256(destination),
        )

    @staticmethod
    def cleanup(file_path: Path) -> None:
        """Delete a temporary uploaded artifact if it exists."""
        try:
            if file_path.exists() and file_path.is_file():
                file_path.unlink()
        except OSError:
            pass

    def purge_stale_files(self, max_age_seconds: int = 3600) -> int:
        """Remove orphaned temporary files older than ``max_age_seconds``."""
        if not self._upload_dir.exists():
            return 0
        cutoff = time.time() - max_age_seconds
        removed = 0
        for entry in self._upload_dir.iterdir():
            if entry.name == ".gitkeep" or not entry.is_file():
                continue
            try:
                if entry.stat().st_mtime <= cutoff:
                    entry.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

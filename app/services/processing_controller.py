"""Framework-independent central ProcessingController for document ingestion and normalization."""

from __future__ import annotations

import time
from pathlib import Path
from typing import AsyncIterator, BinaryIO

from app.core.config import Settings
from app.core.exceptions import MemoriaReaderError
from app.core.logging import get_logger
from app.extractors.base import ExtractionContext
from app.extractors.registry import ExtractorRegistry
from app.schemas.common import ExtractionStatus
from app.schemas.document import (
    BatchExtractionItem,
    BatchExtractionResponse,
    ChunkingConfig,
    DocumentSource,
    NormalizedDocument,
)
from app.services.file_detector import FileDetector
from app.services.file_validator import FileValidator
from app.services.normalizer import DocumentNormalizer
from app.services.status_tracker import DocumentStatusTracker
from app.services.storage import UploadStorageService
from app.utils.file_utils import compute_sha256, sanitize_filename

logger = get_logger(__name__)


class ProcessingController:
    """Central orchestrator for the MemoriaOS Document Reader Agent pipeline.

    Intentionally independent of FastAPI so it can be invoked directly from
    LangGraph nodes, background workers, CLI pipelines, or HTTP handlers.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        registry: ExtractorRegistry,
        storage: UploadStorageService,
        normalizer: DocumentNormalizer,
        detector: FileDetector | None = None,
        validator: FileValidator | None = None,
        status_tracker: DocumentStatusTracker | None = None,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._storage = storage
        self._normalizer = normalizer
        self._detector = detector or FileDetector()
        self._validator = validator or FileValidator(
            max_file_size_bytes=settings.max_file_size_bytes,
            detector=self._detector,
        )
        self._status_tracker = status_tracker

    def _build_extraction_context(self) -> ExtractionContext:
        return ExtractionContext(
            default_encoding=self._settings.default_encoding,
            csv_max_rows=self._settings.csv_max_rows,
            max_file_size_bytes=self._settings.max_file_size_bytes,
            pdf_min_text_chars_per_page=self._settings.pdf_min_text_chars_per_page,
            ocr_enabled=self._settings.ocr_enabled,
            ocr_engine_name=self._settings.ocr_engine,
            tesseract_lang=self._settings.tesseract_lang,
        )

    def _default_chunking_config(self) -> ChunkingConfig:
        return ChunkingConfig(
            chunk_size=self._settings.chunk_size,
            chunk_overlap=self._settings.chunk_overlap,
        )

    def _run_pipeline_on_path(
        self,
        *,
        file_path: Path,
        sanitized_filename: str,
        byte_size: int,
        sha256_hex: str,
        content_type: str | None,
        started_perf: float,
        chunking_config: ChunkingConfig | None = None,
        request_id: str | None = None,
    ) -> NormalizedDocument:
        detected = self._detector.detect_and_verify(
            file_path,
            declared_filename=sanitized_filename,
            content_type=content_type,
        )
        extractor = self._registry.get(detected.format)
        logger.info(
            "Extracting '%s' (%s, %d bytes) via %s",
            sanitized_filename,
            detected.format.value,
            byte_size,
            extractor.name,
            extra={"request_id": request_id},
        )

        extracted = extractor.extract(file_path, self._build_extraction_context())
        source = DocumentSource(
            filename=sanitized_filename,
            extension=detected.extension,
            format=detected.format,
            mime_type=detected.mime_type,
            byte_size=byte_size,
            content_hash=f"sha256:{sha256_hex}",
        )
        normalized = self._normalizer.normalize(
            extracted=extracted,
            source=source,
            total_started_perf=started_perf,
            chunking_config=chunking_config or self._default_chunking_config(),
        )
        if self._status_tracker is not None:
            self._status_tracker.record_document(normalized)
        logger.info(
            "Normalized document %s in %.2f ms (%d blocks, %d chunks)",
            normalized.document_id,
            normalized.processing_time_ms,
            normalized.metadata.block_count,
            normalized.metadata.chunk_count,
            extra={
                "request_id": request_id,
                "document_id": normalized.document_id,
            },
        )
        return normalized

    def process_file(
        self,
        file_path: Path,
        *,
        content_type: str | None = None,
        chunking_config: ChunkingConfig | None = None,
        request_id: str | None = None,
    ) -> NormalizedDocument:
        """Validate, extract, normalize, and chunk an existing file on disk."""
        started = time.perf_counter()
        self._validator.validate_local_file(
            file_path,
            content_type=content_type,
        )
        safe_name = sanitize_filename(file_path.name)
        byte_size = file_path.stat().st_size
        sha256_hex = compute_sha256(file_path)

        return self._run_pipeline_on_path(
            file_path=file_path,
            sanitized_filename=safe_name,
            byte_size=byte_size,
            sha256_hex=sha256_hex,
            content_type=content_type,
            started_perf=started,
            chunking_config=chunking_config,
            request_id=request_id,
        )

    def process_bytes(
        self,
        data: bytes,
        *,
        filename: str,
        content_type: str | None = None,
        chunking_config: ChunkingConfig | None = None,
        request_id: str | None = None,
    ) -> NormalizedDocument:
        """Validate and process in-memory document bytes (ideal for LangGraph/workers)."""
        started = time.perf_counter()
        safe_name, _fmt, ext, resolved_mime = self._validator.validate_incoming_metadata(
            filename=filename,
            content_type=content_type,
        )
        self._validator.validate_size(len(data), safe_name)

        stored = self._storage.save_bytes(data, filename=safe_name, extension=ext)
        try:
            return self._run_pipeline_on_path(
                file_path=stored.path,
                sanitized_filename=stored.sanitized_filename,
                byte_size=stored.byte_size,
                sha256_hex=stored.sha256,
                content_type=resolved_mime,
                started_perf=started,
                chunking_config=chunking_config,
                request_id=request_id,
            )
        finally:
            if self._settings.cleanup_temp_uploads:
                self._storage.cleanup(stored.path)

    def process_stream(
        self,
        stream: BinaryIO,
        *,
        filename: str,
        content_type: str | None = None,
        chunking_config: ChunkingConfig | None = None,
        request_id: str | None = None,
    ) -> NormalizedDocument:
        """Validate and process a synchronous binary stream with temp file cleanup."""
        started = time.perf_counter()
        safe_name, _fmt, ext, resolved_mime = self._validator.validate_incoming_metadata(
            filename=filename,
            content_type=content_type,
        )
        stored = self._storage.save_stream(stream, filename=safe_name, extension=ext)
        try:
            return self._run_pipeline_on_path(
                file_path=stored.path,
                sanitized_filename=stored.sanitized_filename,
                byte_size=stored.byte_size,
                sha256_hex=stored.sha256,
                content_type=resolved_mime,
                started_perf=started,
                chunking_config=chunking_config,
                request_id=request_id,
            )
        finally:
            if self._settings.cleanup_temp_uploads:
                self._storage.cleanup(stored.path)

    async def process_async_chunks(
        self,
        chunks: AsyncIterator[bytes],
        *,
        filename: str,
        content_type: str | None = None,
        chunking_config: ChunkingConfig | None = None,
        request_id: str | None = None,
    ) -> NormalizedDocument:
        """Validate and process an async byte-chunk stream with temp file cleanup."""
        started = time.perf_counter()
        safe_name, _fmt, ext, resolved_mime = self._validator.validate_incoming_metadata(
            filename=filename,
            content_type=content_type,
        )
        stored = await self._storage.save_async_chunks(
            chunks, filename=safe_name, extension=ext
        )
        try:
            return self._run_pipeline_on_path(
                file_path=stored.path,
                sanitized_filename=stored.sanitized_filename,
                byte_size=stored.byte_size,
                sha256_hex=stored.sha256,
                content_type=resolved_mime,
                started_perf=started,
                chunking_config=chunking_config,
                request_id=request_id,
            )
        finally:
            if self._settings.cleanup_temp_uploads:
                self._storage.cleanup(stored.path)

    async def process_async_batch(
        self,
        items: list[tuple[AsyncIterator[bytes], str, str | None]],
        *,
        chunking_config: ChunkingConfig | None = None,
        request_id: str | None = None,
    ) -> BatchExtractionResponse:
        """Process multiple async document streams independently with error isolation."""
        results: list[BatchExtractionItem] = []
        succeeded = 0
        failed = 0

        for chunks, filename, content_type in items:
            safe_name = sanitize_filename(filename)
            try:
                document = await self.process_async_chunks(
                    chunks,
                    filename=filename,
                    content_type=content_type,
                    chunking_config=chunking_config,
                    request_id=request_id,
                )
                results.append(
                    BatchExtractionItem(
                        filename=safe_name,
                        status=document.status,
                        document=document,
                    )
                )
                succeeded += 1
            except MemoriaReaderError as exc:
                failed += 1
                results.append(
                    BatchExtractionItem(
                        filename=safe_name,
                        status=ExtractionStatus.FAILED,
                        error_code=exc.error_code,
                        error_message=exc.message,
                    )
                )
            except Exception:
                failed += 1
                logger.exception(
                    "Unexpected batch extraction error for '%s'",
                    safe_name,
                    extra={"request_id": request_id},
                )
                results.append(
                    BatchExtractionItem(
                        filename=safe_name,
                        status=ExtractionStatus.FAILED,
                        error_code="INTERNAL_SERVER_ERROR",
                        error_message="An unexpected internal error occurred while processing the document.",
                    )
                )

        return BatchExtractionResponse(
            total_files=len(items),
            succeeded=succeeded,
            failed=failed,
            results=results,
        )

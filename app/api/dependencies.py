"""FastAPI dependency injection providers for the Document Reader Agent."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.core.exceptions import ObsidianPersistenceError
from app.extractors import (
    CsvExtractor,
    DocxExtractor,
    ExtractorRegistry,
    MarkdownExtractor,
    OcrEngine,
    PdfExtractor,
    TesseractOcrHook,
    TextExtractor,
)
from app.obsidian import ObsidianConfig, ObsidianWriter
from app.schemas.common import DocumentFormat
from app.schemas.document import ChunkingConfig
from app.services import (
    DocumentChunker,
    DocumentNormalizer,
    DocumentReaderAgentService,
    DocumentStatusTracker,
    FileDetector,
    FileValidator,
    ProcessingController,
    UploadStorageService,
)


def get_app_settings() -> Settings:
    """Provide application configuration settings."""
    return get_settings()


def build_ocr_engine(settings: Settings) -> OcrEngine:
    """Instantiate the configured OCR engine adapter (Tesseract hook by default)."""
    return TesseractOcrHook(tesseract_cmd=settings.tesseract_cmd)


@lru_cache(maxsize=1)
def _cached_registry(tesseract_cmd: str) -> ExtractorRegistry:
    ocr_engine = TesseractOcrHook(tesseract_cmd=tesseract_cmd)
    registry = ExtractorRegistry()
    registry.register(PdfExtractor(ocr_engine=ocr_engine))
    registry.register(DocxExtractor())
    registry.register(TextExtractor())
    registry.register(MarkdownExtractor())
    registry.register(CsvExtractor())
    return registry


def get_extractor_registry(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ExtractorRegistry:
    """Provide the configured ExtractorRegistry containing independent engines."""
    return _cached_registry(settings.tesseract_cmd)


def get_storage_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> UploadStorageService:
    """Provide the upload storage service configured with size and directory guardrails."""
    return UploadStorageService(
        upload_dir=settings.upload_dir,
        max_file_size_bytes=settings.max_file_size_bytes,
    )


@lru_cache(maxsize=1)
def get_file_detector() -> FileDetector:
    """Provide stateless FileDetector singleton."""
    return FileDetector()


@lru_cache(maxsize=1)
def get_status_tracker() -> DocumentStatusTracker:
    """Provide bounded thread-safe DocumentStatusTracker singleton."""
    return DocumentStatusTracker(max_entries=1000)


def get_file_validator(
    settings: Annotated[Settings, Depends(get_app_settings)],
    detector: Annotated[FileDetector, Depends(get_file_detector)],
) -> FileValidator:
    """Provide FileValidator configured with size limits and allowed formats."""
    allowed = {
        DocumentFormat(fmt)
        for fmt in settings.allowed_format_list
        if fmt in {item.value for item in DocumentFormat}
    }
    return FileValidator(
        max_file_size_bytes=settings.max_file_size_bytes,
        allowed_formats=allowed or set(DocumentFormat),
        detector=detector,
    )


def get_document_chunker(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> DocumentChunker:
    """Provide DocumentChunker configured from environment settings."""
    return DocumentChunker(
        default_config=ChunkingConfig(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
    )


def get_document_normalizer(
    chunker: Annotated[DocumentChunker, Depends(get_document_chunker)],
) -> DocumentNormalizer:
    """Provide DocumentNormalizer wired with DocumentChunker."""
    return DocumentNormalizer(chunker=chunker)


def get_processing_controller(
    settings: Annotated[Settings, Depends(get_app_settings)],
    registry: Annotated[ExtractorRegistry, Depends(get_extractor_registry)],
    storage: Annotated[UploadStorageService, Depends(get_storage_service)],
    normalizer: Annotated[DocumentNormalizer, Depends(get_document_normalizer)],
    detector: Annotated[FileDetector, Depends(get_file_detector)],
    validator: Annotated[FileValidator, Depends(get_file_validator)],
    status_tracker: Annotated[DocumentStatusTracker, Depends(get_status_tracker)],
) -> ProcessingController:
    """Assemble and inject the central ProcessingController."""
    return ProcessingController(
        settings=settings,
        registry=registry,
        storage=storage,
        normalizer=normalizer,
        detector=detector,
        validator=validator,
        status_tracker=status_tracker,
    )


def get_agent_service(
    controller: Annotated[ProcessingController, Depends(get_processing_controller)],
) -> DocumentReaderAgentService:
    """Provide the inter-agent DocumentReaderAgentService facade."""
    return DocumentReaderAgentService(controller=controller)


def get_obsidian_writer() -> ObsidianWriter:
    """Provide an ObsidianWriter configured from environment variables."""
    try:
        config = ObsidianConfig.from_env()
    except ValueError as exc:
        raise ObsidianPersistenceError(
            "Obsidian persistence is not configured.",
            details={"reason": "MEMORIA_OBSIDIAN_VAULT_PATH is not configured."},
        ) from exc
    return ObsidianWriter(config)


def get_obsidian_writer_resolver(
    request: Request,
) -> Callable[[], Awaitable[ObsidianWriter]]:
    """Return a lazy ObsidianWriter resolver so disabled requests never touch the vault."""

    async def _resolve() -> ObsidianWriter:
        override = request.app.dependency_overrides.get(get_obsidian_writer)
        if override is not None:
            resolved = override()
            if inspect.isawaitable(resolved):
                return await resolved
            return resolved
        return get_obsidian_writer()

    return _resolve

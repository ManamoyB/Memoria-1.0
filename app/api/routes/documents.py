"""Document ingestion, supported-formats, and status HTTP endpoints."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)

from app.api.dependencies import (
    get_app_settings,
    get_extractor_registry,
    get_obsidian_writer_resolver,
    get_processing_controller,
    get_status_tracker,
)
from app.api.upload_helpers import (
    iter_upload_chunks,
    persist_document_to_obsidian,
    resolve_chunking_config,
)
from app.core.config import Settings
from app.core.exceptions import MemoriaReaderError
from app.extractors.registry import ExtractorRegistry
from app.obsidian import ObsidianWriter
from app.schemas.common import (
    DocumentStatusResponse,
    ErrorResponse,
    SupportedFormatsResponse,
)
from app.schemas.document import BatchExtractionResponse, NormalizedDocument
from app.services.processing_controller import ProcessingController
from app.services.status_tracker import DocumentStatusTracker

router = APIRouter(prefix="/documents", tags=["Documents"])

_SUPPORTED_FORMATS_EXAMPLE = {
    "formats": [
        {
            "format": "pdf",
            "extensions": [".pdf"],
            "mime_types": ["application/pdf"],
            "extractor_name": "pymupdf_pdf_extractor",
            "preserves_structure": True,
            "supports_tables": False,
            "ocr_fallback_ready": True,
        },
        {
            "format": "docx",
            "extensions": [".docx"],
            "mime_types": [
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ],
            "extractor_name": "python_docx_extractor",
            "preserves_structure": True,
            "supports_tables": True,
            "ocr_fallback_ready": False,
        },
        {
            "format": "txt",
            "extensions": [".txt", ".text"],
            "mime_types": ["text/plain"],
            "extractor_name": "plain_text_extractor",
            "preserves_structure": True,
            "supports_tables": False,
            "ocr_fallback_ready": False,
        },
        {
            "format": "markdown",
            "extensions": [".md", ".markdown"],
            "mime_types": ["text/markdown", "text/x-markdown"],
            "extractor_name": "markdown_structural_extractor",
            "preserves_structure": True,
            "supports_tables": True,
            "ocr_fallback_ready": False,
        },
        {
            "format": "csv",
            "extensions": [".csv"],
            "mime_types": ["text/csv", "application/csv"],
            "extractor_name": "pandas_csv_extractor",
            "preserves_structure": True,
            "supports_tables": True,
            "ocr_fallback_ready": False,
        },
    ]
}

_PROCESS_SUCCESS_EXAMPLE = {
    "schema_version": "1.0.0",
    "agent": "memoria-document-reader",
    "document_id": "21396d7a-d006-5da4-8139-6d7ad006fda4",
    "filename": "architecture_notes.md",
    "document_type": "markdown",
    "status": "success",
    "ingested_at": "2026-11-12T22:55:32Z",
    "source": {
        "filename": "architecture_notes.md",
        "extension": ".md",
        "format": "markdown",
        "mime_type": "text/markdown",
        "byte_size": 512,
        "content_hash": "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        "ingested_at": "2026-11-12T22:55:32Z",
    },
    "metadata": {
        "title": "MemoriaOS Architecture",
        "author": "Systems Architect",
        "block_count": 3,
        "section_count": 1,
        "table_count": 0,
        "chunk_count": 1,
        "word_count": 24,
        "char_count": 160,
        "line_count": 5,
        "encoding": "utf-8",
        "extractor_name": "markdown_structural_extractor",
        "custom_properties": {},
    },
    "content": "# MemoriaOS Architecture\n\nDeterministic extraction and normalization.",
    "blocks": [],
    "sections": [],
    "tables": [],
    "pages": [],
    "chunks": [],
    "ocr": {
        "status": "not_needed",
        "ocr_enabled": False,
        "ocr_applied": False,
        "ocr_engine": "tesseract",
        "pages_requiring_ocr": [],
        "empty_pages": [],
        "notes": [],
    },
    "processing_statistics": {
        "extraction_time_ms": 1.4,
        "normalization_time_ms": 0.5,
        "chunking_time_ms": 0.3,
        "total_time_ms": 2.2,
        "char_count": 160,
        "word_count": 24,
        "line_count": 5,
        "block_count": 3,
        "section_count": 1,
        "table_count": 0,
        "chunk_count": 1,
        "page_count": None,
        "empty_page_count": 0,
        "scanned_page_count": 0,
        "records_extracted": None,
        "truncated": False,
    },
    "extraction_warnings": [],
    "processing_time_ms": 2.2,
}

_COMMON_UPLOAD_ERROR_RESPONSES = {
    408: {
        "model": ErrorResponse,
        "description": "Request exceeded configured processing timeout.",
        "content": {
            "application/json": {
                "example": {
                    "status": "error",
                    "error_code": "REQUEST_TIMEOUT",
                    "message": "Document processing exceeded the configured timeout.",
                    "details": {"timeout_seconds": 30.0},
                    "request_id": "req-1234",
                }
            }
        },
    },
    413: {
        "model": ErrorResponse,
        "description": "Uploaded document exceeds configured maximum file size.",
        "content": {
            "application/json": {
                "example": {
                    "status": "error",
                    "error_code": "FILE_TOO_LARGE",
                    "message": "File 'oversized.pdf' exceeds maximum allowed size.",
                    "details": {"max_bytes": 26214400},
                    "request_id": "req-1234",
                }
            }
        },
    },
    415: {
        "model": ErrorResponse,
        "description": "Unsupported document format or mismatched MIME/binary signature.",
        "content": {
            "application/json": {
                "example": {
                    "status": "error",
                    "error_code": "UNSUPPORTED_DOCUMENT_FORMAT",
                    "message": "Unsupported document format for file 'archive.zip'.",
                    "details": {"supported_extensions": [".csv", ".docx", ".md", ".pdf", ".txt"]},
                    "request_id": "req-1234",
                }
            }
        },
    },
    422: {
        "model": ErrorResponse,
        "description": "Empty, corrupted, password-protected, or invalidly encoded document.",
        "content": {
            "application/json": {
                "example": {
                    "status": "error",
                    "error_code": "PASSWORD_PROTECTED_DOCUMENT",
                    "message": "PDF document 'locked.pdf' is password-protected and cannot be read without decryption.",
                    "details": {"filename": "locked.pdf", "is_encrypted": True},
                    "request_id": "req-1234",
                }
            }
        },
    },
    500: {
        "model": ErrorResponse,
        "description": "Unexpected internal error (raw stack traces and filesystem paths are never exposed).",
        "content": {
            "application/json": {
                "example": {
                    "status": "error",
                    "error_code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected internal error occurred while processing the document.",
                    "details": {},
                    "request_id": "req-1234",
                }
            }
        },
    },
}


@router.get(
    "/supported-formats",
    response_model=SupportedFormatsResponse,
    summary="List all supported document formats",
    description=(
        "Returns all registered document formats (PDF, DOCX, TXT, Markdown, CSV), "
        "allowed extensions, MIME types, table support, and OCR readiness."
    ),
    responses={
        200: {
            "description": "Supported formats returned successfully.",
            "content": {"application/json": {"example": _SUPPORTED_FORMATS_EXAMPLE}},
        }
    },
)
async def get_supported_formats(
    registry: Annotated[ExtractorRegistry, Depends(get_extractor_registry)],
) -> SupportedFormatsResponse:
    """Return all supported document formats and extractor capabilities."""
    return SupportedFormatsResponse(formats=registry.list_capabilities())


_OBSIDIAN_HEADERS_OPENAPI = {
    "X-Obsidian-Status": {
        "description": "Obsidian ingestion outcome (created, recreated, or already_ingested) when save_to_obsidian=true.",
        "schema": {"type": "string"},
    },
    "X-Obsidian-Created": {
        "description": "Whether a note file was written on disk ('true' or 'false') when save_to_obsidian=true.",
        "schema": {"type": "string"},
    },
    "X-Obsidian-Note-Path": {
        "description": "Vault-relative path of the persisted Markdown note inside 00-Inbox when save_to_obsidian=true.",
        "schema": {"type": "string"},
    },
}


@router.post(
    "/process",
    response_model=NormalizedDocument,
    status_code=status.HTTP_200_OK,
    summary="Upload and process a document into standardized JSON",
    description=(
        "Accepts a multipart file upload (PDF, DOCX, TXT, Markdown, or CSV), "
        "validates upload size, MIME type, and magic-byte signature, extracts "
        "structural content, normalizes text, generates configurable chunks, cleans up "
        "temporary files, and returns a MemoriaOS NormalizedDocument. When "
        "save_to_obsidian=true, idempotently writes a Markdown note to 00-Inbox and "
        "emits X-Obsidian-Status, X-Obsidian-Created, and X-Obsidian-Note-Path headers."
    ),
    responses={
        200: {
            "description": "Document extracted, normalized, and chunked successfully.",
            "headers": _OBSIDIAN_HEADERS_OPENAPI,
            "content": {"application/json": {"example": _PROCESS_SUCCESS_EXAMPLE}},
        },
        **_COMMON_UPLOAD_ERROR_RESPONSES,
    },
)
@router.post(
    "/extract",
    response_model=NormalizedDocument,
    status_code=status.HTTP_200_OK,
    summary="Alias for POST /api/v1/documents/process",
    description=(
        "Accepts a multipart file upload and returns a standardized NormalizedDocument. "
        "Supports optional save_to_obsidian=true persistence into 00-Inbox."
    ),
    responses={
        200: {
            "description": "Document extracted, normalized, and chunked successfully.",
            "headers": _OBSIDIAN_HEADERS_OPENAPI,
            "content": {"application/json": {"example": _PROCESS_SUCCESS_EXAMPLE}},
        },
        **_COMMON_UPLOAD_ERROR_RESPONSES,
    },
)
async def process_document(
    request: Request,
    response: Response,
    file: Annotated[
        UploadFile,
        File(description="Multipart document upload (PDF, DOCX, TXT, Markdown, or CSV)."),
    ],
    controller: Annotated[ProcessingController, Depends(get_processing_controller)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    resolve_obsidian_writer: Annotated[
        Callable[[], Awaitable[ObsidianWriter]],
        Depends(get_obsidian_writer_resolver),
    ],
    chunk_size: Annotated[
        int | None,
        Query(
            ge=100,
            le=50000,
            description="Optional override for chunk size in characters (default 3000).",
            examples=[3000, 1500],
        ),
    ] = None,
    chunk_overlap: Annotated[
        int | None,
        Query(
            ge=0,
            le=10000,
            description="Optional override for chunk overlap in characters (default 300).",
            examples=[300, 150],
        ),
    ] = None,
    save_to_obsidian: Annotated[
        bool,
        Query(
            description=(
                "Optional opt-in flag to persist the normalized document into the configured "
                "local Obsidian vault's 00-Inbox folder."
            ),
        ),
    ] = False,
) -> NormalizedDocument:
    """Accept a multipart document upload and process it via ProcessingController."""
    request_id = getattr(request.state, "request_id", None)
    chunking_cfg = resolve_chunking_config(
        settings=settings,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    document = await controller.process_async_chunks(
        iter_upload_chunks(file),
        filename=file.filename or "untitled",
        content_type=file.content_type,
        chunking_config=chunking_cfg,
        request_id=request_id,
    )
    if save_to_obsidian:
        ingestion = await persist_document_to_obsidian(
            resolve_writer=resolve_obsidian_writer,
            document=document,
            request_id=request_id,
        )
        response.headers["X-Obsidian-Status"] = ingestion.status
        response.headers["X-Obsidian-Created"] = "true" if ingestion.created else "false"
        response.headers["X-Obsidian-Note-Path"] = ingestion.vault_relative_path
    return document


@router.post(
    "/extract-batch",
    response_model=BatchExtractionResponse,
    status_code=status.HTTP_200_OK,
    summary="Process multiple documents in a single multipart request",
    description=(
        "Processes multiple uploaded documents independently with per-file error isolation "
        "and temporary file cleanup."
    ),
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Empty batch or batch size exceeds MEMORIA_MAX_BATCH_FILES.",
        },
        **_COMMON_UPLOAD_ERROR_RESPONSES,
    },
)
async def extract_documents_batch(
    request: Request,
    files: Annotated[
        list[UploadFile],
        File(description="List of document files (PDF, DOCX, TXT, MD, CSV)"),
    ],
    controller: Annotated[ProcessingController, Depends(get_processing_controller)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    chunk_size: Annotated[
        int | None,
        Query(ge=100, le=50000, description="Optional override for chunk size in characters."),
    ] = None,
    chunk_overlap: Annotated[
        int | None,
        Query(ge=0, le=10000, description="Optional override for chunk overlap in characters."),
    ] = None,
) -> BatchExtractionResponse:
    """Process multiple uploaded documents independently with per-file error isolation."""
    if not files:
        raise MemoriaReaderError(
            "At least one file must be provided for batch extraction.",
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="EMPTY_BATCH_REQUEST",
        )
    if len(files) > settings.max_batch_files:
        raise MemoriaReaderError(
            f"Batch size ({len(files)}) exceeds maximum allowed limit of {settings.max_batch_files}.",
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="BATCH_LIMIT_EXCEEDED",
            details={"received": len(files), "max_batch_files": settings.max_batch_files},
        )

    chunking_cfg = resolve_chunking_config(
        settings=settings,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    request_id = getattr(request.state, "request_id", None)
    items = [
        (iter_upload_chunks(f), f.filename or "untitled", f.content_type)
        for f in files
    ]
    return await controller.process_async_batch(
        items,
        chunking_config=chunking_cfg,
        request_id=request_id,
    )


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    summary="Retrieve processing status for a document ID",
    description=(
        "Returns tracked processing metadata (status, counts, timing, warnings) "
        "for a previously processed deterministic document_id."
    ),
    responses={
        200: {
            "description": "Tracked status found.",
            "content": {
                "application/json": {
                    "example": {
                        "document_id": "21396d7a-d006-5da4-8139-6d7ad006fda4",
                        "filename": "architecture_notes.md",
                        "document_type": "markdown",
                        "status": "success",
                        "chunk_count": 1,
                        "block_count": 3,
                        "processing_time_ms": 2.2,
                        "warnings": [],
                        "updated_at": "2026-11-12T22:55:32Z",
                    }
                }
            },
        },
        404: {
            "model": ErrorResponse,
            "description": "No status record exists for the supplied document_id.",
            "content": {
                "application/json": {
                    "example": {
                        "status": "error",
                        "error_code": "DOCUMENT_STATUS_NOT_FOUND",
                        "message": "No processing status found for document_id '...'.",
                        "details": {"document_id": "..."},
                        "request_id": "req-1234",
                    }
                }
            },
        },
    },
)
async def get_document_status(
    document_id: Annotated[
        str,
        Path(
            min_length=8,
            max_length=128,
            description="Deterministic UUID returned by POST /api/v1/documents/process.",
            examples=["21396d7a-d006-5da4-8139-6d7ad006fda4"],
        ),
    ],
    status_tracker: Annotated[DocumentStatusTracker, Depends(get_status_tracker)],
) -> DocumentStatusResponse:
    """Return tracked processing status for a given document ID."""
    return status_tracker.get_status(document_id)

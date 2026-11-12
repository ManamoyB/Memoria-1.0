"""FastAPI application factory and Uvicorn entrypoint for MemoriaOS Document Reader Agent."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.exception_handlers import register_exception_handlers
from app.api.routes import api_router, root_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.schemas.common import ErrorResponse
from app.services.storage import UploadStorageService

_OPENAPI_TAGS = [
    {
        "name": "Operational",
        "description": "Service metadata, liveness probes, and format capability discovery.",
    },
    {
        "name": "Documents",
        "description": (
            "Multipart document ingestion, structural extraction, normalization, "
            "chunking, and status lookup."
        ),
    },
    {
        "name": "Inter-Agent Communication",
        "description": (
            "Standardized AgentTaskResponse execution endpoints for Agent 07 "
            "(Orchestrator) and LangGraph workflows."
        ),
    },
]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    resolved_settings = settings or get_settings()
    configure_logging(
        level=resolved_settings.log_level,
        environment=resolved_settings.environment,
    )
    logger = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        storage = UploadStorageService(
            upload_dir=resolved_settings.upload_dir,
            max_file_size_bytes=resolved_settings.max_file_size_bytes,
        )
        storage.ensure_ready()
        purged = storage.purge_stale_files(max_age_seconds=3600)
        logger.info(
            "Started %s v%s (%s, purged=%d stale temp files)",
            resolved_settings.app_name,
            resolved_settings.app_version,
            resolved_settings.environment,
            purged,
        )
        yield
        logger.info("Shutting down %s", resolved_settings.app_name)

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description=(
            "First independent agent of MemoriaOS: multi-format document extraction "
            "(PDF, DOCX, TXT, Markdown, CSV), structural preservation, configurable "
            "chunking, and standardized Pydantic v2 JSON normalization."
        ),
        openapi_tags=_OPENAPI_TAGS,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def attach_request_id_and_timeout(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        try:
            response = await asyncio.wait_for(
                call_next(request),
                timeout=resolved_settings.request_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Request timed out after %.2fs",
                resolved_settings.request_timeout_seconds,
                extra={"request_id": request_id},
            )
            body = ErrorResponse(
                error_code="REQUEST_TIMEOUT",
                message="Document processing exceeded the configured timeout.",
                details={"timeout_seconds": resolved_settings.request_timeout_seconds},
                request_id=request_id,
            )
            response = JSONResponse(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                content=body.model_dump(mode="json"),
            )
        response.headers["X-Request-ID"] = request_id
        return response

    cors_origins = resolved_settings.cors_origin_list
    allow_credentials = "*" not in cors_origins
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    register_exception_handlers(application)
    application.include_router(root_router)
    application.include_router(api_router, prefix=resolved_settings.api_prefix)

    return application


app = create_app()

"""FastAPI application factory and Uvicorn entrypoint for MemoriaOS Document Reader Agent."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.body_limit import BodyLimitMiddleware
from app.api.exception_handlers import register_exception_handlers
from app.api.routes import api_router, root_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.memory.repository import MemoryError
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
        memory_runtime = getattr(_app.state, "memory_runtime", None)
        if memory_runtime is not None:
            memory_runtime.close()
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
    from app.api.routes.memory import router as memory_router
    from app.api.routes.memory import runtime

    application.include_router(memory_router, prefix=resolved_settings.api_prefix)
    rate_windows: defaultdict[str, deque[float]] = defaultdict(deque)

    @application.exception_handler(MemoryError)
    async def memory_error_handler(request: Request, exc: MemoryError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={
                "error_code": exc.code,
                "message": str(exc),
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @application.middleware("http")
    async def authenticate_memory_requests(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        prefix = resolved_settings.api_prefix
        public = {
            "/",
            "/health",
            prefix + "/health",
            prefix + "/formats",
            prefix + "/documents/supported-formats",
            "/docs",
            "/redoc",
            "/openapi.json",
        }
        legacy_test = resolved_settings.environment == "test" and (
            request.url.path.startswith(prefix + "/documents")
            or request.url.path == prefix + "/agent/execute"
        )
        if request.method == "OPTIONS" or request.url.path in public or legacy_test:
            return await call_next(request)
        if not request.url.path.startswith(prefix + "/"):
            return await call_next(request)
        try:
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                raise MemoryError("Bearer credential required", "UNAUTHORIZED", 401)
            rt = runtime(request)
            identity = await asyncio.to_thread(rt.repo.authenticate, header[7:])
            request.state.principal = identity
            if (
                request.url.path.startswith(prefix + "/documents")
                or request.url.path == prefix + "/agent/execute"
            ):
                required = "read" if request.method == "GET" else "execute"
                if required not in identity["scopes"] and "admin" not in identity["scopes"]:
                    raise MemoryError("Credential lacks required scope", "FORBIDDEN", 403)
                # Legacy status tracking and vault ledger are owner-local, not multi-tenant.
                if identity["user_id"] != rt.settings.owner_id:
                    raise MemoryError(
                        "Legacy workbench is owner-only; use ingestion API", "FORBIDDEN", 403
                    )
                if request.query_params.get("save_to_obsidian", "false").lower() in ("true", "1"):
                    from app.obsidian.config import DEFAULT_VAULT_FOLDERS, ObsidianConfig

                    vault = ObsidianConfig.from_env().resolved_vault_path()
                    if not vault.is_dir() or any(
                        not (vault / folder).is_dir() or (vault / folder).resolve().parent != vault
                        for folder in DEFAULT_VAULT_FOLDERS
                    ):
                        raise MemoryError(
                            ("Existing vault layout is unavailable"), "VAULT_UNAVAILABLE", 503
                        )
            stamp = time.monotonic()
            window = rate_windows[identity["id"]]
            while window and window[0] < stamp - 60:
                window.popleft()
            if len(window) >= rt.settings.rate_limit_per_minute:
                raise MemoryError("Request rate limit exceeded", "RATE_LIMITED", 429)
            window.append(stamp)
            content_length = request.headers.get("Content-Length")
            if (
                content_length
                and int(content_length) > resolved_settings.max_file_size_bytes + 1048576
            ):
                raise MemoryError("Request exceeds upload limit", "PAYLOAD_TOO_LARGE", 413)
        except MemoryError as exc:
            return await memory_error_handler(request, exc)
        except Exception:
            return JSONResponse(
                status_code=503,
                content={
                    "error_code": "SERVICE_UNAVAILABLE",
                    "message": (
                        "Memory database is unavailable; check initialization and configuration"
                    ),
                },
            )
        return await call_next(request)

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
        except TimeoutError:
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
    application.add_middleware(
        BodyLimitMiddleware,
        max_bytes=resolved_settings.max_file_size_bytes * resolved_settings.max_batch_files
        + 1048576,
    )
    allow_credentials = "*" not in cors_origins
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
    )

    register_exception_handlers(application)
    application.include_router(root_router)
    application.include_router(api_router, prefix=resolved_settings.api_prefix)

    return application


app = create_app()

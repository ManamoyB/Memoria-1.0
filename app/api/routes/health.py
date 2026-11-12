"""Root service info, health check, and capability discovery routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_app_settings, get_extractor_registry
from app.core.config import Settings
from app.extractors.registry import ExtractorRegistry
from app.schemas.common import (
    HealthResponse,
    ServiceInfoResponse,
    SupportedFormatsResponse,
)

root_router = APIRouter(tags=["Operational"])
router = APIRouter(tags=["Operational"])

_SERVICE_INFO_EXAMPLE = {
    "service": "MemoriaOS Document Reader Agent",
    "agent": "memoria-document-reader",
    "version": "0.1.0",
    "environment": "development",
    "status": "running",
    "api_prefix": "/api/v1",
    "docs_url": "/docs",
    "supported_formats": ["pdf", "docx", "txt", "markdown", "csv"],
    "timestamp": "2026-11-12T22:55:32Z",
}

_HEALTH_EXAMPLE = {
    "status": "ok",
    "agent": "memoria-document-reader",
    "version": "0.1.0",
    "environment": "development",
    "ocr_enabled": False,
    "ocr_engine": "tesseract",
    "supported_formats": ["pdf", "docx", "txt", "markdown", "csv"],
    "timestamp": "2026-11-12T22:55:32Z",
}


@root_router.get(
    "/",
    response_model=ServiceInfoResponse,
    summary="Service information and status",
    description="Returns MemoriaOS Document Reader Agent metadata, API prefix, Swagger URL, and supported formats.",
    responses={
        200: {
            "description": "Service information retrieved successfully.",
            "content": {"application/json": {"example": _SERVICE_INFO_EXAMPLE}},
        }
    },
)
async def get_service_info(
    settings: Annotated[Settings, Depends(get_app_settings)],
    registry: Annotated[ExtractorRegistry, Depends(get_extractor_registry)],
) -> ServiceInfoResponse:
    """Return top-level service identity and operational status."""
    return ServiceInfoResponse(
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        status="running",
        api_prefix=settings.api_prefix,
        docs_url="/docs",
        supported_formats=registry.list_formats(),
    )


@root_router.get(
    "/health",
    response_model=HealthResponse,
    summary="Application health check",
    description="Liveness probe reporting service version, OCR configuration, and active extractors.",
    responses={
        200: {
            "description": "Service is healthy.",
            "content": {"application/json": {"example": _HEALTH_EXAMPLE}},
        }
    },
)
@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service liveness and capability status",
    description="Versioned health endpoint reporting OCR status and active document extractors.",
    responses={
        200: {
            "description": "Service is healthy.",
            "content": {"application/json": {"example": _HEALTH_EXAMPLE}},
        }
    },
)
async def get_health(
    settings: Annotated[Settings, Depends(get_app_settings)],
    registry: Annotated[ExtractorRegistry, Depends(get_extractor_registry)],
) -> HealthResponse:
    """Return service health, version, OCR readiness, and supported formats."""
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        environment=settings.environment,
        ocr_enabled=settings.ocr_enabled,
        ocr_engine=settings.ocr_engine,
        supported_formats=registry.list_formats(),
    )


@router.get(
    "/formats",
    response_model=SupportedFormatsResponse,
    summary="List supported document formats and extractor capabilities",
    description="Inspect registered document extractors and their structural capabilities.",
)
async def list_supported_formats(
    registry: Annotated[ExtractorRegistry, Depends(get_extractor_registry)],
) -> SupportedFormatsResponse:
    """Inspect registered document extractors and their structural capabilities."""
    return SupportedFormatsResponse(formats=registry.list_capabilities())

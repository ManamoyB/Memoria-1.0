"""Centralized FastAPI exception handlers mapping domain errors to ErrorResponse JSON."""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import MemoriaReaderError
from app.core.logging import get_logger
from app.schemas.common import ErrorResponse

logger = get_logger(__name__)


def _resolve_request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach centralized exception handlers to the FastAPI application."""

    @app.exception_handler(MemoriaReaderError)
    async def handle_memoria_error(
        request: Request, exc: MemoriaReaderError
    ) -> JSONResponse:
        request_id = _resolve_request_id(request)
        logger.warning(
            "Domain error [%s]: %s",
            exc.error_code,
            exc.message,
            extra={"request_id": request_id},
        )
        body = ErrorResponse(
            error_code=exc.error_code,
            message=exc.message,
            details=jsonable_encoder(exc.details),
            request_id=request_id,
        )
        return JSONResponse(
            status_code=int(exc.status_code),
            content=body.model_dump(mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = _resolve_request_id(request)
        safe_errors = jsonable_encoder(exc.errors())
        logger.warning(
            "Request validation error: %s",
            safe_errors,
            extra={"request_id": request_id},
        )
        body = ErrorResponse(
            error_code="VALIDATION_ERROR",
            message="Request payload failed validation.",
            details={"errors": safe_errors},
            request_id=request_id,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=body.model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request, exc: Exception
    ) -> JSONResponse:
        request_id = _resolve_request_id(request)
        logger.exception(
            "Unhandled server error: %s",
            exc,
            extra={"request_id": request_id},
        )
        body = ErrorResponse(
            error_code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal error occurred while processing the document.",
            details={},
            request_id=request_id,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=body.model_dump(mode="json"),
        )

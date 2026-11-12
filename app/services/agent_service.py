"""Reusable, framework-independent MemoriaOS Document Reader agent service interface."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import AsyncIterator

from app.core.exceptions import (
    CorruptedDocumentError,
    EmptyDocumentError,
    MemoriaReaderError,
    PasswordProtectedDocumentError,
    UnsupportedFormatError,
)
from app.core.logging import get_logger
from app.schemas.agent import AgentError, AgentTaskResponse, MemoriaAgentId
from app.schemas.common import ExtractionStatus
from app.schemas.document import ChunkingConfig, NormalizedDocument
from app.services.processing_controller import ProcessingController
from app.utils.file_utils import sanitize_filename

logger = get_logger(__name__)

_NON_RECOVERABLE_ERRORS = (
    UnsupportedFormatError,
    CorruptedDocumentError,
    EmptyDocumentError,
    PasswordProtectedDocumentError,
)


class DocumentReaderAgentService:
    """High-level inter-agent interface for MemoriaOS Orchestrator and LangGraph nodes.

    Wraps ``ProcessingController`` and always returns a standardized
    ``AgentTaskResponse`` envelope containing ``task_id``, ``agent_id``,
    ``document_id``, ``status``, ``output_type``, ``output``, ``errors``,
    ``metadata``, and ``next_agent``.
    """

    agent_id: str = MemoriaAgentId.DOCUMENT_READER.value

    def __init__(self, controller: ProcessingController) -> None:
        self._controller = controller

    def execute_file(
        self,
        file_path: Path,
        *,
        task_id: str | None = None,
        next_agent: str | None = None,
        chunking_config: ChunkingConfig | None = None,
    ) -> AgentTaskResponse:
        """Process a local file path and return a standardized AgentTaskResponse."""
        resolved_task_id = task_id or str(uuid.uuid4())
        target_next = next_agent or MemoriaAgentId.CONTEXT_UNDERSTANDING.value
        safe_name = sanitize_filename(file_path.name)

        try:
            doc = self._controller.process_file(
                file_path,
                chunking_config=chunking_config,
                request_id=resolved_task_id,
            )
            return self._build_success_response(
                task_id=resolved_task_id,
                document=doc,
                next_agent=target_next,
            )
        except MemoriaReaderError as exc:
            return self._build_error_response(
                task_id=resolved_task_id,
                filename=safe_name,
                exc=exc,
            )
        except Exception:
            logger.exception("Unexpected error in agent execute_file", extra={"request_id": resolved_task_id})
            return self._build_unexpected_error_response(
                task_id=resolved_task_id,
                filename=safe_name,
            )

    def execute_bytes(
        self,
        data: bytes,
        *,
        filename: str,
        content_type: str | None = None,
        task_id: str | None = None,
        next_agent: str | None = None,
        chunking_config: ChunkingConfig | None = None,
    ) -> AgentTaskResponse:
        """Process in-memory document bytes and return a standardized AgentTaskResponse."""
        resolved_task_id = task_id or str(uuid.uuid4())
        target_next = next_agent or MemoriaAgentId.CONTEXT_UNDERSTANDING.value
        safe_name = sanitize_filename(filename)

        try:
            doc = self._controller.process_bytes(
                data,
                filename=filename,
                content_type=content_type,
                chunking_config=chunking_config,
                request_id=resolved_task_id,
            )
            return self._build_success_response(
                task_id=resolved_task_id,
                document=doc,
                next_agent=target_next,
            )
        except MemoriaReaderError as exc:
            return self._build_error_response(
                task_id=resolved_task_id,
                filename=safe_name,
                exc=exc,
            )
        except Exception:
            logger.exception("Unexpected error in agent execute_bytes", extra={"request_id": resolved_task_id})
            return self._build_unexpected_error_response(
                task_id=resolved_task_id,
                filename=safe_name,
            )

    async def execute_async_chunks(
        self,
        chunks: AsyncIterator[bytes],
        *,
        filename: str,
        content_type: str | None = None,
        task_id: str | None = None,
        next_agent: str | None = None,
        chunking_config: ChunkingConfig | None = None,
    ) -> AgentTaskResponse:
        """Process an async byte stream and return a standardized AgentTaskResponse."""
        resolved_task_id = task_id or str(uuid.uuid4())
        target_next = next_agent or MemoriaAgentId.CONTEXT_UNDERSTANDING.value
        safe_name = sanitize_filename(filename)

        try:
            doc = await self._controller.process_async_chunks(
                chunks,
                filename=filename,
                content_type=content_type,
                chunking_config=chunking_config,
                request_id=resolved_task_id,
            )
            return self._build_success_response(
                task_id=resolved_task_id,
                document=doc,
                next_agent=target_next,
            )
        except MemoriaReaderError as exc:
            return self._build_error_response(
                task_id=resolved_task_id,
                filename=safe_name,
                exc=exc,
            )
        except Exception:
            logger.exception("Unexpected error in agent execute_async_chunks", extra={"request_id": resolved_task_id})
            return self._build_unexpected_error_response(
                task_id=resolved_task_id,
                filename=safe_name,
            )

    def _build_success_response(
        self,
        *,
        task_id: str,
        document: NormalizedDocument,
        next_agent: str,
    ) -> AgentTaskResponse:
        return AgentTaskResponse(
            task_id=task_id,
            agent_id=self.agent_id,
            document_id=document.document_id,
            status=document.status,
            output_type="normalized_document",
            output=document,
            errors=[],
            metadata={
                "source_filename": document.filename,
                "document_type": document.document_type.value,
                "content_hash": document.source.content_hash,
                "byte_size": document.source.byte_size,
                "chunk_count": document.metadata.chunk_count,
                "block_count": document.metadata.block_count,
                "page_count": document.metadata.page_count,
                "processing_time_ms": document.processing_time_ms,
                "ocr_status": document.ocr.status.value,
            },
            next_agent=next_agent,
        )

    def _build_error_response(
        self,
        *,
        task_id: str,
        filename: str,
        exc: MemoriaReaderError,
    ) -> AgentTaskResponse:
        recoverable = not isinstance(exc, _NON_RECOVERABLE_ERRORS)
        return AgentTaskResponse(
            task_id=task_id,
            agent_id=self.agent_id,
            document_id=None,
            status=ExtractionStatus.FAILED,
            output_type="normalized_document",
            output=None,
            errors=[
                AgentError(
                    error_code=exc.error_code,
                    message=exc.message,
                    details=exc.details,
                    recoverable=recoverable,
                )
            ],
            metadata={"source_filename": filename},
            next_agent=MemoriaAgentId.ORCHESTRATOR.value,
        )

    def _build_unexpected_error_response(
        self,
        *,
        task_id: str,
        filename: str,
    ) -> AgentTaskResponse:
        return AgentTaskResponse(
            task_id=task_id,
            agent_id=self.agent_id,
            document_id=None,
            status=ExtractionStatus.FAILED,
            output_type="normalized_document",
            output=None,
            errors=[
                AgentError(
                    error_code="INTERNAL_SERVER_ERROR",
                    message="An unexpected internal error occurred while executing the agent task.",
                    details={},
                    recoverable=False,
                )
            ],
            metadata={"source_filename": filename},
            next_agent=MemoriaAgentId.ORCHESTRATOR.value,
        )

"""Inter-agent task execution endpoint for MemoriaOS orchestrators."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.dependencies import get_agent_service, get_app_settings
from app.api.upload_helpers import iter_upload_chunks, resolve_chunking_config
from app.core.config import Settings
from app.schemas.agent import AgentTaskResponse, MemoriaAgentId
from app.services.agent_service import DocumentReaderAgentService

router = APIRouter(prefix="/agent", tags=["Inter-Agent Communication"])


@router.post(
    "/execute",
    response_model=AgentTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute Document Reader Agent task and emit inter-agent envelope",
    description=(
        "Inter-agent HTTP contract callable by Agent 07 (Orchestrator) or external "
        "MemoriaOS workflows. Always returns a standardized AgentTaskResponse envelope "
        "with task_id, agent_id, document_id, status, output_type, output, errors, "
        "metadata, and next_agent."
    ),
)
async def execute_agent_task(
    file: Annotated[UploadFile, File(description="Document file to ingest.")],
    agent_service: Annotated[DocumentReaderAgentService, Depends(get_agent_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    task_id: Annotated[
        str | None,
        Query(description="Optional upstream Orchestrator task_id to propagate."),
    ] = None,
    next_agent: Annotated[
        MemoriaAgentId,
        Query(description="Target downstream MemoriaOS agent identifier."),
    ] = MemoriaAgentId.CONTEXT_UNDERSTANDING,
    chunk_size: Annotated[int | None, Query(ge=100, le=50000)] = None,
    chunk_overlap: Annotated[int | None, Query(ge=0, le=10000)] = None,
) -> AgentTaskResponse:
    """Run extraction + normalization and return the inter-agent AgentTaskResponse."""
    chunking_cfg = resolve_chunking_config(
        settings=settings,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return await agent_service.execute_async_chunks(
        iter_upload_chunks(file),
        filename=file.filename or "untitled",
        content_type=file.content_type,
        task_id=task_id,
        next_agent=next_agent.value,
        chunking_config=chunking_cfg,
    )

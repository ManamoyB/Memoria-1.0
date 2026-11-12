"""Standardized inter-agent communication schemas for MemoriaOS."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ExtractionStatus
from app.schemas.document import NormalizedDocument


class MemoriaAgentId(StrEnum):
    """Registered MemoriaOS agent identifiers for inter-agent routing."""

    DOCUMENT_READER = "agent-01-document-reader"
    CONTEXT_UNDERSTANDING = "agent-02-context-understanding"
    KNOWLEDGE_CLASSIFICATION = "agent-03-knowledge-classification"
    KNOWLEDGE_WRITER = "agent-04-knowledge-writer"
    KNOWLEDGE_GRAPH = "agent-05-knowledge-graph"
    QUALITY_VALIDATION = "agent-06-quality-validation"
    ORCHESTRATOR = "agent-07-orchestrator"


class AgentError(BaseModel):
    """Structured error entry inside an inter-agent task response."""

    model_config = ConfigDict(extra="forbid")

    error_code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    recoverable: bool = Field(default=False)


class AgentTaskResponse(BaseModel):
    """Standardized Pydantic v2 response envelope for MemoriaOS inter-agent communication.

    Every completed (or failed) Document Reader task emits this envelope so
    downstream LangGraph nodes or orchestrators (Agents 02–07) can route outputs
    deterministically without coupling to HTTP transport details.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique task execution identifier propagated across MemoriaOS agents.",
    )
    agent_id: str = Field(
        default=MemoriaAgentId.DOCUMENT_READER.value,
        description="Producing agent identifier.",
    )
    document_id: str | None = Field(
        default=None,
        description="Deterministic UUIDv5 derived from document SHA-256 content hash.",
    )
    status: ExtractionStatus
    output_type: str = Field(
        default="normalized_document",
        description="Semantic payload type discriminator for downstream agents.",
    )
    output: NormalizedDocument | None = Field(
        default=None,
        description="Normalized document payload when status is success or partial.",
    )
    errors: list[AgentError] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Compact task metadata (source references, counts, timing) for routing.",
    )
    next_agent: str | None = Field(
        default=MemoriaAgentId.CONTEXT_UNDERSTANDING.value,
        description="Recommended downstream MemoriaOS target agent.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

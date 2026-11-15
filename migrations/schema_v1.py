"""SQLAlchemy tables and connection lifecycle. No database access at import time."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
json_type = JSON().with_variant(JSONB, "postgresql")


def now() -> Any:
    return datetime.now(UTC)


def uid() -> Any:
    return str(uuid4())


users = Table(
    "users",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("created_at", DateTime(timezone=True)),
)
credentials = Table(
    "credentials",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False),
    Column("name", String(100)),
    Column("digest", String(64), unique=True, nullable=False),
    Column("scopes", json_type, nullable=False),
    Column("revoked", Boolean, default=False),
    Column("created_at", DateTime(timezone=True)),
)
agents = Table(
    "agents",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=True),
    Column("name", String(200)),
    Column("description", Text),
    Column("builtin", Boolean, default=False),
)
memories = Table(
    "memories",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False),
    Column("agent_id", ForeignKey("agents.id"), nullable=True),
    Column("fingerprint", String(64), nullable=False),
    Column("memory_type", String(30), nullable=False),
    Column("title", String(300), nullable=False),
    Column("content", Text, nullable=False),
    Column("summary", Text),
    Column("importance", Float),
    Column("confidence", Float),
    Column("relevance", Float),
    Column("status", String(30), nullable=False),
    Column("version", Integer, nullable=False),
    Column("data", json_type, nullable=False),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    Column("last_accessed_at", DateTime(timezone=True)),
    Column("valid_from", DateTime(timezone=True)),
    Column("valid_until", DateTime(timezone=True)),
    UniqueConstraint("user_id", "fingerprint", name="uq_memory_fingerprint"),
)
Index("ix_memory_owner_status_type", memories.c.user_id, memories.c.status, memories.c.memory_type)
versions = Table(
    "memory_versions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("memory_id", ForeignKey("memories.id", ondelete="CASCADE")),
    Column("version", Integer, nullable=False),
    Column("snapshot", json_type, nullable=False),
    Column("created_at", DateTime(timezone=True)),
    UniqueConstraint("memory_id", "version"),
)
sources = Table(
    "memory_sources",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("memory_id", ForeignKey("memories.id", ondelete="CASCADE")),
    Column("source_id", String(200), index=True),
    Column("data", json_type, nullable=False),
    UniqueConstraint("memory_id", "id"),
)
tags = Table(
    "memory_tags",
    metadata,
    Column("memory_id", ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True),
    Column("tag", String(200), primary_key=True),
)
memory_relationships = Table(
    "memory_relationships",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id")),
    Column("source_id", ForeignKey("memories.id", ondelete="CASCADE")),
    Column("target_id", ForeignKey("memories.id", ondelete="CASCADE")),
    Column("relationship_type", String(30)),
)
entities = Table(
    "entities",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False),
    Column("name", String(200)),
    Column("entity_type", String(30)),
    UniqueConstraint("user_id", "name", "entity_type"),
)
entity_relationships = Table(
    "entity_relationships",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False),
    Column("source_id", ForeignKey("entities.id")),
    Column("target_id", ForeignKey("entities.id")),
    Column("memory_id", ForeignKey("memories.id", ondelete="CASCADE")),
    Column("relationship_type", String(30)),
    Column("confidence", Float),
    Column("valid_from", DateTime(timezone=True)),
    Column("valid_until", DateTime(timezone=True)),
)
conversations = Table(
    "conversations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id")),
    Column("content", Text),
    Column("created_at", DateTime(timezone=True)),
)
jobs = Table(
    "ingestion_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False),
    Column("kind", String(30)),
    Column("status", String(30), nullable=False),
    Column("idempotency_key", String(200)),
    Column("input_hash", String(64)),
    Column("payload", json_type),
    Column("result", json_type),
    Column("error", Text),
    Column("attempts", Integer, default=0),
    Column("workflow_version", String(30)),
    Column("lease_token", String(36)),
    Column("lease_until", DateTime(timezone=True)),
    Column("available_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    UniqueConstraint("user_id", "idempotency_key"),
)
Index("ix_jobs_claim", jobs.c.status, jobs.c.available_at)
agent_tasks = Table(
    "agent_tasks",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id")),
    Column("job_id", ForeignKey("ingestion_jobs.id")),
    Column("agent_id", ForeignKey("agents.id")),
    Column("stage", String(100)),
    Column("status", String(30)),
    Column("output", json_type),
    Column("error", Text),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
)
consolidation_jobs = Table(
    "consolidation_jobs",
    metadata,
    Column("id", ForeignKey("ingestion_jobs.id"), primary_key=True),
    Column("report", json_type),
)
audit_logs = Table(
    "audit_logs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id")),
    Column("action", String(100)),
    Column("resource_id", String(200)),
    Column("details", json_type),
    Column("created_at", DateTime(timezone=True)),
)
system_settings = Table(
    "system_settings",
    metadata,
    Column("key", String(200), primary_key=True),
    Column("value", json_type),
    Column("updated_at", DateTime(timezone=True)),
)
conflicts = Table(
    "conflicts",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id")),
    Column("memory_id", ForeignKey("memories.id", ondelete="CASCADE")),
    Column("other_id", ForeignKey("memories.id", ondelete="CASCADE")),
    Column("status", String(30)),
    Column("resolution", String(30)),
    Column("created_at", DateTime(timezone=True)),
)
outbox = Table(
    "outbox",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id")),
    Column("memory_id", String(36)),
    Column("version", Integer),
    Column("target", String(30)),
    Column("status", String(30)),
    Column("attempts", Integer, default=0),
    Column("error", Text),
    Column("available_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    UniqueConstraint("memory_id", "version", "target"),
)

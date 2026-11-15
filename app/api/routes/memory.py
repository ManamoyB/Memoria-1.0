"""Authenticated MemoriaOS API. Business behavior stays in the memory engine."""

import hashlib
from typing import Any, cast

from fastapi import APIRouter, Depends, Header, Query, Request, UploadFile
from sqlalchemy import delete, func, insert, select, update

from app.api.dependencies import get_agent_service
from app.memory import database as db
from app.memory.contracts import (
    ConsolidationRequest,
    IngestionRequest,
    KeyRequest,
    MemoryInput,
    MemoryPatch,
    OperationalSettings,
    ReviewRequest,
    SearchRequest,
)
from app.memory.repository import MemoryError, serial
from app.memory.runtime import Runtime
from app.schemas.common import ExtractionStatus

router = APIRouter(tags=["Memory OS"])


def runtime(request: Request) -> Runtime:
    if not hasattr(request.app.state, "memory_runtime"):
        request.app.state.memory_runtime = Runtime()
    return cast(Runtime, request.app.state.memory_runtime)


def principal(request: Request) -> Any:
    identity = getattr(request.state, "principal", None)
    if not identity:
        raise MemoryError("Bearer credential required", "UNAUTHORIZED", 401)
    return identity


def scope(identity: Any, required: Any) -> Any:
    if "admin" not in identity["scopes"] and required not in identity["scopes"]:
        raise MemoryError("Credential lacks required scope", "FORBIDDEN", 403)
    return identity["user_id"]


_runtime_dependency = Depends(runtime)
_principal_dependency = Depends(principal)
_reader_dependency = Depends(get_agent_service)


@router.post("/memory", status_code=201)
def create_memory(
    body: MemoryInput, rt: Any = _runtime_dependency, who: Any = _principal_dependency
) -> Any:
    return rt.remember(scope(who, "write"), body)


@router.get("/memory")
def list_memories(
    status: str | None = "STORED",
    memory_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    rt: Any = _runtime_dependency,
    who: Any = _principal_dependency,
) -> Any:
    return rt.repo.list(
        scope(who, "read"), status=status, memory_type=memory_type, limit=limit, offset=offset
    )


@router.post("/search")
@router.post("/memory/retrieve")
@router.post("/memory/context")
def search(
    body: SearchRequest, rt: Any = _runtime_dependency, who: Any = _principal_dependency
) -> Any:
    return rt.retrieval.search(scope(who, "read"), body)


@router.get("/memory/{memory_id}")
def get_memory(
    memory_id: str, rt: Any = _runtime_dependency, who: Any = _principal_dependency
) -> Any:
    return rt.repo.get(scope(who, "read"), memory_id)


@router.patch("/memory/{memory_id}")
def patch_memory(
    memory_id: str,
    body: MemoryPatch,
    rt: Any = _runtime_dependency,
    who: Any = _principal_dependency,
) -> Any:
    user = scope(who, "write")
    rt.quality.execute(body.memory)
    result = rt.repo.revise(user, memory_id, body.expected_version, body.memory)
    rt.graph.connect(user, memory_id)
    return result


@router.delete("/memory/{memory_id}")
def delete_memory(
    memory_id: str,
    expected_version: int = Query(..., ge=1),
    rt: Any = _runtime_dependency,
    who: Any = _principal_dependency,
) -> Any:
    user = scope(who, "write")
    result = rt.repo.revise(user, memory_id, expected_version, status="DELETED")
    rt.graph.connect(user, memory_id)
    return result


@router.post("/memory/{memory_id}/archive")
def archive_memory(
    memory_id: str,
    expected_version: int = Query(..., ge=1),
    rt: Any = _runtime_dependency,
    who: Any = _principal_dependency,
) -> Any:
    user = scope(who, "write")
    return rt.repo.revise(user, memory_id, expected_version, status="ARCHIVED")


@router.post("/memory/{memory_id}/restore")
def restore_memory(
    memory_id: str,
    expected_version: int = Query(..., ge=1),
    rt: Any = _runtime_dependency,
    who: Any = _principal_dependency,
) -> Any:
    return rt.repo.revise(
        scope(who, "write"), memory_id, expected_version, status="WAITING_FOR_REVIEW"
    )


@router.delete("/memory/{memory_id}/purge")
def purge_memory(
    memory_id: str, rt: Any = _runtime_dependency, who: Any = _principal_dependency
) -> Any:
    rt.repo.purge(scope(who, "admin"), memory_id)
    return {"status": "PURGED", "note_policy": "Existing vault notes retained"}


@router.get("/memory/{memory_id}/history")
def history(memory_id: str, rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    return {"items": rt.repo.history(scope(who, "read"), memory_id)}


@router.post("/memory/{memory_id}/review")
def review(
    memory_id: str,
    body: ReviewRequest,
    rt: Any = _runtime_dependency,
    who: Any = _principal_dependency,
) -> Any:
    user = scope(who, "write")
    result = rt.repo.resolve(user, memory_id, body.action)
    rt.graph.connect(user, memory_id)
    return result


@router.get("/conflicts")
def conflicts(rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    user = scope(who, "read")
    with rt.database.engine.connect() as c:
        return {
            "items": serial(
                [
                    dict(r)
                    for r in c.execute(
                        select(db.conflicts).where(db.conflicts.c.user_id == user).limit(200)
                    ).mappings()
                ]
            )
        }


def submit_text(body: Any, rt: Any, who: Any, key: Any) -> Any:
    user = scope(who, "execute")
    source_id = hashlib.sha256((user + body.content).encode()).hexdigest()
    payload = {"content": body.content, "source_type": body.source_type, "source_id": source_id}
    # Bound model context; never silently discard input.
    payload["chunks"] = [
        {"text": body.content[i : i + 6000], "chunk_id": f"text-{i // 6000}"}
        for i in range(0, len(body.content), 6000)
    ]
    job = rt.repo.submit(user, "ingestion", payload, key)
    if body.source_type == "conversation":
        with rt.database.engine.begin() as c:
            if not c.execute(
                select(db.conversations).where(db.conversations.c.id == job["id"])
            ).first():
                c.execute(
                    insert(db.conversations).values(
                        id=job["id"], user_id=user, content=body.content, created_at=db.now()
                    )
                )
    return (rt.process(job["id"]) or job) if not body.background else job


@router.post("/ingestion", status_code=202)
def ingest(
    body: IngestionRequest,
    idempotency_key: str | None = Header(None),
    rt: Any = _runtime_dependency,
    who: Any = _principal_dependency,
) -> Any:
    return submit_text(body, rt, who, idempotency_key)


@router.post("/ingestion/conversation", status_code=202)
def conversation(
    body: IngestionRequest,
    idempotency_key: str | None = Header(None),
    rt: Any = _runtime_dependency,
    who: Any = _principal_dependency,
) -> Any:
    body.source_type = "conversation"
    return submit_text(body, rt, who, idempotency_key)


@router.post("/ingestion/document", status_code=202)
async def document(
    file: UploadFile,
    background: bool = True,
    idempotency_key: str | None = Header(None),
    rt: Any = _runtime_dependency,
    who: Any = _principal_dependency,
    reader: Any = _reader_dependency,
) -> Any:
    from starlette.concurrency import run_in_threadpool

    user = scope(who, "execute")

    # Preserve Agent 01's existing upload validation and bounded async streaming.
    async def chunks() -> Any:
        while chunk := await file.read(65536):
            yield chunk

    result = await reader.execute_async_chunks(
        chunks(), filename=file.filename or "upload.txt", content_type=file.content_type
    )
    await file.close()
    if result.status == ExtractionStatus.FAILED or result.output is None:
        raise MemoryError("Document extraction failed", "DOCUMENT_EXTRACTION_FAILED", 422)
    doc = result.output.model_dump(mode="json")
    payload = {
        "content": doc["content"],
        "chunks": doc["chunks"],
        "document_id": doc["document_id"],
        "source_id": doc["source"]["content_hash"],
        "source_type": "document",
        "document": doc,
    }
    job = await run_in_threadpool(rt.repo.submit, user, "ingestion", payload, idempotency_key)
    with rt.database.engine.begin() as c:
        if not c.execute(
            select(db.agent_tasks).where(
                db.agent_tasks.c.job_id == job["id"], db.agent_tasks.c.stage == "extract"
            )
        ).first():
            c.execute(
                insert(db.agent_tasks).values(
                    id=db.uid(),
                    user_id=user,
                    job_id=job["id"],
                    agent_id="agent-01-document-reader",
                    stage="extract",
                    status="COMPLETED",
                    output=result.model_dump(mode="json"),
                    started_at=db.now(),
                    completed_at=db.now(),
                )
            )
    return ((await run_in_threadpool(rt.process, job["id"])) or job) if not background else job


@router.get("/ingestion/{job_id}")
@router.get("/consolidation/jobs/{job_id}")
@router.get("/consolidation/report/{job_id}")
def job(job_id: str, rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    return rt.repo.job(scope(who, "read"), job_id)


@router.post("/ingestion/{job_id}/resume")
def resume(job_id: str, rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    user = scope(who, "execute")
    existing = rt.repo.job(user, job_id)
    if existing["status"] not in ("FAILED", "WAITING_FOR_REVIEW", "PARTIALLY_COMPLETED"):
        raise MemoryError("Job cannot be resumed in its current state", "CONFLICT", 409)
    memories = existing.get("result", {}).get("memories", [])
    if any(rt.repo.get(user, m["id"])["status"] == "WAITING_FOR_REVIEW" for m in memories):
        raise MemoryError("Resolve pending memory reviews before resuming", "CONFLICT", 409)
    with rt.database.engine.begin() as c:
        # Preserve expensive extraction/classification checkpoints; re-read actual writes and graph.
        c.execute(
            delete(db.agent_tasks).where(
                db.agent_tasks.c.job_id == job_id,
                db.agent_tasks.c.stage.in_(["write", "connect", "postflight"]),
            )
        )
        c.execute(
            update(db.jobs)
            .where(db.jobs.c.id == job_id)
            .values(status="PENDING", available_at=db.now(), error=None)
        )
    return rt.repo.job(user, job_id)


@router.post("/consolidation/run", status_code=202)
def consolidate(
    body: ConsolidationRequest, rt: Any = _runtime_dependency, who: Any = _principal_dependency
) -> Any:
    return rt.repo.submit(scope(who, "execute"), "consolidation", body.model_dump())


@router.get("/agents")
def agents(rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    user = scope(who, "read")
    with rt.database.engine.connect() as c:
        rows = [
            dict(r)
            for r in c.execute(
                select(db.agents).where(
                    db.agents.c.builtin.is_(True) | (db.agents.c.user_id == user)
                )
            ).mappings()
        ]
        for row in rows:
            tasks = (
                c.execute(
                    select(db.agent_tasks)
                    .where(db.agent_tasks.c.agent_id == row["id"], db.agent_tasks.c.user_id == user)
                    .order_by(db.agent_tasks.c.started_at.desc())
                )
                .mappings()
                .all()
            )
            row.update(
                execution_count=len(tasks),
                failure_count=sum(t["status"] == "FAILED" for t in tasks),
                last_execution=serial(dict(tasks[0])) if tasks else None,
                status=tasks[0]["status"] if tasks else "IDLE",
            )
    return {"items": serial(rows)}


@router.post("/agents/register")
def register(
    body: KeyRequest, rt: Any = _runtime_dependency, who: Any = _principal_dependency
) -> Any:
    user = scope(who, "admin")
    aid = db.uid()
    key = rt.repo.issue_key(user, body.name, body.scopes)
    with rt.database.engine.begin() as c:
        c.execute(
            insert(db.agents).values(
                id=aid,
                user_id=user,
                name=body.name,
                description="External API client",
                builtin=False,
            )
        )
    return {"agent_id": aid, "credential": key}


@router.get("/agents/tasks/{task_id}")
def task(task_id: str, rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    user = scope(who, "read")
    with rt.database.engine.connect() as c:
        row = (
            c.execute(
                select(db.agent_tasks).where(
                    db.agent_tasks.c.id == task_id, db.agent_tasks.c.user_id == user
                )
            )
            .mappings()
            .first()
        )
        if not row:
            raise MemoryError("Task not found", "NOT_FOUND", 404)
        return serial(dict(row))


@router.get("/agents/{agent_id}")
def agent(agent_id: str, rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    found = next((a for a in agents(rt, who)["items"] if a["id"] == agent_id), None)
    if not found:
        raise MemoryError("Agent not found", "NOT_FOUND", 404)
    with rt.database.engine.connect() as c:
        found["history"] = serial(
            [
                dict(r)
                for r in c.execute(
                    select(db.agent_tasks)
                    .where(
                        db.agent_tasks.c.agent_id == agent_id,
                        db.agent_tasks.c.user_id == who["user_id"],
                    )
                    .order_by(db.agent_tasks.c.started_at.desc())
                    .limit(50)
                ).mappings()
            ]
        )
    return found


@router.post("/agents/{agent_id}/execute", status_code=202)
def execute_agent(
    agent_id: str,
    body: IngestionRequest,
    rt: Any = _runtime_dependency,
    who: Any = _principal_dependency,
) -> Any:
    record = agent(agent_id, rt, who)
    if not record["builtin"]:
        raise MemoryError("External agents are API identities, not executable server code")
    # Manual dispatch always uses the complete validated workflow, never privileged stage bypass.
    return submit_text(body, rt, who, None)


@router.get("/graph/entities")
@router.get("/graph/relationships")
def graph(rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    return rt.graph.explore(scope(who, "read"))


@router.get("/graph/entities/{entity_id}")
def entity(entity_id: str, rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    return rt.graph.explore(scope(who, "read"), entity_id)


@router.post("/graph/query")
def graph_query(
    entity_id: str | None = None, rt: Any = _runtime_dependency, who: Any = _principal_dependency
) -> Any:
    return rt.graph.explore(scope(who, "read"), entity_id)


@router.get("/system/metrics")
def metrics(rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    user = scope(who, "read")
    with rt.database.engine.connect() as c:
        counts = dict(
            c.execute(
                select(db.memories.c.memory_type, func.count())
                .where(db.memories.c.user_id == user, db.memories.c.status == "STORED")
                .group_by(db.memories.c.memory_type)
            ).all()
        )
        recent = serial(
            [
                dict(r)
                for r in c.execute(
                    select(db.jobs)
                    .where(db.jobs.c.user_id == user)
                    .order_by(db.jobs.c.created_at.desc())
                    .limit(20)
                ).mappings()
            ]
        )
        # Never return job inputs through operational metrics.
        for item in recent:
            item.pop("payload", None)
        documents = c.execute(
            select(func.count())
            .select_from(db.agent_tasks)
            .where(db.agent_tasks.c.user_id == user, db.agent_tasks.c.stage == "extract")
        ).scalar_one()
        pending = c.execute(
            select(func.count())
            .select_from(db.memories)
            .where(db.memories.c.user_id == user, db.memories.c.status == "WAITING_FOR_REVIEW")
        ).scalar_one()
    return {
        "total_memories": sum(counts.values()),
        "by_type": counts,
        "documents": documents,
        "pending_review": pending,
        "recent_jobs": recent,
    }


@router.get("/system/providers")
@router.get("/system/status")
def health(rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    scope(who, "read")
    result = {}
    for name, check in (("ollama", rt.llm.health), ("qdrant", rt.index.health)):
        try:
            result[name] = check()
        except Exception:
            result[name] = {"available": False}
    try:
        with rt.database.engine.connect() as c:
            c.execute(select(db.users.c.id).limit(1))
        result["database"] = {"available": True}
    except Exception:
        result["database"] = {"available": False}
    result["obsidian"] = obsidian_status(rt, who)
    return result


@router.get("/system/config")
def config(rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    scope(who, "admin")
    return {
        "infrastructure": rt.settings.public(),
        "operational": rt.repo.settings().model_dump(),
        "infrastructure_update": "Edit environment and restart; embedding changes require reindex",
    }


@router.patch("/system/config")
def settings(
    body: OperationalSettings, rt: Any = _runtime_dependency, who: Any = _principal_dependency
) -> Any:
    user = scope(who, "admin")
    rt.repo.set_setting("operational", body.model_dump())
    with rt.database.engine.begin() as c:
        rt.repo.audit(c, user, "settings.updated", "operational", body.model_dump())
    return body


@router.get("/obsidian/status")
def obsidian_status(rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    user = scope(who, "read")
    enabled = rt.settings.obsidian_enabled and user == rt.settings.owner_id
    available = False
    if enabled:
        try:
            available = rt.vault.root() is not None
        except MemoryError:
            pass
    with rt.database.engine.connect() as c:
        counts = dict(
            c.execute(
                select(db.outbox.c.status, func.count())
                .where(db.outbox.c.user_id == user, db.outbox.c.target == "obsidian")
                .group_by(db.outbox.c.status)
            ).all()
        )
    return {
        "enabled": enabled,
        "available": available,
        "writes": counts,
        "vault_path": str(rt.settings.obsidian_vault_path) if enabled else None,
        "policy": "Immutable revision notes; existing notes are never overwritten",
    }


@router.post("/obsidian/sync")
def sync(rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    return rt.sync.run(scope(who, "execute"), force=True)


@router.post("/obsidian/reconcile")
def reconcile(rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    return rt.sync.reconcile(scope(who, "execute"))


@router.post("/credentials", status_code=201)
def credential(
    body: KeyRequest, rt: Any = _runtime_dependency, who: Any = _principal_dependency
) -> Any:
    return rt.repo.issue_key(scope(who, "admin"), body.name, body.scopes)


@router.get("/credentials")
def credentials(rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    user = scope(who, "admin")
    with rt.database.engine.connect() as c:
        return {
            "items": serial(
                [
                    dict(r)
                    for r in c.execute(
                        select(
                            db.credentials.c.id,
                            db.credentials.c.name,
                            db.credentials.c.scopes,
                            db.credentials.c.revoked,
                        ).where(db.credentials.c.user_id == user)
                    ).mappings()
                ]
            )
        }


@router.delete("/credentials/{key_id}")
def revoke(key_id: str, rt: Any = _runtime_dependency, who: Any = _principal_dependency) -> Any:
    user = scope(who, "admin")
    with rt.database.engine.begin() as c:
        c.execute(
            update(db.credentials)
            .where(db.credentials.c.id == key_id, db.credentials.c.user_id == user)
            .values(revoked=True)
        )
        rt.repo.audit(c, user, "credential.revoked", key_id)
    return {"status": "REVOKED"}

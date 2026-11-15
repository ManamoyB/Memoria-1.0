"""Transactional persistence boundary, scoped by authenticated principal."""

import hashlib
import json
import secrets
from datetime import timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import and_, delete, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.memory import database as db
from app.memory.contracts import MemoryInput, OperationalSettings
from app.schemas.agent import MemoriaAgentId


class MemoryError(Exception):
    def __init__(self, message: Any, code: Any = "INVALID_OPERATION", status: Any = 400) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def serial(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def digest(value: Any) -> Any:
    return hashlib.sha256(value.encode()).hexdigest()


def fingerprint(candidate: Any) -> Any:
    return digest(
        candidate.memory_type.value + ":" + " ".join(candidate.content.casefold().split())
    )


class Repository:
    def __init__(self, database: Any) -> None:
        self.db = database

    def bootstrap(self, user_id: Any, name: Any = "Local owner") -> None:
        with self.db.engine.begin() as c:
            if not c.execute(select(db.users).where(db.users.c.id == user_id)).first():
                c.execute(insert(db.users).values(id=user_id, name=name, created_at=db.now()))
            for agent in MemoriaAgentId:
                if not c.execute(select(db.agents).where(db.agents.c.id == agent.value)).first():
                    c.execute(
                        insert(db.agents).values(
                            id=agent.value,
                            builtin=True,
                            name=agent.name.replace("_", " ").title(),
                            description=agent.value,
                        )
                    )

    def issue_key(self, user: Any, name: Any, scopes: Any) -> Any:
        token = "mem_" + secrets.token_urlsafe(32)
        key_id = db.uid()
        with self.db.engine.begin() as c:
            c.execute(
                insert(db.credentials).values(
                    id=key_id,
                    user_id=user,
                    name=name,
                    digest=digest(token),
                    scopes=scopes,
                    revoked=False,
                    created_at=db.now(),
                )
            )
            self.audit(c, user, "credential.created", key_id)
        return {"id": key_id, "token": token, "scopes": scopes}

    def authenticate(self, token: Any) -> Any:
        with self.db.engine.connect() as c:
            row = (
                c.execute(
                    select(db.credentials).where(
                        db.credentials.c.digest == digest(token),
                        db.credentials.c.revoked.is_(False),
                    )
                )
                .mappings()
                .first()
            )
            if not row:
                raise MemoryError("Invalid or revoked credential", "UNAUTHORIZED", 401)
            return dict(row)

    def audit(self, c: Any, user: Any, action: Any, resource: Any, details: Any = None) -> None:
        c.execute(
            insert(db.audit_logs).values(
                id=db.uid(),
                user_id=user,
                action=action,
                resource_id=resource,
                details=details or {},
                created_at=db.now(),
            )
        )

    def settings(self) -> Any:
        with self.db.engine.connect() as c:
            row = c.execute(
                select(db.system_settings.c.value).where(db.system_settings.c.key == "operational")
            ).scalar_one_or_none()
        return OperationalSettings.model_validate(row or {})

    def set_setting(self, key: Any, value: Any) -> None:
        with self.db.engine.begin() as c:
            exists = c.execute(
                select(db.system_settings).where(db.system_settings.c.key == key)
            ).first()
            if exists:
                c.execute(
                    update(db.system_settings)
                    .where(db.system_settings.c.key == key)
                    .values(value=value, updated_at=db.now())
                )
            else:
                c.execute(
                    insert(db.system_settings).values(key=key, value=value, updated_at=db.now())
                )

    def get_setting(self, key: Any) -> Any:
        with self.db.engine.connect() as c:
            return c.execute(
                select(db.system_settings.c.value).where(db.system_settings.c.key == key)
            ).scalar_one_or_none()

    def _get(self, c: Any, user: Any, memory_id: Any) -> Any:
        row = (
            c.execute(
                select(db.memories).where(
                    db.memories.c.id == memory_id, db.memories.c.user_id == user
                )
            )
            .mappings()
            .first()
        )
        if not row:
            raise MemoryError("Memory not found", "NOT_FOUND", 404)
        return dict(row)

    def get(self, user: Any, memory_id: Any) -> Any:
        with self.db.engine.connect() as c:
            return serial(self._get(c, user, memory_id))

    def list(
        self,
        user: Any,
        *,
        status: Any = "STORED",
        memory_type: Any = None,
        limit: Any = 50,
        offset: Any = 0,
    ) -> Any:
        query = select(db.memories).where(db.memories.c.user_id == user)
        if status:
            query = query.where(db.memories.c.status == status)
        if memory_type:
            query = query.where(db.memories.c.memory_type == memory_type)
        with self.db.engine.connect() as c:
            count = c.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows = (
                c.execute(
                    query.order_by(db.memories.c.updated_at.desc(), db.memories.c.id)
                    .limit(limit)
                    .offset(offset)
                )
                .mappings()
                .all()
            )
        return {
            "items": serial([dict(r) for r in rows]),
            "total": count,
            "limit": limit,
            "offset": offset,
        }

    def _snapshot(self, c: Any, row: Any) -> None:
        c.execute(
            insert(db.versions).values(
                id=db.uid(),
                memory_id=row["id"],
                version=row["version"],
                snapshot=serial(row),
                created_at=db.now(),
            )
        )
        for target in ("vector", "obsidian"):
            c.execute(
                insert(db.outbox).values(
                    id=db.uid(),
                    user_id=row["user_id"],
                    memory_id=row["id"],
                    version=row["version"],
                    target=target,
                    status="PENDING",
                    attempts=0,
                    available_at=db.now(),
                    created_at=db.now(),
                )
            )

    def _provenance(self, c: Any, memory_id: Any, candidate: Any) -> None:
        c.execute(delete(db.tags).where(db.tags.c.memory_id == memory_id))
        for tag in sorted(set(candidate.tags)):
            if len(tag) > 200:
                raise MemoryError("Tag exceeds 200 characters")
            c.execute(insert(db.tags).values(memory_id=memory_id, tag=tag))
        for source in candidate.sources:
            source_data = source.model_dump(mode="json")
            sid = str(uuid5(NAMESPACE_URL, memory_id + json.dumps(source_data, sort_keys=True)))
            if not c.execute(select(db.sources.c.id).where(db.sources.c.id == sid)).first():
                c.execute(
                    insert(db.sources).values(
                        id=sid, memory_id=memory_id, source_id=source.source_id, data=source_data
                    )
                )

    def create(self, user: Any, candidate: MemoryInput, agent_id: Any = None) -> Any:
        settings = self.settings()
        if candidate.confidence < settings.minimum_confidence or candidate.inferred:
            initial = "WAITING_FOR_REVIEW"
        else:
            initial = "STORED"
        fp = fingerprint(candidate)
        try:
            with self.db.engine.begin() as c:
                # Serializes writes per owner, including conflict detection on PostgreSQL.
                c.execute(
                    select(db.users.c.id).where(db.users.c.id == user).with_for_update()
                ).first()
                existing = (
                    c.execute(
                        select(db.memories).where(
                            db.memories.c.user_id == user, db.memories.c.fingerprint == fp
                        )
                    )
                    .mappings()
                    .first()
                )
                if existing:
                    # Keep every source on duplicate ingestion without altering the original fact.
                    combined = MemoryInput.model_validate(existing["data"])
                    known = {s.model_dump_json() for s in combined.sources}
                    combined.sources.extend(
                        s for s in candidate.sources if s.model_dump_json() not in known
                    )
                    if len(combined.sources) != len(existing["data"]["sources"]):
                        return self._revise(c, user, dict(existing), combined, existing["status"])
                    return serial(dict(existing)) | {"duplicate": True}
                others = []
                if candidate.subject and candidate.predicate and candidate.object:
                    rows = c.execute(
                        select(db.memories).where(
                            db.memories.c.user_id == user, db.memories.c.status == "STORED"
                        )
                    ).mappings()
                    for row in rows:
                        data = row["data"]
                        if (
                            data.get("subject", "").casefold() == candidate.subject.casefold()
                            and data.get("predicate", "").casefold()
                            == candidate.predicate.casefold()
                            and data.get("object", "").casefold() != candidate.object.casefold()
                        ):
                            others.append(dict(row))
                if others:
                    initial = "WAITING_FOR_REVIEW"
                row = dict(
                    id=db.uid(),
                    user_id=user,
                    agent_id=agent_id,
                    fingerprint=fp,
                    memory_type=candidate.memory_type.value,
                    title=candidate.title,
                    content=candidate.content,
                    summary=candidate.summary,
                    importance=candidate.importance,
                    confidence=candidate.confidence,
                    relevance=candidate.relevance,
                    status=initial,
                    version=1,
                    data=candidate.model_dump(mode="json"),
                    created_at=db.now(),
                    updated_at=db.now(),
                    valid_from=candidate.valid_from,
                    valid_until=candidate.valid_until,
                )
                c.execute(insert(db.memories).values(**row))
                self._provenance(c, row["id"], candidate)
                self._snapshot(c, row)
                for other in others:
                    c.execute(
                        insert(db.conflicts).values(
                            id=db.uid(),
                            user_id=user,
                            memory_id=row["id"],
                            other_id=other["id"],
                            status="OPEN",
                            created_at=db.now(),
                        )
                    )
                self.audit(c, user, "memory.created", row["id"], {"status": initial})
            if others and settings.conflict_policy != "review" and not candidate.inferred:
                return self.resolve(user, row["id"], settings.conflict_policy)
            return serial(row)
        except IntegrityError as exc:
            with self.db.engine.connect() as c:
                existing = (
                    c.execute(
                        select(db.memories).where(
                            db.memories.c.user_id == user, db.memories.c.fingerprint == fp
                        )
                    )
                    .mappings()
                    .first()
                )
            if existing:
                return self.create(user, candidate, agent_id)
            raise MemoryError("Concurrent write conflict; retry", "CONFLICT", 409) from exc

    def _revise(self, c: Any, user: Any, old: Any, candidate: Any, status: Any) -> Any:
        row = old | dict(
            fingerprint=fingerprint(candidate),
            memory_type=candidate.memory_type.value,
            title=candidate.title,
            content=candidate.content,
            summary=candidate.summary,
            importance=candidate.importance,
            confidence=candidate.confidence,
            relevance=candidate.relevance,
            data=candidate.model_dump(mode="json"),
            status=status,
            version=old["version"] + 1,
            updated_at=db.now(),
            valid_from=candidate.valid_from,
            valid_until=candidate.valid_until,
        )
        result = c.execute(
            update(db.memories)
            .where(
                db.memories.c.id == old["id"],
                db.memories.c.user_id == user,
                db.memories.c.version == old["version"],
            )
            .values(**row)
        )
        if result.rowcount != 1:
            raise MemoryError("Memory changed; reload before updating", "VERSION_CONFLICT", 409)
        self._provenance(c, old["id"], candidate)
        self._snapshot(c, row)
        self.audit(
            c, user, "memory.revised", old["id"], {"version": row["version"], "status": status}
        )
        return serial(row)

    def revise(
        self, user: Any, memory_id: Any, version: Any, candidate: Any = None, status: Any = None
    ) -> Any:
        with self.db.engine.begin() as c:
            c.execute(select(db.users.c.id).where(db.users.c.id == user).with_for_update()).first()
            old = self._get(c, user, memory_id)
            if old["version"] != version:
                raise MemoryError("Memory changed; reload before updating", "VERSION_CONFLICT", 409)
            resolved = candidate or MemoryInput.model_validate(old["data"])
            # Changed claims require review. Explicit review is the only activation path.
            target_status = status or ("WAITING_FOR_REVIEW" if candidate else old["status"])
            return self._revise(c, user, old, resolved, target_status)

    def resolve(self, user: Any, memory_id: Any, action: Any) -> Any:
        with self.db.engine.begin() as c:
            c.execute(select(db.users.c.id).where(db.users.c.id == user).with_for_update()).first()
            row = self._get(c, user, memory_id)
            if row["status"] != "WAITING_FOR_REVIEW":
                raise MemoryError("Memory is not awaiting review", "CONFLICT", 409)
            links = (
                c.execute(
                    select(db.conflicts).where(
                        db.conflicts.c.user_id == user,
                        db.conflicts.c.memory_id == memory_id,
                        db.conflicts.c.status == "OPEN",
                    )
                )
                .mappings()
                .all()
            )
            others = [self._get(c, user, link["other_id"]) for link in links]
            if action == "higher_confidence" and any(
                o["confidence"] >= row["confidence"] for o in others
            ):
                raise MemoryError("Candidate does not have higher confidence", "CONFLICT", 409)
            if action in ("supersede", "higher_confidence"):
                for other in others:
                    self._revise(
                        c, user, other, MemoryInput.model_validate(other["data"]), "SUPERSEDED"
                    )
                    c.execute(
                        insert(db.memory_relationships).values(
                            id=db.uid(),
                            user_id=user,
                            source_id=memory_id,
                            target_id=other["id"],
                            relationship_type="SUPERSEDES",
                        )
                    )
            status = "REJECTED" if action == "reject" else "STORED"
            result = self._revise(c, user, row, MemoryInput.model_validate(row["data"]), status)
            c.execute(
                update(db.conflicts)
                .where(
                    db.conflicts.c.user_id == user,
                    db.conflicts.c.memory_id == memory_id,
                    db.conflicts.c.status == "OPEN",
                )
                .values(status="RESOLVED", resolution=action)
            )
            self.audit(c, user, "memory.reviewed", memory_id, {"action": action})
            return result

    def history(self, user: Any, memory_id: Any) -> Any:
        with self.db.engine.connect() as c:
            self._get(c, user, memory_id)
            return list(
                c.execute(
                    select(db.versions.c.snapshot)
                    .where(db.versions.c.memory_id == memory_id)
                    .order_by(db.versions.c.version)
                ).scalars()
            )

    def merge(
        self, user: str, survivor: dict[str, Any], original: dict[str, Any], candidate: MemoryInput
    ) -> dict[str, Any]:
        """Merge, archive, link, and enqueue both revisions in one transaction."""
        with self.db.engine.begin() as c:
            c.execute(select(db.users.c.id).where(db.users.c.id == user).with_for_update()).first()
            first = self._get(c, user, survivor["id"])
            second = self._get(c, user, original["id"])
            if (
                first["version"] != survivor["version"]
                or second["version"] != original["version"]
                or first["status"] != "STORED"
                or second["status"] != "STORED"
            ):
                raise MemoryError("Memory changed during consolidation", "VERSION_CONFLICT", 409)
            result = self._revise(c, user, first, candidate, "STORED")
            self._revise(c, user, second, MemoryInput.model_validate(second["data"]), "ARCHIVED")
            c.execute(
                insert(db.memory_relationships).values(
                    id=db.uid(),
                    user_id=user,
                    source_id=first["id"],
                    target_id=second["id"],
                    relationship_type="SUPERSEDES",
                )
            )
            return dict(result)

    def purge(self, user: Any, memory_id: Any) -> None:
        with self.db.engine.begin() as c:
            c.execute(select(db.users.c.id).where(db.users.c.id == user).with_for_update()).first()
            row = self._get(c, user, memory_id)
            if row["status"] != "DELETED":
                raise MemoryError("Soft-delete the memory before purging")
            c.execute(delete(db.memories).where(db.memories.c.id == memory_id))
            c.execute(
                insert(db.outbox).values(
                    id=db.uid(),
                    user_id=user,
                    memory_id=memory_id,
                    version=row["version"] + 1,
                    target="vector",
                    status="PENDING",
                    attempts=0,
                    available_at=db.now(),
                    created_at=db.now(),
                )
            )
            self.audit(c, user, "memory.purged", memory_id)

    def submit(self, user: Any, kind: Any, payload: Any, key: Any = None) -> Any:
        key = key or db.uid()
        hashed = digest(json.dumps(payload, sort_keys=True))
        with self.db.engine.begin() as c:
            c.execute(select(db.users.c.id).where(db.users.c.id == user).with_for_update()).first()
            existing = (
                c.execute(
                    select(db.jobs).where(
                        db.jobs.c.user_id == user, db.jobs.c.idempotency_key == key
                    )
                )
                .mappings()
                .first()
            )
            if existing:
                if existing["input_hash"] != hashed or existing["kind"] != kind:
                    raise MemoryError(
                        "Idempotency key already used for another request", "CONFLICT", 409
                    )
                return serial(dict(existing))
            row = dict(
                id=db.uid(),
                user_id=user,
                kind=kind,
                payload=payload,
                status="PENDING",
                idempotency_key=key,
                input_hash=hashed,
                attempts=0,
                workflow_version="1.0",
                available_at=db.now(),
                created_at=db.now(),
                result={},
            )
            c.execute(insert(db.jobs).values(**row))
            return serial(row)

    def job(self, user: Any, job_id: Any) -> Any:
        with self.db.engine.connect() as c:
            row = (
                c.execute(select(db.jobs).where(db.jobs.c.id == job_id, db.jobs.c.user_id == user))
                .mappings()
                .first()
            )
            if not row:
                raise MemoryError("Job not found", "NOT_FOUND", 404)
            return serial(dict(row))

    def claim(self, job_id: Any = None) -> Any:
        eligible = or_(
            and_(db.jobs.c.status.in_(["PENDING", "RETRYING"]), db.jobs.c.available_at <= db.now()),
            and_(db.jobs.c.status == "RUNNING", db.jobs.c.lease_until < db.now()),
        )
        with self.db.engine.begin() as c:
            q = select(db.jobs).where(eligible).order_by(db.jobs.c.created_at)
            if job_id:
                q = q.where(db.jobs.c.id == job_id)
            row = c.execute(q.with_for_update(skip_locked=True).limit(1)).mappings().first()
            if not row:
                return None
            token = db.uid()
            changed = c.execute(
                update(db.jobs)
                .where(db.jobs.c.id == row["id"], eligible)
                .values(
                    status="RUNNING",
                    lease_token=token,
                    lease_until=db.now() + timedelta(minutes=5),
                    attempts=row["attempts"] + 1,
                    started_at=db.now(),
                    error=None,
                )
            )
            return (
                (dict(row) | {"lease_token": token, "attempts": row["attempts"] + 1})
                if changed.rowcount
                else None
            )

    def heartbeat(self, job: Any) -> None:
        with self.db.engine.begin() as c:
            result = c.execute(
                update(db.jobs)
                .where(db.jobs.c.id == job["id"], db.jobs.c.lease_token == job["lease_token"])
                .values(lease_until=db.now() + timedelta(minutes=5))
            )
            if not result.rowcount:
                raise MemoryError("Job lease lost", "LEASE_LOST", 409)

    def finish(self, job: Any, status: Any, result: Any = None, error: Any = None) -> None:
        with self.db.engine.begin() as c:
            c.execute(
                update(db.jobs)
                .where(db.jobs.c.id == job["id"], db.jobs.c.lease_token == job["lease_token"])
                .values(
                    status=status,
                    result=result or {},
                    error=error,
                    lease_token=None,
                    lease_until=None,
                    available_at=db.now() + timedelta(seconds=2 ** job["attempts"]),
                    completed_at=None if status == "RETRYING" else db.now(),
                )
            )

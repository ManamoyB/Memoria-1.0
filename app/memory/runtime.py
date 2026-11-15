"""Composition root and durable worker; independent of the HTTP framework."""

import logging
import threading
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import insert, select, update

from app.memory import database as db
from app.memory.agents import ClassificationAgent, ContextAgent, QualityAgent, WriterAgent
from app.memory.config import MemorySettings
from app.memory.contracts import MemoryInput
from app.memory.graph import KnowledgeGraph
from app.memory.orchestrator import Orchestrator
from app.memory.providers import OllamaProvider, QdrantIndex
from app.memory.repository import MemoryError, Repository
from app.memory.retrieval import Retrieval
from app.memory.synchronization import Synchronizer, VaultExporter

logger = logging.getLogger(__name__)


class Runtime:
    def __init__(
        self,
        settings: Any = None,
        database: Any = None,
        llm: Any = None,
        embeddings: Any = None,
        index: Any = None,
    ) -> None:
        self.settings = settings or MemorySettings()
        self.database = database or db.Database(self.settings.database_url.get_secret_value())
        self.repo = Repository(self.database)
        self.llm = llm or OllamaProvider(self.settings)
        self.embeddings = embeddings or self.llm
        self.index = index or QdrantIndex(self.settings, self.repo)
        self.quality = QualityAgent()
        self.writer = WriterAgent(self.repo, self.quality)
        self.graph = KnowledgeGraph(self.repo)
        self.orchestrator = Orchestrator(
            self.repo,
            ContextAgent(self.llm),
            ClassificationAgent(self.llm),
            self.quality,
            self.writer,
            self.graph,
        )
        self.vault = VaultExporter(self.settings, self.repo)
        self.sync = Synchronizer(self.repo, self.embeddings, self.index, self.vault)
        self.retrieval = Retrieval(self.repo, self.embeddings, self.index)

    def remember(self, user: Any, candidate: Any) -> Any:
        memory = self.writer.execute(user, candidate)
        self.graph.connect(user, memory["id"])
        return memory

    def consolidate(self, user: Any, payload: Any) -> Any:
        rows = self.repo.list(user, limit=payload.get("limit", 500))["items"]
        report = {
            "examined": len(rows),
            "duplicate_candidates": [],
            "merged": [],
            "conflicts": [],
            "archived": [],
            "errors": [],
            "dry_run": payload.get("dry_run", True),
        }
        settings = self.repo.settings()
        handled = set()
        for index, row in enumerate(rows):
            for other in rows[index + 1 :]:
                if row["memory_type"] != other["memory_type"]:
                    continue
                similarity = SequenceMatcher(
                    None, row["content"].casefold(), other["content"].casefold()
                ).ratio()
                if similarity < 0.85:
                    continue
                report["duplicate_candidates"].append(
                    {"ids": [row["id"], other["id"]], "similarity": similarity}
                )
                a, b = row["data"], other["data"]
                # Only merge equivalent explicit structured claims, not mere vector similarity.
                compatible = (
                    a.get("subject")
                    and a.get("predicate")
                    and a.get("object")
                    and all(
                        a.get(k) == b.get(k)
                        for k in ("subject", "predicate", "object", "valid_from", "valid_until")
                    )
                    and not a["inferred"]
                    and not b["inferred"]
                )
                if not compatible:
                    report["conflicts"].append([row["id"], other["id"]])
                    continue
                if report["dry_run"] or other["id"] in handled or row["id"] in handled:
                    continue
                try:
                    candidate = MemoryInput.model_validate(a)
                    candidate.sources.extend(
                        s
                        for s in MemoryInput.model_validate(b).sources
                        if s not in candidate.sources
                    )
                    # Extractive summary, retaining the exact original claim.
                    candidate.summary = candidate.content[:5000]
                    candidate.metadata = candidate.metadata | {
                        "consolidated_from": [row["id"], other["id"]]
                    }
                    updated = self.repo.merge(user, row, other, candidate)
                    row.update(updated)
                    handled.add(other["id"])
                    report["merged"].append([row["id"], other["id"]])
                except (MemoryError, ValueError):
                    report["errors"].append(
                        {"memory_id": row["id"], "error": "Merge requires review"}
                    )
            expired = (
                row["valid_until"]
                and datetime.fromisoformat(row["valid_until"]).replace(tzinfo=UTC) < db.now()
            )
            old = settings.retention_days and datetime.fromisoformat(row["updated_at"]).replace(
                tzinfo=UTC
            ) < db.now() - timedelta(days=settings.retention_days)
            if (expired or old) and row["data"]["expiration_policy"] == "archive":
                report["archived"].append(row["id"])
                if not report["dry_run"] and row["id"] not in handled:
                    self.repo.revise(user, row["id"], row["version"], status="ARCHIVED")
        return report

    def process(self, job_id: Any = None) -> Any:
        job = self.repo.claim(job_id)
        if not job:
            return None
        if job["attempts"] > self.settings.max_attempts:
            self.repo.finish(job, "FAILED", error="RETRY_LIMIT_EXCEEDED")
            return self.repo.job(job["user_id"], job["id"])
        stopped = threading.Event()

        def renew() -> Any:
            while not stopped.wait(30):
                try:
                    self.repo.heartbeat(job)
                except Exception:
                    return

        heartbeat = threading.Thread(target=renew, daemon=True)
        orchestrator_task = db.uid()
        with self.database.engine.begin() as c:
            c.execute(
                insert(db.agent_tasks).values(
                    id=orchestrator_task,
                    user_id=job["user_id"],
                    job_id=job["id"],
                    agent_id="agent-07-orchestrator",
                    stage=job["kind"],
                    status="RUNNING",
                    started_at=db.now(),
                )
            )
        heartbeat.start()
        try:
            if job["kind"] == "consolidation":
                result = self.consolidate(job["user_id"], job["payload"])
                with self.database.engine.begin() as c:
                    if c.execute(
                        select(db.consolidation_jobs).where(db.consolidation_jobs.c.id == job["id"])
                    ).first():
                        c.execute(
                            update(db.consolidation_jobs)
                            .where(db.consolidation_jobs.c.id == job["id"])
                            .values(report=result)
                        )
                    else:
                        c.execute(insert(db.consolidation_jobs).values(id=job["id"], report=result))
                status = "PARTIALLY_COMPLETED" if result["errors"] else "COMPLETED"
            else:
                result = self.orchestrator.execute(job)
                status = (
                    "WAITING_FOR_REVIEW"
                    if any(m["status"] == "WAITING_FOR_REVIEW" for m in result["memories"])
                    else "COMPLETED"
                )
            sync_result = self.sync.run(job["user_id"])
            result["synchronization"] = sync_result
            if sync_result["failed"] and status == "COMPLETED":
                status = "PARTIALLY_COMPLETED"
            self.repo.finish(job, status, result)
            with self.database.engine.begin() as c:
                c.execute(
                    update(db.agent_tasks)
                    .where(db.agent_tasks.c.id == orchestrator_task)
                    .values(status=status, completed_at=db.now())
                )
        except Exception as exc:
            recoverable = isinstance(exc, MemoryError) and exc.status >= 500
            status = (
                "RETRYING"
                if recoverable and job["attempts"] < self.settings.max_attempts
                else "FAILED"
            )
            error = exc.code if isinstance(exc, MemoryError) else "INTERNAL_ERROR"
            logger.error("Workflow failed: job=%s code=%s", job["id"], error)
            self.repo.finish(job, status, error=error)
            with self.database.engine.begin() as c:
                c.execute(
                    update(db.agent_tasks)
                    .where(db.agent_tasks.c.id == orchestrator_task)
                    .values(status="FAILED", error=error, completed_at=db.now())
                )
        finally:
            stopped.set()
            heartbeat.join(timeout=1)
        return self.repo.job(job["user_id"], job["id"])

    def schedule(self) -> Any:
        interval = self.repo.settings().consolidation_interval_hours
        if interval:
            slot = int(db.now().timestamp() // (interval * 3600))
            self.repo.submit(
                self.settings.owner_id,
                "consolidation",
                {"dry_run": True, "limit": 500},
                f"scheduled-consolidation:{interval}:{slot}",
            )

    def close(self) -> None:
        for service in {id(x): x for x in (self.llm, self.embeddings, self.index)}.values():
            if hasattr(service, "close"):
                service.close()
        self.database.close()

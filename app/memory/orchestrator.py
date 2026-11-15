"""Versioned LangGraph workflow with durable, retry-safe stage outputs."""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import insert, select, update

from app.memory import database as db
from app.memory.contracts import MemoryInput
from app.memory.repository import MemoryError
from app.schemas.agent import MemoriaAgentId as Agent


class WorkflowState(TypedDict, total=False):
    job: dict[str, Any]
    candidates: list[dict[str, Any]]
    memories: list[dict[str, Any]]
    validation: list[dict[str, Any]]
    graph: list[dict[str, Any]]


class Orchestrator:
    def __init__(
        self, repo: Any, context: Any, classifier: Any, quality: Any, writer: Any, graph: Any
    ) -> None:
        self.repo, self.context, self.classifier = repo, context, classifier
        self.quality, self.writer, self.graph = quality, writer, graph
        builder = StateGraph(WorkflowState)
        stages = [
            ("understand", Agent.CONTEXT_UNDERSTANDING, self.understand),
            ("classify", Agent.KNOWLEDGE_CLASSIFICATION, self.classify),
            ("validate", Agent.QUALITY_VALIDATION, self.validate),
            ("write", Agent.KNOWLEDGE_WRITER, self.write),
            ("connect", Agent.KNOWLEDGE_GRAPH, self.connect),
            ("postflight", Agent.QUALITY_VALIDATION, self.postflight),
        ]
        previous = START
        for name, agent, operation in stages:
            builder.add_node(name, self._node(name, agent.value, operation))
            builder.add_edge(previous, name)
            previous = name
        builder.add_edge(previous, END)
        self.workflow = builder.compile()

    def _node(self, name: Any, agent: Any, operation: Any) -> Any:
        def execute(state: Any) -> Any:
            job = state["job"]
            self.repo.heartbeat(job)
            with self.repo.db.engine.begin() as c:
                saved = (
                    c.execute(
                        select(db.agent_tasks.c.output)
                        .where(
                            db.agent_tasks.c.job_id == job["id"],
                            db.agent_tasks.c.stage == name,
                            db.agent_tasks.c.status == "COMPLETED",
                        )
                        .order_by(db.agent_tasks.c.completed_at.desc())
                    )
                    .scalars()
                    .first()
                )
                if saved is not None:
                    return saved
                tid = db.uid()
                c.execute(
                    insert(db.agent_tasks).values(
                        id=tid,
                        user_id=job["user_id"],
                        job_id=job["id"],
                        agent_id=agent,
                        stage=name,
                        status="RUNNING",
                        started_at=db.now(),
                    )
                )
            try:
                output = operation(state)
                with self.repo.db.engine.begin() as c:
                    c.execute(
                        update(db.agent_tasks)
                        .where(db.agent_tasks.c.id == tid)
                        .values(status="COMPLETED", output=output, completed_at=db.now())
                    )
                return output
            except Exception as exc:
                with self.repo.db.engine.begin() as c:
                    c.execute(
                        update(db.agent_tasks)
                        .where(db.agent_tasks.c.id == tid)
                        .values(
                            status="FAILED",
                            error=exc.code if isinstance(exc, MemoryError) else "INTERNAL_ERROR",
                            completed_at=db.now(),
                        )
                    )
                raise

        return execute

    def understand(self, state: Any) -> Any:
        job = state["job"]
        payload = job["payload"]
        chunks = payload.get("chunks") or [{"text": payload["content"], "chunk_id": None}]
        result = []
        for chunk in chunks:
            self.repo.heartbeat(job)
            text = chunk.get("text", chunk.get("content", ""))
            for candidate in self.context.execute(text, payload["source_id"]):
                for source in candidate.sources:
                    source.chunk_id = chunk.get("chunk_id")
                    source.document_id = payload.get("document_id")
                    source.source_type = payload.get("source_type", "text")
                result.append(candidate.model_dump(mode="json"))
        return {"candidates": result}

    def classify(self, state: Any) -> Any:
        result = []
        for value in state["candidates"]:
            self.repo.heartbeat(state["job"])
            result.append(
                self.classifier.execute(MemoryInput.model_validate(value)).model_dump(mode="json")
            )
        return {"candidates": result}

    def validate(self, state: Any) -> Any:
        return {"validation": [self.quality.execute(c) for c in state["candidates"]]}

    def write(self, state: Any) -> Any:
        return {
            "memories": [
                self.writer.execute(state["job"]["user_id"], MemoryInput.model_validate(c))
                for c in state["candidates"]
            ]
        }

    def connect(self, state: Any) -> Any:
        return {
            "graph": [
                self.graph.connect(state["job"]["user_id"], m["id"]) for m in state["memories"]
            ]
        }

    def postflight(self, state: Any) -> Any:
        for memory in state["memories"]:
            saved = self.repo.get(state["job"]["user_id"], memory["id"])
            self.quality.execute(saved["data"])
            if not self.repo.history(state["job"]["user_id"], memory["id"]):
                raise MemoryError("Missing revision history", "CONSISTENCY_ERROR", 500)
        return {}

    def execute(self, job: Any) -> Any:
        result = self.workflow.invoke({"job": job})
        return {
            "memories": result["memories"],
            "validation": result["validation"],
            "graph": result["graph"],
            "workflow_version": "1.0",
        }

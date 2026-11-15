"""Release regressions for atomic writes, request bounds and outage recovery."""

import asyncio

import pytest
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException

from app.api.body_limit import BodyLimitMiddleware
from app.memory.contracts import MemoryInput
from app.memory.repository import MemoryError
from scripts.memoria import worker_cycle
from tests.test_memory_os import candidate, memory_runtime  # noqa: F401


def test_chunked_request_limit():
    async def scenario():
        messages = iter(
            [
                {"type": "http.request", "body": b"123", "more_body": True},
                {"type": "http.request", "body": b"456", "more_body": False},
            ]
        )

        async def receive():
            return next(messages)

        async def send(message):
            pass

        async def application(scope, receive, send):
            await receive()
            await receive()

        with pytest.raises(HTTPException) as error:
            await BodyLimitMiddleware(application, 5)({"type": "http"}, receive, send)
        assert error.value.status_code == 413

    asyncio.run(scenario())


def test_consolidation_rollback_preserves_both_memories(memory_runtime, monkeypatch):
    rt = memory_runtime
    first = rt.remember("local-owner", candidate("Raja uses Python."))
    second = rt.remember("local-owner", candidate("Raja uses Python!"))
    original = rt.repo._snapshot

    def fail_second(connection, row):
        if row["id"] == second["id"]:
            raise RuntimeError("Injected disk failure")
        original(connection, row)

    monkeypatch.setattr(rt.repo, "_snapshot", fail_second)
    with pytest.raises(RuntimeError):
        rt.repo.merge("local-owner", first, second, MemoryInput.model_validate(first["data"]))
    for row in (first, second):
        saved = rt.repo.get("local-owner", row["id"])
        assert saved["status"] == "STORED" and saved["version"] == 1
        assert len(rt.repo.history("local-owner", row["id"])) == 1


def test_purge_requires_soft_delete(memory_runtime):
    rt = memory_runtime
    row = rt.remember("local-owner", candidate())
    with pytest.raises(MemoryError, match="Soft-delete"):
        rt.repo.purge("local-owner", row["id"])
    assert rt.repo.get("local-owner", row["id"])["status"] == "STORED"


def test_worker_survives_database_outage(memory_runtime, monkeypatch, caplog):
    rt = memory_runtime
    original = rt.schedule

    def offline():
        raise OperationalError("secret statement", {}, Exception("secret password"))

    monkeypatch.setattr(rt, "schedule", offline)
    assert worker_cycle(rt) is False
    assert "secret" not in caplog.text
    monkeypatch.setattr(rt, "schedule", original)
    assert worker_cycle(rt) is True

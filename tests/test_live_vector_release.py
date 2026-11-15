"""Actual PostgreSQL + Ollama embeddings + Qdrant synchronization/retrieval."""

import os
from uuid import uuid4

import pytest

from app.memory.config import MemorySettings
from app.memory.contracts import SearchRequest
from app.memory.database import Database
from app.memory.runtime import Runtime
from tests.test_memory_os import candidate

pytestmark = pytest.mark.skipif(
    os.getenv("MEMORIA_LIVE_TESTS") != "1" or not os.getenv("MEMORIA_POSTGRES_TEST_URL"),
    reason="Explicit real-service test configuration required",
)


def test_live_vector_crud_filters_and_sync():
    settings = MemorySettings(
        database_url=os.environ["MEMORIA_POSTGRES_TEST_URL"],
        owner_id=str(uuid4()),
        qdrant_collection="memoria_release_" + uuid4().hex,
        obsidian_enabled=False,
        provider_timeout=30,
    )
    rt = Runtime(settings, Database(settings.database_url.get_secret_value()))
    owner, other = settings.owner_id, str(uuid4())
    rt.repo.bootstrap(owner)
    rt.repo.bootstrap(other)
    try:
        vector = rt.embeddings.embed("Python backend development")
        assert len(vector) == 768
        first = rt.remember(owner, candidate(tags=["release"], memory_type="project"))
        private = rt.remember(other, candidate("Private project Python record."))
        assert rt.sync.run(owner, force=True)["failed"] == 0
        assert rt.sync.run(other, force=True)["failed"] == 0
        query = SearchRequest(
            query="Python",
            mode="semantic",
            memory_type="project",
            tags=["release"],
            source_id="source-1",
        )
        result = rt.retrieval.search(owner, query)
        assert [r["memory"]["id"] for r in result["results"]] == [first["id"]]
        assert private["id"] not in {r["memory"]["id"] for r in result["results"]}
        assert not rt.retrieval.search(owner, query.model_copy(update={"tags": ["missing"]}))[
            "results"
        ]
        changed = rt.repo.revise(
            owner,
            first["id"],
            1,
            candidate("Raja uses Rust.", memory_type="project", tags=["release"]),
        )
        accepted = rt.repo.resolve(owner, changed["id"], "keep_both")
        assert rt.sync.run(owner, force=True)["failed"] == 0
        point = rt.index.request("GET", f"/collections/{rt.index.collection}/points/{first['id']}")[
            "result"
        ]
        assert point["payload"]["version"] == accepted["version"]
        rt.repo.revise(owner, first["id"], accepted["version"], status="DELETED")
        assert rt.sync.run(owner, force=True)["failed"] == 0
        points = rt.index.request(
            "POST", f"/collections/{rt.index.collection}/points", json={"ids": [first["id"]]}
        )["result"]
        assert not points
    finally:
        rt.index.request("DELETE", "/collections/" + settings.qdrant_collection)
        rt.close()

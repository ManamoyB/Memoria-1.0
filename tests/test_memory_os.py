"""Memory OS regression, isolation and failure recovery contracts."""

import json
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.core.config import Settings
from app.main import create_app
from app.memory import database as db
from app.memory.agents import ContextAgent
from app.memory.config import MemorySettings
from app.memory.contracts import Classification, Extraction, MemoryInput, SearchRequest
from app.memory.providers import OllamaProvider, QdrantIndex
from app.memory.repository import MemoryError
from app.memory.runtime import Runtime
from app.obsidian.config import DEFAULT_VAULT_FOLDERS


def candidate(content="Raja uses Python.", source="source-1", **kwargs):
    return MemoryInput(
        title=content,
        content=content,
        confidence=0.9,
        sources=[{"source_id": source, "quote": content}],
        **kwargs,
    )


class FixtureProvider:
    """Test-only deterministic provider, never installed as a runtime fallback."""

    def structured(self, prompt, schema):
        if schema is Classification:
            return Classification(memory_type="semantic", tags=["development"], importance=0.7)
        text = json.loads(prompt.split("Source data follows:\n")[1])
        source = json.loads(prompt.split("Each source_id must be ")[1].split(". Return no")[0])
        return Extraction(
            candidates=[
                candidate(text, source, entities=[{"name": "Raja", "entity_type": "person"}])
            ]
        )

    def embed(self, text):
        return [1.0, 0.0, 0.0]

    def health(self):
        return {"available": True}


class FixtureIndex:
    def __init__(self):
        self.points = {}
        self.fail = False

    def upsert(self, memory, vector):
        if self.fail:
            raise MemoryError("Index offline", "VECTOR_UNAVAILABLE", 503)
        self.points[memory["id"]] = memory

    def remove(self, mid):
        if self.fail:
            raise MemoryError("Index offline", "VECTOR_UNAVAILABLE", 503)
        self.points.pop(mid, None)

    def search(self, user, vector, request):
        if self.fail:
            raise MemoryError("Index offline", "VECTOR_UNAVAILABLE", 503)
        return [
            {"id": mid, "score": 0.9} for mid, row in self.points.items() if row["user_id"] == user
        ]

    def health(self):
        return {"available": not self.fail}


@pytest.fixture
def memory_runtime(tmp_path):
    settings = MemorySettings(
        database_url=f"sqlite:///{tmp_path / 'memory.db'}", embedding_dimensions=3
    )
    database = db.Database(settings.database_url.get_secret_value())
    database.create_for_tests()
    provider = FixtureProvider()
    rt = Runtime(settings, database, provider, provider, FixtureIndex())
    rt.repo.bootstrap("local-owner")
    rt.repo.bootstrap("other")
    yield rt
    rt.close()


def test_memory_versions_and_owner_isolation(memory_runtime):
    rt = memory_runtime
    row = rt.remember("local-owner", candidate())
    assert row["status"] == "STORED"
    assert rt.repo.create("local-owner", candidate())["duplicate"]
    with pytest.raises(MemoryError, match="not found"):
        rt.repo.get("other", row["id"])
    changed = rt.repo.revise("local-owner", row["id"], 1, candidate("Raja uses Rust."))
    assert changed["status"] == "WAITING_FOR_REVIEW"
    with pytest.raises(MemoryError, match="changed"):
        rt.repo.revise("local-owner", row["id"], 1, candidate())
    rt.repo.resolve("local-owner", row["id"], "keep_both")
    assert len(rt.repo.history("local-owner", row["id"])) == 3


def test_duplicate_preserves_new_source(memory_runtime):
    repo = memory_runtime.repo
    first = repo.create("local-owner", candidate())
    second = repo.create("local-owner", candidate(source="another-source"))
    assert first["id"] == second["id"]
    assert len(second["data"]["sources"]) == 2
    assert second["version"] == 2


def test_conflict_review_preserves_history(memory_runtime):
    repo = memory_runtime.repo
    old = repo.create(
        "local-owner", candidate(subject="Raja", predicate="prefers", object="Python")
    )
    new = repo.create(
        "local-owner",
        candidate("Raja prefers Rust.", subject="Raja", predicate="prefers", object="Rust"),
    )
    assert new["status"] == "WAITING_FOR_REVIEW"
    repo.resolve("local-owner", new["id"], "supersede")
    assert repo.get("local-owner", old["id"])["status"] == "SUPERSEDED"
    assert repo.history("local-owner", old["id"])[0]["status"] == "STORED"


def test_pipeline_retry_and_job_idempotency(memory_runtime):
    rt = memory_runtime
    payload = {"content": "Raja uses Python.", "source_id": "test-source"}
    job = rt.repo.submit("local-owner", "ingestion", payload, "stable-key")
    assert rt.repo.submit("local-owner", "ingestion", payload, "stable-key")["id"] == job["id"]
    with pytest.raises(MemoryError):
        rt.repo.submit("local-owner", "ingestion", payload | {"content": "other"}, "stable-key")
    rt.index.fail = True
    result = rt.process(job["id"])
    assert result["status"] == "PARTIALLY_COMPLETED"
    assert rt.repo.list("local-owner")["total"] == 1
    rt.index.fail = False
    report = rt.sync.run("local-owner", force=True)
    assert report["synced"] == 1
    assert len(rt.index.points) == 1


def test_worker_reclaims_expired_lease(memory_runtime):
    rt = memory_runtime
    job = rt.repo.submit(
        "local-owner", "ingestion", {"content": "Raja uses Python.", "source_id": "s"}
    )
    first = rt.repo.claim(job["id"])
    assert rt.repo.claim(job["id"]) is None
    with rt.database.engine.begin() as c:
        c.execute(
            update(db.jobs)
            .where(db.jobs.c.id == job["id"])
            .values(lease_until=db.now() - timedelta(seconds=1))
        )
    second = rt.repo.claim(job["id"])
    assert second["lease_token"] != first["lease_token"]
    with pytest.raises(MemoryError, match="lease"):
        rt.repo.heartbeat(first)


def test_hybrid_search_scope_and_archive(memory_runtime):
    rt = memory_runtime
    row = rt.remember("local-owner", candidate())
    rt.remember("other", candidate("Private Python password."))
    rt.sync.run(force=True)
    request = SearchRequest(query="Python")
    result = rt.retrieval.search("local-owner", request)
    assert len(result["results"]) == 1
    assert result["results"][0]["explanation"]["ranks"] == {"keyword": 1, "semantic": 1}
    assert row["id"] in result["context"]
    rt.repo.revise("local-owner", row["id"], 1, status="ARCHIVED")
    assert rt.retrieval.search("local-owner", request)["results"] == []


def test_provider_outage_never_fabricates(memory_runtime):
    rt = memory_runtime
    rt.remember("local-owner", candidate())
    rt.index.fail = True
    result = rt.retrieval.search("local-owner", SearchRequest(query="Python"))
    assert result["warnings"] and len(result["results"]) == 1
    with pytest.raises(MemoryError):
        rt.retrieval.search("local-owner", SearchRequest(query="Python", mode="semantic"))


def test_invalid_source_is_rejected():
    class BadProvider:
        def structured(self, prompt, schema):
            return Extraction(candidates=[candidate("Invented fact", "s")])

    with pytest.raises(MemoryError, match="provenance"):
        ContextAgent(BadProvider()).execute("Actual source", "s")


def test_ollama_contract_and_dimensions():
    def handler(request):
        if request.url.path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [[1.0, 2.0]]})
        return httpx.Response(200, json={"message": {"content": "not json"}})

    provider = OllamaProvider(MemorySettings(embedding_dimensions=3), httpx.MockTransport(handler))
    with pytest.raises(MemoryError, match="dimensions"):
        provider.embed("test")
    with pytest.raises(MemoryError, match="structured"):
        provider.structured("test", Extraction)
    provider.close()


def test_qdrant_mismatch_and_owner_filter(memory_runtime):
    rt = memory_runtime
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/exists"):
            return httpx.Response(200, json={"result": {"exists": True}})
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json={"result": {"points": []}})
        return httpx.Response(
            200,
            json={"result": {"config": {"params": {"vectors": {"size": 3, "distance": "Cosine"}}}}},
        )

    index = QdrantIndex(rt.settings, rt.repo, httpx.MockTransport(handler))
    with pytest.raises(MemoryError, match="unknown"):
        index.ensure()
    rt.repo.set_setting(
        "collection:" + rt.settings.qdrant_collection,
        {"model": rt.settings.embedding_model, "dimensions": 3},
    )
    index.search("local-owner", [1, 0, 0], SearchRequest(query="Python"))
    assert {"key": "user_id", "match": {"value": "local-owner"}} in json.loads(seen[-1].content)[
        "filter"
    ]["must"]
    rt.repo.set_setting(
        "collection:" + rt.settings.qdrant_collection, {"model": "another", "dimensions": 3}
    )
    with pytest.raises(MemoryError, match="model changed"):
        index.ensure()
    index.close()


def test_vault_preserves_human_notes_and_recovers(memory_runtime, tmp_path):
    rt = memory_runtime
    vault = tmp_path / "vault"
    for folder in DEFAULT_VAULT_FOLDERS:
        (vault / folder).mkdir(parents=True)
    rt.settings.obsidian_enabled = True
    rt.settings.obsidian_vault_path = vault
    memory = rt.remember("local-owner", candidate())
    output = rt.vault.export(memory)
    path = vault / output["path"]
    original = path.read_text(encoding="utf-8")
    assert "memory_id:" in original
    path.unlink()
    assert rt.sync.reconcile("local-owner")["synced"] == 1
    path.write_text("Human edited note", encoding="utf-8")
    with pytest.raises(MemoryError, match="preserved"):
        rt.vault.export(memory)
    assert path.read_text() == "Human edited note"
    rt.settings.obsidian_enabled = False
    rt.settings.obsidian_vault_path = tmp_path / "missing"
    assert rt.sync.reconcile("local-owner")["status"] == "DISABLED"
    assert not rt.settings.obsidian_vault_path.exists()


def test_consolidation_dry_run_and_history(memory_runtime):
    rt = memory_runtime
    a = rt.remember(
        "local-owner",
        candidate("Raja prefers Python.", subject="Raja", predicate="prefers", object="Python"),
    )
    b = rt.remember(
        "local-owner",
        candidate("Raja prefers Python!", subject="Raja", predicate="prefers", object="Python"),
    )
    report = rt.consolidate("local-owner", {"dry_run": True})
    assert report["duplicate_candidates"] and not report["merged"]
    report = rt.consolidate("local-owner", {"dry_run": False})
    assert len(report["merged"]) == 1
    assert rt.repo.list("local-owner")["total"] == 1
    assert sum(len(rt.repo.history("local-owner", mid)) for mid in (a["id"], b["id"])) == 4


def test_authenticated_api_scopes_and_contracts(memory_runtime, tmp_path):
    rt = memory_runtime
    app = create_app(Settings(environment="development", upload_dir=tmp_path / "uploads"))
    app.state.memory_runtime = rt
    owner_key = rt.repo.issue_key("local-owner", "admin", ["admin"])["token"]
    other_key = rt.repo.issue_key("other", "read", ["read"])["token"]
    with TestClient(app) as client:
        assert client.get("/api/v1/memory").status_code == 401
        headers = {"Authorization": "Bearer " + owner_key}
        row = client.post(
            "/api/v1/memory", json=candidate().model_dump(mode="json"), headers=headers
        )
        assert row.status_code == 201, row.text
        mid = row.json()["id"]
        other = {"Authorization": "Bearer " + other_key}
        assert client.get("/api/v1/memory/" + mid, headers=other).status_code == 404
        assert (
            client.post(
                "/api/v1/memory", json=candidate().model_dump(mode="json"), headers=other
            ).status_code
            == 403
        )
        assert client.get("/api/v1/system/config", headers=other).status_code == 403
        result = client.post(
            "/api/v1/search", json={"query": "Python", "mode": "keyword"}, headers=headers
        )
        assert result.status_code == 200 and len(result.json()["results"]) == 1
        assert len(client.get("/api/v1/agents", headers=headers).json()["items"]) == 7
        pdf = __import__("fitz").open()
        pdf.new_page().insert_text((50, 50), "Raja uses Python.")
        response = client.post(
            "/api/v1/ingestion/document?background=false",
            headers=headers,
            files={"file": ("test.pdf", pdf.tobytes(), "application/pdf")},
        )
        pdf.close()
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "COMPLETED", response.text


def test_inferred_claim_not_confirmed(memory_runtime):
    row = memory_runtime.remember("local-owner", candidate(inferred=True))
    assert row["status"] == "WAITING_FOR_REVIEW"
    assert memory_runtime.repo.list("local-owner")["total"] == 0


def test_graph_isolation_and_invalid_relationship(memory_runtime):
    rt = memory_runtime
    row = rt.remember(
        "local-owner", candidate(entities=[{"name": "Raja", "entity_type": "person"}])
    )
    assert rt.graph.explore("local-owner")["relationships"]
    assert not rt.graph.explore("other")["entities"]
    rt.repo.revise("local-owner", row["id"], 1, status="ARCHIVED")
    assert not rt.graph.explore("local-owner")["relationships"]
    with pytest.raises(MemoryError):
        rt.remember(
            "local-owner",
            candidate(relationships=[{"subject": "A", "predicate": "USES", "object": "B"}]),
        )

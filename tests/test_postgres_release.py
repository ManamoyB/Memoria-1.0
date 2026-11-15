"""Opt-in real PostgreSQL release gates; never substitutes SQLite."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.memory import database as db
from app.memory.config import MemorySettings
from app.memory.contracts import SearchRequest
from app.memory.runtime import Runtime
from tests.test_memory_os import FixtureIndex, FixtureProvider, candidate

pytestmark = pytest.mark.skipif(
    not os.getenv("MEMORIA_POSTGRES_TEST_URL"), reason="Real PostgreSQL test URL is required"
)


@pytest.fixture
def pg_runtime():
    url = os.environ["MEMORIA_POSTGRES_TEST_URL"]
    assert url.startswith("postgresql+psycopg://"), "This suite requires real PostgreSQL"
    settings = MemorySettings(database_url=url, owner_id=str(uuid4()), obsidian_enabled=False)
    database = db.Database(url)
    fixture = FixtureProvider()
    rt = Runtime(settings, database, fixture, fixture, FixtureIndex())
    rt.repo.bootstrap(settings.owner_id, "Isolated release test")
    yield rt
    rt.close()


def test_postgres_crud_jsonb_history_and_isolation(pg_runtime):
    rt = pg_runtime
    owner = rt.settings.owner_id
    other = str(uuid4())
    rt.repo.bootstrap(other)
    row = rt.remember(owner, candidate(metadata={"release": "verified"}))
    assert rt.repo.get(owner, row["id"])["content"] == "Raja uses Python."
    assert rt.repo.list(other)["total"] == 0
    with pytest.raises(Exception, match="not found"):
        rt.repo.get(other, row["id"])
    with rt.database.engine.connect() as c:
        assert (
            c.execute(
                select(db.memories.c.data["metadata"]["release"].as_string()).where(
                    db.memories.c.id == row["id"]
                )
            ).scalar_one()
            == "verified"
        )
        assert (
            c.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name='memories' AND column_name='data'"
                )
            ).scalar_one()
            == "jsonb"
        )
    updated = rt.repo.revise(owner, row["id"], 1, candidate("Raja uses Rust."))
    assert updated["status"] == "WAITING_FOR_REVIEW"
    accepted = rt.repo.resolve(owner, row["id"], "keep_both")
    archived = rt.repo.revise(owner, row["id"], accepted["version"], status="ARCHIVED")
    deleted = rt.repo.revise(owner, row["id"], archived["version"], status="DELETED")
    assert len(rt.repo.history(owner, row["id"])) == deleted["version"]
    with rt.database.engine.connect() as c:
        count = c.execute(
            select(func.count()).select_from(db.outbox).where(db.outbox.c.memory_id == row["id"])
        ).scalar_one()
        assert count == 2 * deleted["version"]
    rt.repo.purge(owner, row["id"])
    assert rt.repo.list(owner, status=None)["total"] == 0


def test_postgres_transaction_rollback(pg_runtime, monkeypatch):
    rt = pg_runtime

    def fail(*args, **kwargs):
        raise RuntimeError("injected transaction failure")

    monkeypatch.setattr(rt.repo, "audit", fail)
    with pytest.raises(RuntimeError, match="transaction failure"):
        rt.remember(rt.settings.owner_id, candidate())
    assert rt.repo.list(rt.settings.owner_id, status=None)["total"] == 0
    with rt.database.engine.connect() as c:
        assert (
            c.execute(
                select(func.count())
                .select_from(db.outbox)
                .where(db.outbox.c.user_id == rt.settings.owner_id)
            ).scalar_one()
            == 0
        )


def test_postgres_foreign_keys_indexes_and_fulltext(pg_runtime):
    rt = pg_runtime
    inspector = inspect(rt.database.engine)
    assert any(f["referred_table"] == "users" for f in inspector.get_foreign_keys("memories"))
    indexes = {i["name"] for i in inspector.get_indexes("memories")}
    assert {"ix_memory_fulltext", "ix_memory_owner_status_type"} <= indexes
    with pytest.raises(IntegrityError):
        with rt.database.engine.begin() as c:
            c.execute(
                insert(db.credentials).values(
                    id=str(uuid4()),
                    user_id="missing-owner",
                    name="invalid",
                    digest=uuid4().hex,
                    scopes=["read"],
                    revoked=False,
                )
            )
    rt.remember(rt.settings.owner_id, candidate())
    found = rt.retrieval.search(rt.settings.owner_id, SearchRequest(query="Python", mode="keyword"))
    assert len(found["results"]) == 1


def test_postgres_concurrent_duplicates(pg_runtime):
    rt = pg_runtime
    owner = rt.settings.owner_id

    def create(i):
        return rt.remember(owner, candidate(source=f"parallel-source-{i}"))

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(create, range(8)))
    assert len({row["id"] for row in results}) == 1
    saved = rt.repo.get(owner, results[0]["id"])
    assert len(saved["data"]["sources"]) == 8
    assert rt.repo.list(owner)["total"] == 1


def test_postgres_pool_pre_ping_reconnects(pg_runtime):
    rt = pg_runtime
    with rt.database.engine.connect() as c:
        pid = c.execute(text("SELECT pg_backend_pid()")).scalar_one()
    # A separate connection kills only the connection owned by this isolated test.
    other = db.Database(os.environ["MEMORIA_POSTGRES_TEST_URL"])
    with other.engine.begin() as c:
        assert c.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}).scalar_one()
    other.close()
    with rt.database.engine.connect() as c:
        assert c.execute(text("SELECT 1")).scalar_one() == 1
        assert c.execute(text("SELECT pg_backend_pid()")).scalar_one() != pid


def test_postgres_restart_preserves_memory_and_outbox(pg_runtime):
    rt = pg_runtime
    row = rt.remember(rt.settings.owner_id, candidate())
    rt.database.close()
    replacement = Runtime(
        rt.settings,
        db.Database(os.environ["MEMORIA_POSTGRES_TEST_URL"]),
        rt.llm,
        rt.embeddings,
        rt.index,
    )
    try:
        assert replacement.repo.get(rt.settings.owner_id, row["id"])["version"] == 1
        assert replacement.sync.run(rt.settings.owner_id, force=True)["synced"] == 1
        assert row["id"] in rt.index.points
    finally:
        replacement.close()

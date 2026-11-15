"""Explicit embedding migration: build a new collection, verify, then switch."""

import argparse
import re

from sqlalchemy import insert, select, update

from app.memory import database as db
from app.memory.providers import QdrantIndex
from app.memory.repository import MemoryError
from app.memory.runtime import Runtime


def reindex(rt, collection):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", collection):
        raise ValueError("Use a simple collection name")
    target = QdrantIndex(rt.settings, rt.repo)
    target.collection_override = collection
    if collection == rt.index.collection:
        raise ValueError("Choose a new collection; never migrate in place")
    try:
        target.ensure()
        # All memory mutations lock their owner. Hold these locks for a consistent snapshot.
        with rt.database.engine.begin() as c:
            list(c.execute(select(db.users.c.id).order_by(db.users.c.id).with_for_update()))
            rows = [
                dict(r)
                for r in c.execute(
                    select(db.memories).where(db.memories.c.status == "STORED")
                ).mappings()
            ]
            for row in rows:
                target.upsert(row, rt.embeddings.embed(row["content"]))
            count = target.request(
                "POST", f"/collections/{collection}/points/count", json={"exact": True}
            )["result"]["count"]
            if count != len(rows):
                raise MemoryError("Replacement collection count mismatch; active index unchanged")
            exists = c.execute(
                select(db.system_settings).where(db.system_settings.c.key == "active_collection")
            ).first()
            if exists:
                c.execute(
                    update(db.system_settings)
                    .where(db.system_settings.c.key == "active_collection")
                    .values(value=collection, updated_at=db.now())
                )
            else:
                c.execute(
                    insert(db.system_settings).values(
                        key="active_collection", value=collection, updated_at=db.now()
                    )
                )
            rt.repo.audit(
                c, rt.settings.owner_id, "index.migrated", collection, {"memories": count}
            )
        return {"collection": collection, "memories": count, "old_collection_preserved": True}
    finally:
        target.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection")
    args = parser.parse_args()
    runtime = Runtime()
    try:
        print(reindex(runtime, args.collection))
    finally:
        runtime.close()

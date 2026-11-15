"""Owner-scoped relational knowledge graph."""

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import delete, insert, select

from app.memory import database as db
from app.memory.repository import MemoryError, serial


class KnowledgeGraph:
    def __init__(self, repo: Any) -> None:
        self.repo = repo

    def connect(self, user: Any, memory_id: Any) -> Any:
        with self.repo.db.engine.begin() as c:
            memory = self.repo._get(c, user, memory_id)
            c.execute(
                delete(db.entity_relationships).where(
                    db.entity_relationships.c.memory_id == memory_id
                )
            )
            if memory["status"] != "STORED":
                return {"entities": 0, "relationships": 0}
            inputs = memory["data"]["entities"]
            names = {}
            for entity in inputs:
                eid = str(
                    uuid5(
                        NAMESPACE_URL,
                        user + ":" + entity["entity_type"] + ":" + entity["name"].casefold(),
                    )
                )
                names[entity["name"].casefold()] = eid
                if not c.execute(select(db.entities.c.id).where(db.entities.c.id == eid)).first():
                    c.execute(
                        insert(db.entities).values(
                            id=eid,
                            user_id=user,
                            name=entity["name"],
                            entity_type=entity["entity_type"],
                        )
                    )
            document_entity = str(uuid5(NAMESPACE_URL, user + ":memory:" + memory_id))
            if not c.execute(
                select(db.entities.c.id).where(db.entities.c.id == document_entity)
            ).first():
                c.execute(
                    insert(db.entities).values(
                        id=document_entity, user_id=user, name=memory_id, entity_type="document"
                    )
                )
            relations = []
            for eid in set(names.values()):
                relations.append((eid, document_entity, "MENTIONED_IN", memory["confidence"]))
            for relation in memory["data"]["relationships"]:
                a, b = (
                    names.get(relation["subject"].casefold()),
                    names.get(relation["object"].casefold()),
                )
                if not a or not b:
                    raise MemoryError(
                        "Relationship references an undeclared entity", "INVALID_RELATIONSHIP", 422
                    )
                relations.append((a, b, relation["predicate"], relation["confidence"]))
            for a, b, predicate, confidence in relations:
                rid = str(uuid5(NAMESPACE_URL, memory_id + a + b + predicate))
                if not c.execute(
                    select(db.entity_relationships.c.id).where(db.entity_relationships.c.id == rid)
                ).first():
                    c.execute(
                        insert(db.entity_relationships).values(
                            id=rid,
                            user_id=user,
                            source_id=a,
                            target_id=b,
                            relationship_type=predicate,
                            memory_id=memory_id,
                            confidence=confidence,
                            valid_from=memory["valid_from"],
                            valid_until=memory["valid_until"],
                        )
                    )
            return {"entities": len(names), "relationships": len(relations)}

    def explore(self, user: Any, entity_id: Any = None, limit: Any = 200) -> Any:
        with self.repo.db.engine.connect() as c:
            edges = (
                select(db.entity_relationships)
                .join(db.memories)
                .where(
                    db.entity_relationships.c.user_id == user,
                    db.memories.c.user_id == user,
                    db.memories.c.status == "STORED",
                )
            )
            if entity_id:
                edges = edges.where(
                    (db.entity_relationships.c.source_id == entity_id)
                    | (db.entity_relationships.c.target_id == entity_id)
                )
            rows = [dict(r) for r in c.execute(edges.limit(limit)).mappings()]
            ids = {r[k] for r in rows for k in ("source_id", "target_id")}
            nodes = [
                dict(r)
                for r in c.execute(
                    select(db.entities).where(
                        db.entities.c.user_id == user, db.entities.c.id.in_(ids)
                    )
                ).mappings()
            ]
            return serial({"entities": nodes, "relationships": rows})

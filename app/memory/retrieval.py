"""Explainable rank fusion over authoritative, owner-filtered memories."""

import math
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update

from app.memory import database as db
from app.memory.repository import MemoryError, serial


class Retrieval:
    def __init__(self, repo: Any, embeddings: Any, index: Any) -> None:
        self.repo, self.embeddings, self.index = repo, embeddings, index

    def search(self, user: Any, request: Any) -> Any:
        warnings, vector_rows, keyword_rows = [], [], []
        tokens = re.findall(r"\w+", request.query.casefold())
        with self.repo.db.engine.connect() as c:
            query = select(db.memories).where(
                db.memories.c.user_id == user, db.memories.c.status == "STORED"
            )
            if request.memory_type:
                query = query.where(db.memories.c.memory_type == request.memory_type.value)
            if request.after:
                query = query.where(db.memories.c.created_at >= request.after)
            if request.before:
                query = query.where(db.memories.c.created_at <= request.before)
            # PostgreSQL FTS supplies its own ranked shortlist, not raw scores for fusion.
            if request.mode != "semantic":
                if c.dialect.name == "postgresql":
                    document = func.to_tsvector(
                        "simple", db.memories.c.title + " " + db.memories.c.content
                    )
                    terms = func.plainto_tsquery("simple", request.query)
                    ranked = (
                        query.where(document.op("@@")(terms))
                        .order_by(func.ts_rank_cd(document, terms).desc())
                        .limit(request.top_k * 5)
                    )
                    keyword_rows = [dict(r) for r in c.execute(ranked).mappings()]
                else:
                    rows = [dict(r) for r in c.execute(query).mappings()]

                    def score(row: Any) -> Any:
                        words = re.findall(r"\w+", (row["title"] + " " + row["content"]).casefold())
                        return sum(words.count(t) for t in tokens)

                    keyword_rows = sorted(
                        (r for r in rows if score(r)), key=lambda r: (-score(r), r["id"])
                    )[: request.top_k * 5]
        if request.mode != "keyword":
            try:
                vector_rows = self.index.search(user, self.embeddings.embed(request.query), request)
            except MemoryError:
                if request.mode == "semantic" or not request.allow_keyword_fallback:
                    raise
                warnings.append("Semantic retrieval unavailable; returned keyword results only")
        ranks: dict[str, dict[str, int]] = {}
        for mode, rows in (("keyword", keyword_rows), ("semantic", vector_rows)):
            for rank, row in enumerate(rows, 1):
                ranks.setdefault(str(row["id"]), {})[mode] = rank
        results = []
        k = self.repo.settings().rrf_k
        for mid, explanation in ranks.items():
            try:
                row = self.repo.get(user, mid)
            except MemoryError:
                continue
            if row["status"] != "STORED":
                continue
            data = row["data"]
            if request.memory_type and row["memory_type"] != request.memory_type.value:
                continue
            if any(t not in data["tags"] for t in request.tags):
                continue
            if request.source_id and not any(
                s["source_id"] == request.source_id for s in data["sources"]
            ):
                continue
            created = datetime.fromisoformat(row["created_at"]).replace(tzinfo=UTC)
            if request.after and created < request.after.replace(tzinfo=UTC):
                continue
            if request.before and created > request.before.replace(tzinfo=UTC):
                continue
            if data["valid_until"] and datetime.fromisoformat(data["valid_until"]) < db.now():
                continue
            if data["valid_from"] and datetime.fromisoformat(data["valid_from"]) > db.now():
                continue
            updated = datetime.fromisoformat(row["updated_at"]).replace(tzinfo=UTC)
            temporal = math.exp(-max(0, (db.now() - updated).days) / 365)
            fusion = sum(1 / (k + r) for r in explanation.values())
            boost = 1 + 0.1 * row["importance"] + 0.1 * row["confidence"] + 0.05 * temporal
            results.append(
                {
                    "memory": row,
                    "score": fusion * boost,
                    "explanation": {"ranks": explanation, "rrf": fusion, "boost": boost},
                }
            )
        results.sort(key=lambda r: (-r["score"], r["memory"]["id"]))
        results = results[: request.top_k]
        ids = [r["memory"]["id"] for r in results]
        with self.repo.db.engine.begin() as c:
            c.execute(
                update(db.memories)
                .where(db.memories.c.user_id == user, db.memories.c.id.in_(ids))
                .values(last_accessed_at=db.now())
            )
            links = [
                dict(r)
                for r in c.execute(
                    select(db.memory_relationships).where(
                        db.memory_relationships.c.user_id == user,
                        db.memory_relationships.c.source_id.in_(ids),
                    )
                ).mappings()
            ]
        context, remaining = [], request.context_tokens
        for result in results:
            row = result["memory"]
            text = f"[{row['id']}] {row['content']}\nSources: " + ", ".join(
                s["source_id"] for s in row["data"]["sources"]
            )
            # UTF-8 bytes is a conservative upper bound, independent of tokenizer/provider.
            size = len(text.encode("utf-8"))
            if size <= remaining:
                context.append(text)
                remaining -= size
        return {
            "results": results,
            "context": "\n\n".join(context),
            "warnings": warnings,
            "relationships": serial(links),
            "context_budget_used": request.context_tokens - remaining,
            "context_budget_unit": "utf8_bytes_conservative_tokens",
        }

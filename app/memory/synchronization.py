"""Retryable derived indexes and non-destructive Obsidian revision exports."""

import hashlib
import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from app.memory import database as db
from app.memory.repository import MemoryError
from app.obsidian.config import DEFAULT_VAULT_FOLDERS

DESTINATIONS = {
    "episodic": "02-Episodic-Memory",
    "semantic": "03-Semantic-Memory",
    "procedural": "04-Procedural-Memory",
    "preference": "05-Preferences",
    "project": "06-Projects",
}


class VaultExporter:
    def __init__(self, settings: Any, repo: Any) -> None:
        self.settings, self.repo = settings, repo

    def root(self) -> Any:
        if not self.settings.obsidian_enabled:
            return None
        path = self.settings.obsidian_vault_path
        if path is None or not path.is_dir():
            raise MemoryError("Configured existing vault is unavailable", "VAULT_UNAVAILABLE", 503)
        root = path.resolve()
        if any(
            not (root / folder).is_dir() or (root / folder).resolve().parent != root
            for folder in DEFAULT_VAULT_FOLDERS
        ):
            raise MemoryError("Existing vault folder mapping is invalid", "VAULT_LAYOUT", 409)
        return root

    def render(self, memory: Any) -> Any:
        data = memory["data"]
        frontmatter = {
            "memory_id": memory["id"],
            "version": memory["version"],
            "memory_type": memory["memory_type"],
            "status": memory["status"],
            "tags": data["tags"],
            "created_at": memory["created_at"],
            "updated_at": memory["updated_at"],
            "confidence": memory["confidence"],
        }
        # JSON values are also valid YAML scalars/arrays, avoiding frontmatter injection.
        header = "\n".join(
            f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in frontmatter.items()
        )
        sources = "\n".join(f"- {s['source_id']}: {s['quote']}" for s in data["sources"])
        links = " ".join(
            "[[" + e["name"].replace("[", "").replace("]", "") + "]]" for e in data["entities"]
        )
        return (
            f"---\n{header}\n---\n\n# {memory['title']}\n\n{memory['content']}\n"
            f"\n## Sources\n{sources}\n\n## Entities\n{links}\n"
        )

    def export(self, memory: Any) -> Any:
        if not self.settings.obsidian_enabled:
            return {"status": "DISABLED"}
        if memory["user_id"] != self.settings.owner_id:
            return {"status": "EXCLUDED"}
        if memory["status"] not in ("STORED", "ARCHIVED", "SUPERSEDED"):
            return {"status": "EXCLUDED"}
        root = self.root()
        folder = (
            "08-Archive" if memory["status"] != "STORED" else DESTINATIONS[memory["memory_type"]]
        )
        destination = root / folder / f"memoria-{memory['id']}-v{memory['version']}.md"
        content = self.render(memory).encode("utf-8")
        checksum = hashlib.sha256(content).hexdigest()
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or destination.read_bytes() != content:
                raise MemoryError(
                    "Existing note differs; preserved for human review", "NOTE_CONFLICT", 409
                )
        else:
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as file:
                    temporary = Path(file.name)
                    file.write(content)
                    file.flush()
                    os.fsync(file.fileno())
                # Atomic no-clobber publication. Unlike replace(), link cannot overwrite a note.
                try:
                    os.link(temporary, destination)
                except FileExistsError:
                    if destination.is_symlink() or destination.read_bytes() != content:
                        raise MemoryError(
                            "Concurrent note conflict; existing note preserved",
                            "NOTE_CONFLICT",
                            409,
                        ) from None
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
        manifest = {"path": destination.relative_to(root).as_posix(), "checksum": checksum}
        return {"status": "SYNCED", **manifest}


class Synchronizer:
    def __init__(self, repo: Any, embeddings: Any, index: Any, vault: Any) -> None:
        self.repo, self.embeddings, self.index, self.vault = repo, embeddings, index, vault

    def run(self, user: Any = None, limit: Any = 50, force: Any = False) -> Any:
        report = {"synced": 0, "failed": 0, "disabled": 0}
        # Lock the authoritative memory during external writes: old revisions cannot win a race.
        with self.repo.db.engine.connect() as c:
            query = select(db.outbox.c.id).where(db.outbox.c.status.in_(["PENDING", "FAILED"]))
            if not force:
                query = query.where(db.outbox.c.available_at <= db.now())
            if user:
                query = query.where(db.outbox.c.user_id == user)
            ids = list(c.execute(query.order_by(db.outbox.c.created_at).limit(limit)).scalars())
        for oid in ids:
            with self.repo.db.engine.begin() as c:
                event = (
                    c.execute(select(db.outbox).where(db.outbox.c.id == oid).with_for_update())
                    .mappings()
                    .one()
                )
                if event["status"] not in ("PENDING", "FAILED"):
                    continue
                row = (
                    c.execute(
                        select(db.memories)
                        .where(db.memories.c.id == event["memory_id"])
                        .with_for_update()
                    )
                    .mappings()
                    .first()
                )
                try:
                    if event["target"] == "vector":
                        if row and row["status"] == "STORED":
                            self.index.upsert(dict(row), self.embeddings.embed(row["content"]))
                        else:
                            self.index.remove(event["memory_id"])
                    elif row:
                        from app.memory.repository import serial

                        result = self.vault.export(serial(dict(row)))
                        if result["status"] == "DISABLED":
                            report["disabled"] += 1
                            c.execute(
                                update(db.outbox)
                                .where(db.outbox.c.id == oid)
                                .values(available_at=db.now() + timedelta(minutes=5))
                            )
                            continue
                    c.execute(
                        update(db.outbox)
                        .where(db.outbox.c.id == oid)
                        .values(status="SYNCED", error=None)
                    )
                    report["synced"] += 1
                except Exception as exc:
                    message = str(exc) if isinstance(exc, MemoryError) else "Synchronization failed"
                    c.execute(
                        update(db.outbox)
                        .where(db.outbox.c.id == oid)
                        .values(
                            status="FAILED",
                            error=message,
                            attempts=event["attempts"] + 1,
                            available_at=db.now()
                            + timedelta(seconds=min(3600, 2 ** min(event["attempts"] + 1, 12))),
                        )
                    )
                    report["failed"] += 1
        return report

    def reconcile(self, user: Any) -> Any:
        if not self.vault.settings.obsidian_enabled:
            return {"status": "DISABLED", "examined": 0}
        if user != self.vault.settings.owner_id:
            raise MemoryError("Vault export is restricted to its owner", "FORBIDDEN", 403)
        self.vault.root()
        report: dict[str, Any] = {"examined": 0, "synced": 0, "conflicts": []}
        offset = 0
        while True:
            batch = self.repo.list(user, status=None, limit=100, offset=offset)["items"]
            if not batch:
                break
            for memory in batch:
                report["examined"] += 1
                try:
                    if self.vault.export(memory)["status"] == "SYNCED":
                        report["synced"] += 1
                except MemoryError:
                    report["conflicts"].append(memory["id"])
            offset += len(batch)
        return report

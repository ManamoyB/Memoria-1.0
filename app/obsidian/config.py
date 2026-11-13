"""Configuration and safe vault layout management."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_VAULT_FOLDERS = (
    "00-Inbox",
    "01-Profile",
    "02-Episodic-Memory",
    "03-Semantic-Memory",
    "04-Procedural-Memory",
    "05-Preferences",
    "06-Projects",
    "07-Insights",
    "08-Archive",
    "09-Daily-Logs",
    "10-System",
)


@dataclass(frozen=True, slots=True)
class ObsidianConfig:
    """Filesystem locations for the local Obsidian integration."""

    vault_path: Path
    document_folder: str = "00-Inbox"
    database_path: Path | None = None
    create_vault_structure: bool = True
    folders: tuple[str, ...] = field(default=DEFAULT_VAULT_FOLDERS)

    @classmethod
    def from_env(cls) -> "ObsidianConfig":
        raw_path = os.getenv("MEMORIA_OBSIDIAN_VAULT_PATH")
        if not raw_path:
            raise ValueError(
                "Set MEMORIA_OBSIDIAN_VAULT_PATH to your local Obsidian vault directory."
            )
        raw_db = os.getenv("MEMORIA_OBSIDIAN_DATABASE_PATH")
        return cls(
            vault_path=Path(raw_path).expanduser(),
            database_path=Path(raw_db).expanduser() if raw_db else None,
        )

    def resolved_vault_path(self) -> Path:
        return self.vault_path.expanduser().resolve()

    def resolved_database_path(self) -> Path:
        if self.database_path is not None:
            return self.database_path.expanduser().resolve()
        return self.resolved_vault_path() / ".memoria" / "ingestion.sqlite3"

    def ensure_vault(self) -> Path:
        root = self.resolved_vault_path()
        root.mkdir(parents=True, exist_ok=True)
        if self.create_vault_structure:
            for folder in self.folders:
                target = (root / folder).resolve()
                if root not in target.parents:
                    raise ValueError(f"Vault folder escapes vault root: {folder}")
                target.mkdir(parents=True, exist_ok=True)
        destination = (root / self.document_folder).resolve()
        if root not in destination.parents:
            raise ValueError("Configured document folder must be inside the vault.")
        destination.mkdir(parents=True, exist_ok=True)
        return root

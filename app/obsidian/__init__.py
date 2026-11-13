"""Local Obsidian vault integration for MemoriaOS."""

from app.obsidian.config import ObsidianConfig
from app.obsidian.writer import ObsidianIngestionResult, ObsidianWriter

__all__ = ["ObsidianConfig", "ObsidianIngestionResult", "ObsidianWriter"]

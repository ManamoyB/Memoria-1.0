"""Infrastructure configuration; secrets never appear in public settings."""

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MemorySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEMORIA_", env_file=".env", extra="ignore")
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://memoria:memoria@localhost:5432/memoria"
    )
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"
    ollama_num_gpu: int = Field(default=-1, ge=-1)
    ollama_context_length: int = Field(default=4096, ge=1024, le=131072)
    embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = Field(default=768, ge=1)
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr = SecretStr("")
    qdrant_collection: str = "memoria_nomic_768_v1"
    provider_timeout: float = Field(default=60, ge=1, le=300)
    obsidian_enabled: bool = False
    obsidian_vault_path: Path | None = None
    owner_id: str = "local-owner"
    worker_poll_seconds: float = Field(default=2, ge=0.1)
    max_attempts: int = Field(default=3, ge=1, le=10)
    rate_limit_per_minute: int = Field(default=120, ge=1)

    @field_validator("ollama_base_url", "qdrant_url")
    @classmethod
    def safe_provider_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Provider URLs must be HTTP(S) origins without credentials or query strings"
            )
        return value.rstrip("/")

    def public(self) -> Any:
        return self.model_dump(mode="json", exclude={"database_url", "qdrant_api_key"})

"""Environment-based application configuration using Pydantic v2 Settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import tempfile
from typing import Literal

from pydantic import AliasChoices, Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_upload_dir() -> Path:
    return Path(tempfile.gettempdir()) / "memoria_uploads"


class Settings(BaseSettings):
    """Runtime settings for the MemoriaOS Document Reader Agent.

    All configuration fields can be overridden via environment variables prefixed
    with ``MEMORIA_`` (or ``PORT`` for cloud platforms like Render) or through a
    ``.env`` file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MEMORIA_",
        case_sensitive=False,
        extra="ignore",
    )

    # Application identity
    app_name: str = Field(default="MemoriaOS Document Reader Agent")
    app_version: str = Field(default="0.1.0")
    environment: Literal["development", "staging", "production", "test"] = Field(
        default="development"
    )
    debug: bool = Field(default=False)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO"
    )

    # Server & API routing (supports Render's unprefixed PORT env var)
    host: str = Field(default="0.0.0.0")
    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        validation_alias=AliasChoices("PORT", "MEMORIA_PORT"),
    )
    api_prefix: str = Field(default="/api/v1")
    request_timeout_seconds: float = Field(default=30.0, ge=0.1, le=300.0)
    cors_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000")

    # Storage & upload guardrails (defaults to ephemeral OS temp directory)
    upload_dir: Path = Field(default_factory=_default_upload_dir)
    max_file_size_mb: int = Field(default=25, ge=1, le=500)
    max_batch_files: int = Field(default=10, ge=1, le=100)
    cleanup_temp_uploads: bool = Field(default=True)

    # Extraction, chunking & future OCR readiness (Tesseract)
    default_encoding: str = Field(default="utf-8")
    allowed_formats: str = Field(default="pdf,docx,txt,markdown,csv")
    csv_max_rows: int = Field(default=10000, ge=1, le=1_000_000)
    chunk_size: int = Field(default=3000, ge=100, le=50000)
    chunk_overlap: int = Field(default=300, ge=0, le=10000)
    pdf_min_text_chars_per_page: int = Field(default=40, ge=0)
    ocr_enabled: bool = Field(default=False)
    ocr_engine: str = Field(default="tesseract")
    tesseract_cmd: str = Field(default="tesseract")
    tesseract_lang: str = Field(default="eng")

    @field_validator("api_prefix")
    @classmethod
    def normalize_api_prefix(cls, value: str) -> str:
        """Ensure API prefix always starts with '/' and has no trailing slash."""
        stripped = value.strip()
        if not stripped:
            return "/api/v1"
        if not stripped.startswith("/"):
            stripped = f"/{stripped}"
        return stripped.rstrip("/") or "/api/v1"

    @model_validator(mode="after")
    def validate_chunking_bounds(self) -> Settings:
        """Ensure default chunk_overlap is strictly smaller than default chunk_size."""
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                "MEMORIA_CHUNK_OVERLAP must be strictly smaller than MEMORIA_CHUNK_SIZE."
            )
        return self

    @computed_field
    @property
    def max_file_size_bytes(self) -> int:
        """Maximum permitted upload size in bytes."""
        return self.max_file_size_mb * 1024 * 1024

    @computed_field
    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed list of allowed CORS origins."""
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @computed_field
    @property
    def allowed_format_list(self) -> list[str]:
        """Parsed list of allowed canonical document format names."""
        return [
            fmt.strip().lower()
            for fmt in self.allowed_formats.split(",")
            if fmt.strip()
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton Settings instance for dependency injection."""
    return Settings()

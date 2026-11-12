"""Application settings loaded from environment variables / `.env`."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every field can be overridden with an env variable."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Database (read-only role!) ---
    database_url: str = "postgresql+asyncpg://analyst_ro:analyst_ro_password@localhost:5433/shop"
    db_pool_size: int = Field(default=5, ge=1, le=50)
    statement_timeout_ms: int = Field(default=5000, ge=100, le=60_000)
    default_row_limit: int = Field(default=100, ge=1, le=10_000)
    schema_cache_ttl_s: int = Field(default=300, ge=0)

    # --- LLM ---
    # "demo"   -> deterministic offline scripted LLM (no API key needed, for demos/tests)
    # "openai" -> any OpenAI-compatible endpoint: OpenAI, Ollama, vLLM, OpenRouter, GigaChat proxy
    llm_provider: Literal["demo", "openai"] = "demo"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_timeout_s: float = Field(default=60.0, gt=0)
    llm_json_mode: bool = True

    # --- Agent graph ---
    max_retries: int = Field(default=3, ge=0, le=10)
    synthesizer_max_rows: int = Field(default=50, ge=1, le=500)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

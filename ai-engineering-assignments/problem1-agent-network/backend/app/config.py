"""Centralised, validated configuration (12-factor: everything comes from the environment)."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- infrastructure -------------------------------------------------
    database_url: str = "postgresql+psycopg://agentnet:agentnet@localhost:5432/agentnet"
    redis_url: str = "redis://localhost:6379/0"
    queue_name: str = "agentnet"
    cors_origins: str = "http://localhost:5173"
    public_base_url: str = "http://localhost:8000"

    # --- embeddings -----------------------------------------------------
    embedding_provider: Literal["local", "ollama", "openai"] = "local"
    embedding_dim: int = Field(384, ge=8, le=2000)  # pgvector HNSW supports <= 2000 dims
    embedding_model: str = "nomic-embed-text"
    embedding_base_url: str = "http://127.0.0.1:11434"
    embedding_api_key: str = ""
    embedding_timeout_seconds: float = 20.0

    # --- reranking ------------------------------------------------------
    reranker_provider: Literal["local", "ollama", "http"] = "local"
    reranker_model: str = "llama3.1:8b"
    reranker_base_url: str = "http://127.0.0.1:11434"
    reranker_api_key: str = ""
    reranker_timeout_seconds: float = 30.0

    # --- routing --------------------------------------------------------
    vector_top_k: int = Field(50, ge=1, le=1000)
    rerank_top_n: int = Field(10, ge=1, le=100)
    min_similarity: float = Field(0.12, ge=0.0, le=1.0)
    min_rerank_score: float = Field(0.20, ge=0.0, le=1.0)

    # --- webhooks -------------------------------------------------------
    webhook_timeout_seconds: float = 5.0
    webhook_max_attempts: int = Field(5, ge=1, le=10)
    webhook_backoff_seconds: str = "10,30,120,600"
    # Dev/test only: allows http:// and loopback/private targets (disables the SSRF guard).
    allow_private_webhooks: bool = False

    # --- limits ---------------------------------------------------------
    rate_limit_per_minute: int = Field(120, ge=1)
    register_rate_limit_per_hour: int = Field(20, ge=1)
    max_post_chars: int = 5000
    max_comment_chars: int = 2000
    max_manifesto_chars: int = 2000

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def backoff_intervals(self) -> list[int]:
        return [int(x) for x in self.webhook_backoff_seconds.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

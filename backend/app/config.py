"""Pydantic Settings for env-driven configuration.

Fails fast at import time if required env vars are missing — this is intentional:
we want an unstarted container over a silently-misconfigured one.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(..., alias="DATABASE_URL")
    database_sync_url: str = Field(..., alias="DATABASE_SYNC_URL")
    redis_url: str = Field("redis://redis:6379/0", alias="REDIS_URL")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    gcs_backup_bucket: str = Field("", alias="GCS_BACKUP_BUCKET")
    prometheus_multiproc_dir: str = Field(
        "/tmp/prom_multiproc", alias="PROMETHEUS_MULTIPROC_DIR"
    )
    # Phase 2 additions — ML + RAG
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    qdrant_url: str = Field("http://qdrant:6333", alias="QDRANT_URL")
    mlflow_tracking_uri: str = Field("./mlruns", alias="MLFLOW_TRACKING_URI")
    mlflow_artifact_root: str = Field("./mlartifacts", alias="MLFLOW_ARTIFACT_ROOT")
    reddit_client_id: str = Field("", alias="REDDIT_CLIENT_ID")
    reddit_client_secret: str = Field("", alias="REDDIT_CLIENT_SECRET")
    reddit_user_agent: str = Field("Tide/0.1", alias="REDDIT_USER_AGENT")
    fishbrain_user_agent: str = Field(
        "Tide/0.1 (+research-mvp)", alias="FISHBRAIN_USER_AGENT"
    )
    # Phase 3 additions — LangGraph agent + Anthropic Synthesizer + Langfuse
    anthropic_api_key: str = Field(..., alias="ANTHROPIC_API_KEY")
    langfuse_secret_key: str = Field("", alias="LANGFUSE_SECRET_KEY")
    langfuse_public_key: str = Field("", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_host: str = Field("https://cloud.langfuse.com", alias="LANGFUSE_HOST")
    rapidfuzz_threshold: int = Field(65, alias="RAPIDFUZZ_THRESHOLD")
    rate_limit_bypass_token: str | None = Field(
        default=None,
        alias="TIDE_RATE_LIMIT_BYPASS_TOKEN",
        description=(
            "When a request includes header `X-Tide-Test-Token` matching this "
            "value, slowapi's 20/IP/hour limit is skipped. Operator-only escape "
            "hatch for prod testing. Null in dev disables the bypass entirely."
        ),
    )


settings = Settings()  # import-time instantiation; fails fast on missing required env

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


settings = Settings()  # import-time instantiation; fails fast on missing required env

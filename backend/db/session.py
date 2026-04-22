"""SQLAlchemy 2.0 async + sync engines and session factories.

- `async_engine` / `async_session_factory`: used by FastAPI request handlers and
  Celery tasks that need async I/O.
- `sync_engine`: used by Alembic (which still expects a sync driver).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


async_engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    # WR-07: bound worst-case connection staleness so long-lived Celery
    # workers survive NAT/Timescale restart cycles that pool_pre_ping can
    # miss. 30 minutes is a conservative middle-ground between churn and
    # safety.
    pool_recycle=1800,
    # Fail fast on checkout starvation rather than silently blocking a
    # request indefinitely.
    pool_timeout=10,
)

async_session_factory = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

sync_engine = create_engine(settings.database_sync_url, pool_pre_ping=True)

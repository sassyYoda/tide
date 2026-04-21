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
)

async_session_factory = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

sync_engine = create_engine(settings.database_sync_url, pool_pre_ping=True)

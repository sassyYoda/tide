"""FastAPI dependency: yield an AsyncSession bound to the shared engine.

Uses the module-level ``async_session_factory`` declared in
``backend/db/session.py`` (created in Plan 01).
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from db.session import async_session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession; the context manager handles close + rollback."""
    async with async_session_factory() as session:
        yield session


__all__ = ["get_session"]

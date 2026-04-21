"""FastAPI dependency: yield an async Redis client per request.

``decode_responses=False`` keeps parity with the ingest layer (which stores
orjson-encoded bytes under LKG keys).
"""

from __future__ import annotations

from typing import AsyncGenerator

from redis.asyncio import Redis

from app.config import settings


async def get_redis() -> AsyncGenerator[Redis, None]:
    """Yield an async Redis client bound to ``settings.redis_url``."""
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        yield redis
    finally:
        await redis.aclose()


__all__ = ["get_redis"]

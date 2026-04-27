"""v1 API router aggregator.

Bare-import convention (locked, see backend/pyproject.toml [tool.pytest.ini_options]
``pythonpath = ["."]`` + the runtime ``PYTHONPATH=backend``):

    from api.v1.query import router as query_router
    from api.v1.spots import router as spots_router

Do NOT prefix imports with the backend package name — that prefix is not on
the import path for this repo and would raise ``ModuleNotFoundError``.
"""
from fastapi import APIRouter

from api.v1.query import router as query_router
from api.v1.spots import router as spots_router

router = APIRouter()
router.include_router(query_router)
router.include_router(spots_router)

__all__ = ["router"]

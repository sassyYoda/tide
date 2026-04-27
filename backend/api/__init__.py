"""Tide HTTP API package.

Subpackages:
- ``api.v1`` — public versioned routes (query SSE, scored spots).
- ``api.middleware`` — slowapi rate-limit Limiter + custom exception handler.

Import convention (locked, do NOT use ``from backend.api...``):
    from api.v1 import router as v1_router
    from api.middleware.rate_limit import limiter, rate_limit_handler

These work because ``backend/`` is on ``pythonpath`` (see backend/pyproject.toml
``[tool.pytest.ini_options].pythonpath`` and the runtime ``PYTHONPATH=backend``
in the docker entrypoint).
"""

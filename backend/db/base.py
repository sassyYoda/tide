"""SQLAlchemy 2.0 declarative base.

Plan 02 adds `db/models.py` which imports Base and defines ORM models. Alembic's
env.py picks up `Base.metadata` for autogenerate.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass

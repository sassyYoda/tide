"""Alembic environment — sync psycopg2 driver + TimescaleDB hypertable filter.

Design notes:
- Alembic still expects a sync DBAPI for migrations, so we read
  `settings.database_sync_url` (postgresql+psycopg2://...) and drive the
  migration with a standard sync `engine_from_config` + `NullPool`.
- TimescaleDB's `create_hypertable()` creates `_hyper_N_M_...` child tables and
  indexes as a side effect. Alembic's autogenerate sees these and tries to DROP
  them, which would corrupt the database. `include_name()` below filters them
  out, along with all `_timescaledb_*` and `timescaledb_*` schemas.
- `db.models` is imported for its side effects (registering ORM classes on
  `Base.metadata`). Plan 01 ships without models; Plan 02 creates `db/models.py`
  and removes the try/except guard.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from db.base import Base

# Plan 02: db/models.py exists and registers all ORM classes onto Base.metadata.
# Import for side effects; Alembic autogenerate reads target_metadata below.
import db.models  # noqa: F401

config = context.config

# Inject the sync URL from Pydantic Settings — alembic.ini intentionally has no
# sqlalchemy.url key.
config.set_main_option("sqlalchemy.url", settings.database_sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


_TIMESCALE_SCHEMAS = frozenset(
    {
        "_timescaledb_catalog",
        "_timescaledb_internal",
        "_timescaledb_cache",
        "_timescaledb_config",
        "timescaledb_information",
        "timescaledb_experimental",
    }
)


def include_name(name, type_, parent_names):
    """Exclude TimescaleDB-managed objects from autogenerate diffs."""
    if type_ == "index" and name and name.startswith("_hyper_"):
        return False
    if type_ == "table" and name and name.startswith("_hyper_"):
        return False
    if type_ == "schema" and name in _TIMESCALE_SCHEMAS:
        return False
    return True


def run_migrations_offline() -> None:
    """Offline mode: emit SQL without connecting."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_name=include_name,
        include_schemas=False,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online mode: sync psycopg2 engine, NullPool (Alembic is a one-shot)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_name=include_name,
            include_schemas=False,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

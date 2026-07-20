"""Alembic environment: migrations always target halu-core's configured
database (spec §7, Phase 6.5) -- never `SQLModel.metadata.create_all()`
in production. Tests and local dev may still use the ephemeral
in-memory SQLite path (see `halu_core.config.Settings.database_is_ephemeral_sqlite`),
which this file has no involvement in.

Phase 8.7: an optional, separate migration connection string.
Providers like Neon give out a *pooled* connection string for normal
runtime traffic (what `HALU_CORE_DATABASE_URL` / `settings.database_url`
is for) and a separate *direct* connection string for anything that
needs a real, non-pooled session -- which DDL (what every Alembic
migration is) generally requires, since pgbouncer-style poolers
commonly can't run migrations reliably (session state, prepared
statements, and advisory locks used by some migration tooling don't
survive being transparently multiplexed across pooled connections).
`HALU_CORE_MIGRATION_DATABASE_URL`, if set, is used here instead of the
runtime URL; if unset, this falls back to `settings.database_url`
exactly as before, so self-hosters with a single plain Postgres/SQLite
instance (no pooler in front of it) don't need to configure anything
extra.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

import halu_core.models  # noqa: F401  (registers every table's metadata)
from alembic import context
from halu_core.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Drive the connection URL from the app's own settings so migrations
# always target whatever HALU_CORE_DATABASE_URL points at -- unless a
# separate, direct migration URL is configured (see module docstring),
# in which case migrations use that instead of the pooled runtime URL.
migration_database_url = os.environ.get("HALU_CORE_MIGRATION_DATABASE_URL") or settings.database_url
config.set_main_option("sqlalchemy.url", migration_database_url)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

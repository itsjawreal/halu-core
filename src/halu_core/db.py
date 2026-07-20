"""Database engine and session management (SQLite via SQLModel)."""

from __future__ import annotations

import logging
import os
from collections.abc import Generator

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from halu_core.config import settings

logger = logging.getLogger("halu_core.db")

_is_sqlite = settings.database_url.startswith("sqlite")
_is_memory = settings.database_url in ("sqlite://", "sqlite:///:memory:")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}
# An in-memory SQLite database only exists for the lifetime of one
# connection, so pool every request onto the same connection.
if _is_memory:
    _engine_kwargs: dict[str, object] = {"poolclass": StaticPool}
else:
    # A managed Postgres endpoint (e.g. Neon's pooled/pgbouncer endpoint)
    # can close idle connections server-side at any time. Without
    # pool_pre_ping, SQLAlchemy hands out those dead connections from its
    # pool as-is, and the first query on one fails with
    # "SSL connection has been closed unexpectedly". pool_pre_ping issues
    # a cheap liveness check before reusing a pooled connection and
    # transparently reconnects if it's dead; pool_recycle proactively
    # retires connections before they get old enough to hit a idle
    # timeout in the first place.
    _engine_kwargs = {"pool_pre_ping": True, "pool_recycle": 300}
engine = create_engine(settings.database_url, connect_args=_connect_args, **_engine_kwargs)


def create_db_and_tables() -> None:
    """Create the SQLite data directory (if needed) and all tables.

    Dev/test convenience only -- see `ensure_database_ready()`, which is
    what actually runs at app startup and only calls this for the
    ephemeral in-memory SQLite database tests and quick local runs use.
    """
    if settings.database_url.startswith("sqlite:///"):
        db_path = settings.database_url.removeprefix("sqlite:///")
        if db_path and db_path != ":memory:":
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def ensure_database_ready() -> None:
    """Prepare the database at app startup (Phase 6.5 §7).

    Never calls `SQLModel.metadata.create_all()` against a persistent
    database (file-based SQLite, Postgres, ...) -- that database is
    expected to already be migrated via `alembic upgrade head`. Only
    the ephemeral in-memory SQLite URL (used by tests and quick local
    runs) is auto-created here, since there is no persistent schema to
    migrate in the first place.
    """
    if settings.database_is_ephemeral_sqlite:
        create_db_and_tables()
    else:
        logger.info(
            "Skipping auto-create for persistent database; run "
            "'alembic upgrade head' to apply migrations."
        )


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session

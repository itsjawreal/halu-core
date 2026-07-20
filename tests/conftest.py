"""Shared pytest fixtures: an isolated in-memory database per test."""

from __future__ import annotations

import os

# Must be set before halu_core.config is first imported anywhere, so the
# app's own startup-time database (unused by tests, which override the
# session dependency below) never touches disk.
os.environ.setdefault("HALU_CORE_DATABASE_URL", "sqlite://")

from collections.abc import Generator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

import halu_core.models  # noqa: E402, F401  (registers every table before create_all)


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


@pytest.fixture()
def client(session: Session) -> Generator[TestClient, None, None]:
    from halu_core.api.dependencies import get_session
    from halu_core.main import app

    def _get_session_override() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_session] = _get_session_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

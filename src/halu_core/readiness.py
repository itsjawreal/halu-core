"""Readiness checks for `/health/ready` (Phase 8 §6).

Each check is a small, independent, side-effect-free function so it can
be unit-tested without booting a full app. None of these ever log or
return a token, hidden challenge data, or any other secret -- only
booleans and short human-readable status strings.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlmodel import Session

from halu_core.challenges.registry import registry
from halu_core.config import settings
from halu_core.db import engine
from halu_core.migrations_meta import EXPECTED_MIGRATION_HEAD


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def check_database() -> CheckResult:
    """Can we open a connection and run the simplest possible query?"""
    try:
        with Session(engine) as session:
            session.execute(text("SELECT 1"))
        return CheckResult("database", True, "connected")
    except Exception as exc:  # noqa: BLE001 - report, don't crash the health endpoint
        return CheckResult("database", False, f"connection failed: {type(exc).__name__}")


def check_migration_head() -> CheckResult:
    """Is a persistent database actually at the migration head this code expects?

    An ephemeral (in-memory) SQLite database has no Alembic history at
    all by design (tests/dev auto-create instead) -- that's expected,
    not a failure.
    """
    if settings.database_is_ephemeral_sqlite:
        return CheckResult("migration_head", True, "ephemeral database; migrations not tracked")
    try:
        with Session(engine) as session:
            row = session.execute(text("SELECT version_num FROM alembic_version")).first()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "migration_head", False, f"could not read alembic_version: {type(exc).__name__}"
        )
    version_num = row[0] if row else None
    if version_num != EXPECTED_MIGRATION_HEAD:
        return CheckResult(
            "migration_head",
            False,
            f"database is at {version_num!r}, expected {EXPECTED_MIGRATION_HEAD!r}",
        )
    return CheckResult("migration_head", True, f"at head {EXPECTED_MIGRATION_HEAD!r}")


def check_registered_challenges(challenge_ids: tuple[str, ...]) -> CheckResult:
    """Are all the challenge ids a deployment expects to serve actually registered?

    `challenge_ids` is supplied by the caller (e.g. halu-web passes its
    `OFFICIAL_CHALLENGE_IDS`) -- core has no opinion on which ids matter.
    An empty tuple (the bare engine, with no official challenges of its
    own) always passes trivially.
    """
    missing = [cid for cid in challenge_ids if not registry.is_registered(cid)]
    if missing:
        return CheckResult("registered_challenges", False, f"not registered: {missing}")
    return CheckResult("registered_challenges", True, f"{len(challenge_ids)} registered")


def run_readiness_checks(challenge_ids: tuple[str, ...] = ()) -> tuple[bool, list[CheckResult]]:
    checks = [
        check_database(),
        check_migration_head(),
        check_registered_challenges(challenge_ids),
    ]
    return all(c.ok for c in checks), checks

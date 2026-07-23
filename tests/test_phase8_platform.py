"""Tests for Phase 8 public-alpha-readiness primitives: production
manifest enforcement, public result sharing, data retention cleanup,
liveness/readiness, and abuse protection limits.
"""

from __future__ import annotations

import dataclasses
import sys
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from halu_core.challenges.base import Challenge
from halu_core.challenges.models import ActionRequest, ActionResult
from halu_core.challenges.registry import ProductionManifestChangeError, registry
from halu_core.config import settings as real_settings
from halu_core.migrations_meta import EXPECTED_MIGRATION_HEAD
from halu_core.models.enums import AgentType, RunStatus
from halu_core.models.public_share import RunPublicShare
from halu_core.models.run import Run
from halu_core.readiness import (
    check_database,
    check_migration_head,
    check_registered_challenges,
)
from halu_core.services import public_share_service
from halu_core.services.cleanup_service import run_cleanup
from halu_core.services.run_service import (
    ManifestUnavailableError,
    create_run,
)
from halu_core.timeutils import utc_now


class _TinyChallenge(Challenge):
    @property
    def id(self) -> str:
        return "phase8_tiny_001"

    @property
    def name(self) -> str:
        return "Phase 8 Tiny Challenge"

    @property
    def time_limit_seconds(self) -> int:
        return 60

    @property
    def public_instructions(self) -> str:
        return "Do the one thing."

    @property
    def allowed_actions(self) -> tuple[str, ...]:
        return ("complete_run",)

    def build_initial_state(self) -> dict[str, Any]:
        return {"done": False}

    def validate_action(self, state: dict[str, Any], action: ActionRequest) -> ActionResult:
        return ActionResult(success=True, state_changed=False)

    def apply_action(self, state: dict[str, Any], action: ActionRequest) -> dict[str, Any]:
        return state

    def is_complete(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))


@pytest.fixture()
def tiny_challenge_id() -> Iterator[str]:
    challenge = _TinyChallenge()
    registry.register(challenge, replace=True)
    yield challenge.id
    registry.unregister(challenge.id)


def _settings_with(**overrides: Any) -> Any:
    """A full, valid `Settings` (frozen dataclass) with some fields
    overridden -- since it's frozen, tests can't mutate the shared
    singleton in place, so they monkeypatch a module's `settings` name
    to one of these instead.
    """
    return dataclasses.replace(real_settings, **overrides)


def _registry_module() -> Any:
    """The actual `halu_core.challenges.registry` *module* object.

    `import halu_core.challenges.registry as x` doesn't reliably give
    you this: `halu_core/challenges/__init__.py` does
    `from halu_core.challenges.registry import registry`, which rebinds
    the *package* attribute `halu_core.challenges.registry` from the
    submodule to the singleton instance -- so a dotted `import ... as`
    (which resolves via attribute access once the parent package is
    loaded) can silently hand back the singleton instead of the module.
    Going through `sys.modules` sidesteps that shadowing entirely.
    """
    return sys.modules["halu_core.challenges.registry"]


# -- Manifest integrity: production enforcement ---------------------------


def test_production_run_creation_fails_for_unregistered_challenge(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import halu_core.services.run_service as run_service_module

    monkeypatch.setattr(run_service_module, "settings", _settings_with(env="production"))
    with pytest.raises(ManifestUnavailableError):
        create_run(session, challenge_id="no_such_challenge", agent_type=AgentType.GENERIC)


def test_development_run_creation_still_succeeds_for_unregistered_challenge(
    session: Session,
) -> None:
    run, _token = create_run(
        session, challenge_id="no_such_challenge", agent_type=AgentType.GENERIC
    )
    assert run.manifest_dataset_hash is None


def test_production_registry_rejects_manifest_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_registry_module(), "settings", _settings_with(env="production"))
    from halu_core.challenges.registry import ChallengeRegistry

    fresh = ChallengeRegistry()
    fresh.register(_TinyChallenge())
    with pytest.raises(ProductionManifestChangeError):
        fresh.register(_TinyChallenge(), replace=True, allow_manifest_change=True)


def test_development_registry_allows_manifest_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_registry_module(), "settings", _settings_with(env="development"))
    from halu_core.challenges.registry import ChallengeRegistry

    fresh = ChallengeRegistry()
    fresh.register(_TinyChallenge())
    fresh.register(_TinyChallenge(), replace=True, allow_manifest_change=True)  # no raise


# -- Public result sharing --------------------------------------------------


def _create_completed_run(session: Session, client: TestClient, challenge_id: str) -> str:
    response = client.post(
        "/api/v1/runs", json={"challenge_id": challenge_id, "agent_type": "generic"}
    )
    body = response.json()
    run_id, token = body["run_id"], body["token"]
    client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"summary": "done", "claims": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    return run_id


def test_public_share_create_and_resolve(
    client: TestClient, session: Session, tiny_challenge_id: str
) -> None:
    run_id = _create_completed_run(session, client, tiny_challenge_id)
    raw_slug = public_share_service.create_public_share(session, run_id)

    resolved = public_share_service.get_run_by_public_slug(session, raw_slug)
    assert resolved is not None
    assert resolved.id == run_id


def test_public_share_wrong_slug_resolves_to_nothing(
    client: TestClient, session: Session, tiny_challenge_id: str
) -> None:
    run_id = _create_completed_run(session, client, tiny_challenge_id)
    public_share_service.create_public_share(session, run_id)

    assert public_share_service.get_run_by_public_slug(session, "not-the-real-slug") is None


def test_public_share_disable_revokes_access(
    client: TestClient, session: Session, tiny_challenge_id: str
) -> None:
    run_id = _create_completed_run(session, client, tiny_challenge_id)
    raw_slug = public_share_service.create_public_share(session, run_id)

    disabled = public_share_service.disable_public_share(session, run_id)
    assert disabled is True
    assert public_share_service.get_run_by_public_slug(session, raw_slug) is None
    assert public_share_service.is_public_sharing_enabled(session, run_id) is False


def test_public_share_rotate_invalidates_old_slug(
    client: TestClient, session: Session, tiny_challenge_id: str
) -> None:
    run_id = _create_completed_run(session, client, tiny_challenge_id)
    old_slug = public_share_service.create_public_share(session, run_id)
    new_slug = public_share_service.rotate_public_share(session, run_id)

    assert old_slug != new_slug
    assert public_share_service.get_run_by_public_slug(session, old_slug) is None
    resolved = public_share_service.get_run_by_public_slug(session, new_slug)
    assert resolved is not None and resolved.id == run_id


def test_disabling_share_with_nothing_active_is_a_noop(
    client: TestClient, session: Session, tiny_challenge_id: str
) -> None:
    run_id = _create_completed_run(session, client, tiny_challenge_id)
    assert public_share_service.disable_public_share(session, run_id) is False


# -- Cleanup: dry-run vs. real, and retention edge cases --------------------


def test_cleanup_dry_run_deletes_nothing(session: Session) -> None:
    now = utc_now()
    stale = Run(
        challenge_id="x",
        agent_type=AgentType.GENERIC,
        status=RunStatus.EXPIRED,
        created_at=now - timedelta(days=30),
        expires_at=now - timedelta(days=29),
    )
    session.add(stale)
    session.commit()

    report = run_cleanup(session, now=now, dry_run=True)
    assert stale.id in report.incomplete_runs_deleted
    assert session.get(Run, stale.id) is not None  # still there


def test_cleanup_real_run_deletes_stale_incomplete_runs(session: Session) -> None:
    now = utc_now()
    stale = Run(
        challenge_id="x",
        agent_type=AgentType.GENERIC,
        status=RunStatus.EXPIRED,
        created_at=now - timedelta(days=30),
        expires_at=now - timedelta(days=29),
    )
    session.add(stale)
    session.commit()
    stale_id = stale.id

    report = run_cleanup(session, now=now, dry_run=False)
    assert stale_id in report.incomplete_runs_deleted
    assert session.get(Run, stale_id) is None


def test_cleanup_never_deletes_a_run_with_an_active_public_share(session: Session) -> None:
    now = utc_now()
    old_completed = Run(
        challenge_id="x",
        agent_type=AgentType.GENERIC,
        status=RunStatus.COMPLETED,
        created_at=now - timedelta(days=400),
        expires_at=now - timedelta(days=399),
        completed_at=now - timedelta(days=400),
    )
    session.add(old_completed)
    session.commit()
    public_share_service.create_public_share(session, old_completed.id)

    report = run_cleanup(session, now=now, dry_run=False)
    assert old_completed.id in report.completed_runs_skipped_public_share
    assert session.get(Run, old_completed.id) is not None


def test_cleanup_deletes_a_run_once_public_share_disabled_and_retention_elapsed(
    session: Session,
) -> None:
    now = utc_now()
    old_completed = Run(
        challenge_id="x",
        agent_type=AgentType.GENERIC,
        status=RunStatus.COMPLETED,
        created_at=now - timedelta(days=400),
        expires_at=now - timedelta(days=399),
        completed_at=now - timedelta(days=400),
    )
    session.add(old_completed)
    session.commit()
    public_share_service.create_public_share(session, old_completed.id)
    public_share_service.disable_public_share(session, old_completed.id)
    # Force disabled_at far enough in the past to clear the retention window.
    share = session.exec(
        select(RunPublicShare).where(RunPublicShare.run_id == old_completed.id)
    ).first()
    assert share is not None
    share.disabled_at = now - timedelta(days=400)
    session.add(share)
    session.commit()

    report = run_cleanup(session, now=now, dry_run=False)
    assert old_completed.id in report.completed_runs_deleted
    assert session.get(Run, old_completed.id) is None


def test_cleanup_retention_zero_disables_that_bucket(session: Session, monkeypatch) -> None:
    from halu_core.services import cleanup_service as cleanup_module

    monkeypatch.setattr(cleanup_module, "settings", _settings_with(retention_incomplete_run_days=0))
    now = utc_now()
    stale = Run(
        challenge_id="x",
        agent_type=AgentType.GENERIC,
        status=RunStatus.EXPIRED,
        created_at=now - timedelta(days=9999),
        expires_at=now - timedelta(days=9998),
    )
    session.add(stale)
    session.commit()

    report = run_cleanup(session, now=now, dry_run=False)
    assert stale.id not in report.incomplete_runs_deleted
    assert session.get(Run, stale.id) is not None


# -- Liveness / readiness ----------------------------------------------------


def test_health_live_always_ok(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_ready_ok_on_ephemeral_test_database(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    names = {c["name"] for c in body["checks"]}
    assert names == {"database", "migration_head", "registered_challenges"}


def test_check_database_reports_ok() -> None:
    result = check_database()
    assert result.ok is True


def test_check_migration_head_ok_on_ephemeral_database() -> None:
    result = check_migration_head()
    assert result.ok is True
    assert "ephemeral" in result.detail


def test_expected_migration_head_matches_alembic_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert EXPECTED_MIGRATION_HEAD == script.get_current_head()


def test_check_registered_challenges_reports_missing() -> None:
    result = check_registered_challenges(("definitely_not_registered_xyz",))
    assert result.ok is False
    assert "definitely_not_registered_xyz" in result.detail


def test_check_registered_challenges_passes_for_examples() -> None:
    result = check_registered_challenges(("example_ping_001", "example_counter_001"))
    assert result.ok is True


# -- Abuse protection ---------------------------------------------------------


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_max_actions_per_run_is_enforced(
    client: TestClient, tiny_challenge_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import halu_core.api.agent as agent_module

    monkeypatch.setattr(agent_module, "settings", _settings_with(max_actions_per_run=2))
    response = client.post(
        "/api/v1/runs", json={"challenge_id": tiny_challenge_id, "agent_type": "generic"}
    )
    run_id, token = response.json()["run_id"], response.json()["token"]

    for _ in range(2):
        client.post(
            f"/api/v1/runs/{run_id}/actions",
            json={"action": "complete_run"},
            headers=_auth(token),
        )
    third = client.post(
        f"/api/v1/runs/{run_id}/actions", json={"action": "complete_run"}, headers=_auth(token)
    )
    assert third.status_code == 429
    assert third.json()["detail"]["error_code"] == "max_actions_exceeded"


def test_oversized_final_report_is_rejected(
    client: TestClient, tiny_challenge_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import halu_core.api.agent as agent_module

    monkeypatch.setattr(agent_module, "settings", _settings_with(max_final_report_length=10))
    response = client.post(
        "/api/v1/runs", json={"challenge_id": tiny_challenge_id, "agent_type": "generic"}
    )
    run_id, token = response.json()["run_id"], response.json()["token"]
    complete = client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"summary": "this summary is definitely too long", "claims": []},
        headers=_auth(token),
    )
    assert complete.status_code == 400
    assert complete.json()["detail"]["error_code"] == "final_report_too_large"


def test_too_many_claims_is_rejected(
    client: TestClient, tiny_challenge_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import halu_core.api.agent as agent_module

    monkeypatch.setattr(agent_module, "settings", _settings_with(max_claims_per_report=2))
    response = client.post(
        "/api/v1/runs", json={"challenge_id": tiny_challenge_id, "agent_type": "generic"}
    )
    run_id, token = response.json()["run_id"], response.json()["token"]
    complete = client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={
            "summary": "done",
            "claims": [
                {"type": "a", "value": 1},
                {"type": "b", "value": 2},
                {"type": "c", "value": 3},
            ],
        },
        headers=_auth(token),
    )
    assert complete.status_code == 400
    assert complete.json()["detail"]["error_code"] == "too_many_claims"


def test_deeply_nested_action_payload_is_rejected(
    client: TestClient, tiny_challenge_id: str, monkeypatch
) -> None:
    import halu_core.api.agent as agent_module

    monkeypatch.setattr(agent_module, "settings", _settings_with(max_json_depth=3))
    response = client.post(
        "/api/v1/runs", json={"challenge_id": tiny_challenge_id, "agent_type": "generic"}
    )
    run_id, token = response.json()["run_id"], response.json()["token"]

    deep: dict[str, object] = {}
    cursor = deep
    for _ in range(10):
        cursor["nested"] = {}
        cursor = cursor["nested"]  # type: ignore[assignment]

    result = client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "complete_run", "payload": deep},
        headers=_auth(token),
    )
    assert result.status_code == 400
    assert result.json()["detail"]["error_code"] == "payload_too_deep"


def test_run_ttl_is_capped(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    import halu_core.services.run_service as run_service_module

    monkeypatch.setattr(run_service_module, "settings", _settings_with(max_run_ttl_seconds=60))
    run, _token = create_run(
        session,
        challenge_id="no_such_challenge",
        agent_type=AgentType.GENERIC,
        ttl_seconds=999_999,
    )
    assert (run.expires_at - run.created_at).total_seconds() <= 60

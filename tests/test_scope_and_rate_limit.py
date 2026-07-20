"""Tests for Phase 3.5's scope enforcement and rate limiting on the
generic Agent API. Uses only halu-core's own `example_ping_001` and the
same test-local `_WidgetChallenge` pattern used in test_agent_api.py, so
none of this depends on any hidden, official challenge logic.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from halu_core.api.dependencies import get_current_time, get_rate_limit_config
from halu_core.challenges.base import Challenge
from halu_core.challenges.models import ActionRequest, ActionResult
from halu_core.challenges.registry import registry
from halu_core.models.enums import AgentType, TokenScope
from halu_core.services.rate_limit_service import RateLimitConfig
from halu_core.services.run_service import create_run


class _WidgetChallenge(Challenge):
    """Same test-only stand-in as test_agent_api.py's, duplicated locally
    so this file has no import-order dependency on that one.
    """

    @property
    def id(self) -> str:
        return "external_scope_rate_limit_001"

    @property
    def name(self) -> str:
        return "Widget Triage (test-only)"

    @property
    def time_limit_seconds(self) -> int:
        return 60

    @property
    def public_instructions(self) -> str:
        return "Approve or reject each widget."

    @property
    def allowed_actions(self) -> tuple[str, ...]:
        return ("approve_widget", "reject_widget", "complete_run")

    def build_initial_state(self) -> dict[str, Any]:
        return {
            "widgets": {
                "w1": {"id": "w1", "status": "pending"},
                "w2": {"id": "w2", "status": "pending"},
            }
        }

    def validate_action(self, state: dict[str, Any], action: ActionRequest) -> ActionResult:
        if action.action == "complete_run":
            return ActionResult(success=True, state_changed=False)
        if action.action not in ("approve_widget", "reject_widget"):
            return ActionResult(
                success=False, state_changed=False, error_code="unknown_action"
            )
        widget = state["widgets"].get(action.target_id) if action.target_id else None
        if widget is None:
            return ActionResult(success=False, state_changed=False, error_code="not_found")
        if widget["status"] != "pending":
            return ActionResult(
                success=False, state_changed=False, error_code="already_processed"
            )
        status = "approved" if action.action == "approve_widget" else "rejected"
        return ActionResult(success=True, state_changed=True, target_status=status)

    def apply_action(self, state: dict[str, Any], action: ActionRequest) -> dict[str, Any]:
        result = self.validate_action(state, action)
        if not result.success or action.action == "complete_run":
            return state
        new_state = copy.deepcopy(state)
        new_state["widgets"][action.target_id]["status"] = result.target_status
        return new_state

    def is_complete(self, state: dict[str, Any]) -> bool:
        return all(w["status"] != "pending" for w in state["widgets"].values())

    def list_items(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        return list(state["widgets"].values())

    def get_item(self, state: dict[str, Any], item_id: str) -> dict[str, Any] | None:
        return state["widgets"].get(item_id)


@pytest.fixture()
def widget_challenge_id() -> Iterator[str]:
    challenge = _WidgetChallenge()
    registry.register(challenge, replace=True)
    yield challenge.id
    registry.unregister(challenge.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_run(
    client: TestClient, challenge_id: str = "example_ping_001", agent_type: str = "generic"
) -> tuple[str, str]:
    response = client.post(
        "/api/v1/runs", json={"challenge_id": challenge_id, "agent_type": agent_type}
    )
    assert response.status_code == 200
    body = response.json()
    return body["run_id"], body["token"]


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


# -- Scope enforcement -------------------------------------------------


def test_challenge_read_only_token_can_read_but_not_write(
    client: TestClient, session: Session
) -> None:
    run, token = create_run(
        session,
        challenge_id="example_ping_001",
        agent_type=AgentType.GENERIC,
        scope=(TokenScope.CHALLENGE_READ,),
    )

    assert client.get(f"/api/v1/runs/{run.id}/challenge", headers=_auth(token)).status_code == 200
    assert client.get(f"/api/v1/runs/{run.id}/context", headers=_auth(token)).status_code == 200

    for response in (
        client.get(f"/api/v1/runs/{run.id}/items", headers=_auth(token)),
        client.post(
            f"/api/v1/runs/{run.id}/actions", json={"action": "ping"}, headers=_auth(token)
        ),
        client.post(
            f"/api/v1/runs/{run.id}/complete",
            json={"summary": "x", "claims": []},
            headers=_auth(token),
        ),
    ):
        assert response.status_code == 403
        assert response.json()["detail"]["error_code"] == "insufficient_scope"


def test_items_read_only_token_can_read_items_but_nothing_else(
    client: TestClient, session: Session, widget_challenge_id: str
) -> None:
    run, token = create_run(
        session,
        challenge_id=widget_challenge_id,
        agent_type=AgentType.GENERIC,
        scope=(TokenScope.ITEMS_READ,),
    )

    assert client.get(f"/api/v1/runs/{run.id}/items", headers=_auth(token)).status_code == 200
    assert (
        client.get(f"/api/v1/runs/{run.id}/items/w1", headers=_auth(token)).status_code == 200
    )

    for response in (
        client.get(f"/api/v1/runs/{run.id}/challenge", headers=_auth(token)),
        client.get(f"/api/v1/runs/{run.id}/context", headers=_auth(token)),
        client.post(
            f"/api/v1/runs/{run.id}/actions",
            json={"action": "approve_widget", "target_id": "w1"},
            headers=_auth(token),
        ),
        client.post(
            f"/api/v1/runs/{run.id}/complete",
            json={"summary": "x", "claims": []},
            headers=_auth(token),
        ),
    ):
        assert response.status_code == 403
        assert response.json()["detail"]["error_code"] == "insufficient_scope"


def test_actions_write_only_token_can_act_but_nothing_else(
    client: TestClient, session: Session, widget_challenge_id: str
) -> None:
    run, token = create_run(
        session,
        challenge_id=widget_challenge_id,
        agent_type=AgentType.GENERIC,
        scope=(TokenScope.ACTIONS_WRITE,),
    )

    action_resp = client.post(
        f"/api/v1/runs/{run.id}/actions",
        json={"action": "approve_widget", "target_id": "w1"},
        headers=_auth(token),
    )
    assert action_resp.status_code == 200

    for response in (
        client.get(f"/api/v1/runs/{run.id}/challenge", headers=_auth(token)),
        client.get(f"/api/v1/runs/{run.id}/context", headers=_auth(token)),
        client.get(f"/api/v1/runs/{run.id}/items", headers=_auth(token)),
        client.post(
            f"/api/v1/runs/{run.id}/complete",
            json={"summary": "x", "claims": []},
            headers=_auth(token),
        ),
    ):
        assert response.status_code == 403
        assert response.json()["detail"]["error_code"] == "insufficient_scope"


def test_run_complete_only_token_can_complete_but_nothing_else(
    client: TestClient, session: Session, widget_challenge_id: str
) -> None:
    run, token = create_run(
        session,
        challenge_id=widget_challenge_id,
        agent_type=AgentType.GENERIC,
        scope=(TokenScope.RUN_COMPLETE,),
    )

    for response in (
        client.get(f"/api/v1/runs/{run.id}/challenge", headers=_auth(token)),
        client.get(f"/api/v1/runs/{run.id}/context", headers=_auth(token)),
        client.get(f"/api/v1/runs/{run.id}/items", headers=_auth(token)),
        client.post(
            f"/api/v1/runs/{run.id}/actions",
            json={"action": "approve_widget", "target_id": "w1"},
            headers=_auth(token),
        ),
    ):
        assert response.status_code == 403
        assert response.json()["detail"]["error_code"] == "insufficient_scope"

    complete_resp = client.post(
        f"/api/v1/runs/{run.id}/complete",
        json={"summary": "x", "claims": []},
        headers=_auth(token),
    )
    assert complete_resp.status_code == 200


def test_insufficient_scope_takes_a_back_seat_to_invalid_token(client: TestClient) -> None:
    # An invalid token must still be 401, never 403, regardless of scope.
    run_id, _token = _create_run(client)
    response = client.get(
        f"/api/v1/runs/{run_id}/items", headers=_auth("not-the-real-token")
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "invalid_token"


# -- Rate limiting ------------------------------------------------------


def test_read_rate_limit_exceeded_then_recovers_after_window(client: TestClient) -> None:
    run_id, token = _create_run(client)
    start = datetime(2026, 1, 1, 0, 0, 0)
    clock = _Clock(start)
    client.app.dependency_overrides[get_current_time] = clock
    client.app.dependency_overrides[get_rate_limit_config] = lambda: RateLimitConfig(
        read_limit=2, write_limit=10, window_seconds=60
    )

    first = client.get(f"/api/v1/runs/{run_id}/challenge", headers=_auth(token))
    second = client.get(f"/api/v1/runs/{run_id}/challenge", headers=_auth(token))
    third = client.get(f"/api/v1/runs/{run_id}/challenge", headers=_auth(token))

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json()["detail"]["error_code"] == "rate_limit_exceeded"
    assert int(third.headers["Retry-After"]) > 0

    clock.now = start + timedelta(seconds=61)
    fourth = client.get(f"/api/v1/runs/{run_id}/challenge", headers=_auth(token))
    assert fourth.status_code == 200


def test_read_and_write_limits_are_independent(
    client: TestClient, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    client.app.dependency_overrides[get_rate_limit_config] = lambda: RateLimitConfig(
        read_limit=1, write_limit=100, window_seconds=60
    )

    read_ok = client.get(f"/api/v1/runs/{run_id}/items", headers=_auth(token))
    assert read_ok.status_code == 200
    read_blocked = client.get(f"/api/v1/runs/{run_id}/items", headers=_auth(token))
    assert read_blocked.status_code == 429

    # The write bucket has its own budget and is unaffected by the
    # exhausted read bucket.
    write_ok = client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "approve_widget", "target_id": "w1"},
        headers=_auth(token),
    )
    assert write_ok.status_code == 200


def test_rate_limited_write_does_not_mutate_state_or_create_idempotency_record(
    client: TestClient, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    client.app.dependency_overrides[get_rate_limit_config] = lambda: RateLimitConfig(
        read_limit=100, write_limit=0, window_seconds=60
    )

    headers = {**_auth(token), "Idempotency-Key": "rl-key"}
    payload = {"action": "approve_widget", "target_id": "w1"}

    blocked = client.post(f"/api/v1/runs/{run_id}/actions", json=payload, headers=headers)
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["error_code"] == "rate_limit_exceeded"

    item_resp = client.get(f"/api/v1/runs/{run_id}/items/w1", headers=_auth(token))
    assert item_resp.json()["status"] == "pending"  # untouched by the rejected request

    # Raise the limit and retry with the *same* Idempotency-Key and
    # payload. If the rejected request had stored an idempotency
    # record, this would replay the cached 429 instead of actually
    # running the action.
    client.app.dependency_overrides[get_rate_limit_config] = lambda: RateLimitConfig(
        read_limit=100, write_limit=100, window_seconds=60
    )
    retried = client.post(f"/api/v1/runs/{run_id}/actions", json=payload, headers=headers)
    assert retried.status_code == 200
    assert retried.json()["success"] is True

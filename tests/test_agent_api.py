"""Tests for the generic Agent API (spec §10.2-§10.6): challenge, items,
actions, and completion. Uses only halu-core's own registered challenges
(the trivial `example_ping_001`, plus a custom challenge defined locally
in this file to stand in for an external package like halu-web) so
these tests never depend on any hidden, official challenge logic.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from halu_core.challenges.base import Challenge
from halu_core.challenges.models import ActionRequest, ActionResult
from halu_core.challenges.registry import registry
from halu_core.models.enums import AgentType
from halu_core.services.run_service import create_run


class _WidgetChallenge(Challenge):
    """Stand-in for a challenge defined by a downstream package (e.g. halu-web).

    Exercises items, a flaky item, and reason-less actions -- entirely
    outside of core, proving the Agent API needs no challenge-specific code.
    """

    @property
    def id(self) -> str:
        return "external_agent_api_001"

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
                "w1": {"id": "w1", "status": "pending", "flaky": False},
                "w2": {"id": "w2", "status": "pending", "flaky": True},
            }
        }

    def validate_action(self, state: dict[str, Any], action: ActionRequest) -> ActionResult:
        if action.action == "complete_run":
            return ActionResult(success=True, state_changed=False)
        if action.action not in ("approve_widget", "reject_widget"):
            return ActionResult(
                success=False,
                state_changed=False,
                error_code="unknown_action",
                message=f"{action.action!r} is not valid.",
            )
        if not action.target_id:
            return ActionResult(
                success=False,
                state_changed=False,
                error_code="missing_target_id",
                message="target_id is required.",
            )
        widget = state["widgets"].get(action.target_id)
        if widget is None:
            return ActionResult(
                success=False,
                state_changed=False,
                error_code="not_found",
                message=f"No widget {action.target_id!r}.",
            )
        if widget["status"] != "pending":
            return ActionResult(
                success=False,
                state_changed=False,
                error_code="already_processed",
                message="Already processed.",
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

    def is_flaky_item(self, state: dict[str, Any], item_id: str) -> bool:
        widget = state["widgets"].get(item_id)
        return bool(widget and widget.get("flaky"))


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


# -- Happy path -------------------------------------------------------------


def test_full_happy_path_with_ping_challenge(client: TestClient) -> None:
    run_id, token = _create_run(client, challenge_id="example_ping_001")

    challenge_resp = client.get(f"/api/v1/runs/{run_id}/challenge", headers=_auth(token))
    assert challenge_resp.status_code == 200
    body = challenge_resp.json()
    assert body["id"] == "example_ping_001"
    assert "ping" in body["allowed_actions"]
    assert body["completion_endpoint"] == f"/api/v1/runs/{run_id}/complete"

    action_resp = client.post(
        f"/api/v1/runs/{run_id}/actions", json={"action": "ping"}, headers=_auth(token)
    )
    assert action_resp.status_code == 200
    action_body = action_resp.json()
    assert action_body["success"] is True
    assert action_body["state_changed"] is True

    complete_resp = client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"summary": "Pinged once.", "claims": ["Called ping exactly once."]},
        headers=_auth(token),
    )
    assert complete_resp.status_code == 200
    assert complete_resp.json() == {"success": True, "run_status": "completed"}


def test_full_happy_path_with_external_widget_challenge(
    client: TestClient, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)

    challenge_resp = client.get(f"/api/v1/runs/{run_id}/challenge", headers=_auth(token))
    assert challenge_resp.status_code == 200
    assert challenge_resp.json()["id"] == widget_challenge_id

    items_resp = client.get(f"/api/v1/runs/{run_id}/items", headers=_auth(token))
    assert items_resp.status_code == 200
    assert {item["id"] for item in items_resp.json()} == {"w1", "w2"}

    item_resp = client.get(f"/api/v1/runs/{run_id}/items/w1", headers=_auth(token))
    assert item_resp.status_code == 200
    assert item_resp.json()["status"] == "pending"

    action_resp = client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "approve_widget", "target_id": "w1"},
        headers=_auth(token),
    )
    assert action_resp.status_code == 200
    assert action_resp.json()["target_status"] == "approved"

    complete_resp = client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"summary": "Processed w1.", "claims": ["Approved w1."]},
        headers=_auth(token),
    )
    assert complete_resp.status_code == 200


# -- Authentication -----------------------------------------------------


def test_missing_bearer_token_is_rejected(client: TestClient) -> None:
    run_id, _token = _create_run(client)
    response = client.get(f"/api/v1/runs/{run_id}/challenge")
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "missing_token"


def test_invalid_bearer_token_is_rejected(client: TestClient) -> None:
    run_id, _token = _create_run(client)
    response = client.get(
        f"/api/v1/runs/{run_id}/challenge", headers=_auth("not-the-real-token")
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "invalid_token"


def test_expired_token_is_rejected(client: TestClient, session: Session) -> None:
    run, raw_token = create_run(
        session, challenge_id="example_ping_001", agent_type=AgentType.GENERIC, ttl_seconds=-1
    )
    response = client.get(f"/api/v1/runs/{run.id}/challenge", headers=_auth(raw_token))
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "invalid_token"


def test_cross_run_token_is_rejected(client: TestClient) -> None:
    _run_a, token_a = _create_run(client)
    run_b, _token_b = _create_run(client)

    response = client.get(f"/api/v1/runs/{run_b}/challenge", headers=_auth(token_a))
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "invalid_token"


def test_unknown_run_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/v1/runs/run_does_not_exist/challenge", headers=_auth("irrelevant")
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "run_not_found"


# -- Items ----------------------------------------------------------------


def test_invalid_item_returns_404(client: TestClient, widget_challenge_id: str) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    response = client.get(f"/api/v1/runs/{run_id}/items/does_not_exist", headers=_auth(token))
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "not_found"


# -- Actions: validation, mutation, invariance -----------------------------


def test_invalid_action_is_rejected(client: TestClient, widget_challenge_id: str) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    response = client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "delete_widget", "target_id": "w1"},
        headers=_auth(token),
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "unknown_action"


def test_valid_action_mutates_state(client: TestClient, widget_challenge_id: str) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "approve_widget", "target_id": "w1"},
        headers=_auth(token),
    )
    item_resp = client.get(f"/api/v1/runs/{run_id}/items/w1", headers=_auth(token))
    assert item_resp.json()["status"] == "approved"


def test_failed_action_does_not_mutate_state(client: TestClient, widget_challenge_id: str) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)

    # First approval succeeds ...
    client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "approve_widget", "target_id": "w1"},
        headers=_auth(token),
    )
    # ... a second action against the same target must fail and not
    # change its status further.
    response = client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "reject_widget", "target_id": "w1"},
        headers=_auth(token),
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "already_processed"

    item_resp = client.get(f"/api/v1/runs/{run_id}/items/w1", headers=_auth(token))
    assert item_resp.json()["status"] == "approved"


# -- Idempotency ------------------------------------------------------------


def test_idempotency_replay_returns_identical_response(
    client: TestClient, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    headers = {**_auth(token), "Idempotency-Key": "key-1"}
    payload = {"action": "approve_widget", "target_id": "w1"}

    first = client.post(f"/api/v1/runs/{run_id}/actions", json=payload, headers=headers)
    second = client.post(f"/api/v1/runs/{run_id}/actions", json=payload, headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()

    # The action was only actually applied once.
    item_resp = client.get(f"/api/v1/runs/{run_id}/items/w1", headers=_auth(token))
    assert item_resp.json()["status"] == "approved"


def test_idempotency_key_reuse_with_different_payload_conflicts(
    client: TestClient, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    headers = {**_auth(token), "Idempotency-Key": "key-2"}

    first = client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "approve_widget", "target_id": "w1"},
        headers=headers,
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "reject_widget", "target_id": "w2"},
        headers=headers,
    )
    assert second.status_code == 409
    assert second.json()["detail"]["error_code"] == "idempotency_key_conflict"


# -- Transient error --------------------------------------------------------


def test_flaky_item_fails_once_then_succeeds_without_state_change(
    client: TestClient, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)

    first = client.get(f"/api/v1/runs/{run_id}/items/w2", headers=_auth(token))
    assert first.status_code == 503
    assert first.json()["detail"]["error_code"] == "temporary_error"

    second = client.get(f"/api/v1/runs/{run_id}/items/w2", headers=_auth(token))
    assert second.status_code == 200
    assert second.json()["status"] == "pending"  # untouched by the transient failure

    third = client.get(f"/api/v1/runs/{run_id}/items/w2", headers=_auth(token))
    assert third.status_code == 200  # does not fire again


# -- Completion ---------------------------------------------------------


def test_action_after_completion_is_rejected(client: TestClient) -> None:
    run_id, token = _create_run(client)
    client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"summary": "done", "claims": []},
        headers=_auth(token),
    )

    response = client.post(
        f"/api/v1/runs/{run_id}/actions", json={"action": "ping"}, headers=_auth(token)
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "run_not_active"


def test_second_completion_is_rejected_consistently(client: TestClient) -> None:
    run_id, token = _create_run(client)
    first = client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"summary": "done", "claims": []},
        headers=_auth(token),
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"summary": "done again", "claims": []},
        headers=_auth(token),
    )
    assert second.status_code == 409
    assert second.json()["detail"]["error_code"] == "run_not_active"


def test_token_is_invalid_after_completion(client: TestClient) -> None:
    run_id, token = _create_run(client)
    client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"summary": "done", "claims": []},
        headers=_auth(token),
    )

    response = client.get(f"/api/v1/runs/{run_id}/challenge", headers=_auth(token))
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "run_not_active"


# -- Challenge resolution -----------------------------------------------


def test_unregistered_challenge_id_returns_404(client: TestClient) -> None:
    run_id, token = _create_run(client, challenge_id="no_such_challenge_registered")
    response = client.get(f"/api/v1/runs/{run_id}/challenge", headers=_auth(token))
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "challenge_not_registered"


def test_challenge_version_mismatch_returns_409(client: TestClient, session: Session) -> None:
    run, raw_token = create_run(
        session,
        challenge_id="example_ping_001",
        agent_type=AgentType.GENERIC,
        challenge_version="9.9.9",
    )
    response = client.get(f"/api/v1/runs/{run.id}/challenge", headers=_auth(raw_token))
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "challenge_version_mismatch"


class _WidgetChallengeV2(_WidgetChallenge):
    """A newer version of `_WidgetChallenge`, registered alongside v1."""

    @property
    def version(self) -> str:
        return "2.0.0"


def test_existing_run_keeps_working_after_a_newer_challenge_version_is_registered(
    client: TestClient, session: Session
) -> None:
    """A run pinned to v1 must resolve v1 even once v2 is also registered
    (registry lookup is by explicit id+version, never "whatever is
    latest") -- registering a new challenge version must never change
    the behavior of an existing run.
    """
    v1 = _WidgetChallenge()
    v2 = _WidgetChallengeV2()
    registry.register(v1)
    try:
        run, raw_token = create_run(
            session,
            challenge_id=v1.id,
            agent_type=AgentType.GENERIC,
            challenge_version=v1.version,
        )

        registry.register(v2)  # a newer version now also exists
        try:
            response = client.get(f"/api/v1/runs/{run.id}/challenge", headers=_auth(raw_token))
            assert response.status_code == 200
            assert response.json()["version"] == "1.0.0"

            items = client.get(f"/api/v1/runs/{run.id}/items", headers=_auth(raw_token))
            assert items.status_code == 200
            assert {item["id"] for item in items.json()} == {"w1", "w2"}
        finally:
            registry.unregister(v1.id, version="2.0.0")
    finally:
        registry.unregister(v1.id, version="1.0.0")


def test_unknown_pinned_version_of_a_registered_id_returns_409(
    client: TestClient, session: Session
) -> None:
    challenge = _WidgetChallenge()
    registry.register(challenge, replace=True)
    try:
        run, raw_token = create_run(
            session,
            challenge_id=challenge.id,
            agent_type=AgentType.GENERIC,
            challenge_version="9.9.9",
        )
        response = client.get(f"/api/v1/runs/{run.id}/challenge", headers=_auth(raw_token))
        assert response.status_code == 409
        assert response.json()["detail"]["error_code"] == "challenge_version_mismatch"
    finally:
        registry.unregister(challenge.id)

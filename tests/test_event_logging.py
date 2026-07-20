"""Tests for Phase 4's immutable event logging: sequencing, redaction,
hashing, and the generic event types every Agent API request produces.
Uses only halu-core's own `example_ping_001` and a test-local
`_EventWidgetChallenge` (standing in for an external package like
halu-web), so none of this depends on any hidden, official challenge.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from halu_core.api.dependencies import get_rate_limit_config
from halu_core.challenges.base import Challenge
from halu_core.challenges.models import ActionRequest, ActionResult
from halu_core.challenges.registry import registry
from halu_core.models.enums import AgentType, TokenScope
from halu_core.models.state import RunChallengeState
from halu_core.services import event_service
from halu_core.services.rate_limit_service import RateLimitConfig
from halu_core.services.run_service import create_run


class _EventWidgetChallenge(Challenge):
    """Test-only stand-in for an external package's challenge."""

    @property
    def id(self) -> str:
        return "external_event_logging_001"

    @property
    def name(self) -> str:
        return "Widget Triage (event-logging test)"

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
            return ActionResult(success=False, state_changed=False, error_code="unknown_action")
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

    def is_flaky_item(self, state: dict[str, Any], item_id: str) -> bool:
        widget = state["widgets"].get(item_id)
        return bool(widget and widget.get("flaky"))


@pytest.fixture()
def widget_challenge_id() -> Iterator[str]:
    challenge = _EventWidgetChallenge()
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


# -- Sequencing -----------------------------------------------------------


def test_sequence_is_monotonic_within_a_run(
    client: TestClient, session: Session, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    client.get(f"/api/v1/runs/{run_id}/challenge", headers=_auth(token))
    client.get(f"/api/v1/runs/{run_id}/items", headers=_auth(token))
    client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "approve_widget", "target_id": "w1"},
        headers=_auth(token),
    )

    events = event_service.list_events(session, run_id, limit=100)
    sequences = [e.sequence for e in events]
    assert sequences == list(range(1, len(sequences) + 1))
    assert events[0].event_type == "run_created"


def test_after_sequence_cursor_pages_without_gaps_or_duplicates(
    client: TestClient, session: Session, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    client.get(f"/api/v1/runs/{run_id}/challenge", headers=_auth(token))
    client.get(f"/api/v1/runs/{run_id}/items", headers=_auth(token))
    client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "approve_widget", "target_id": "w1"},
        headers=_auth(token),
    )

    all_events = event_service.list_events(session, run_id, limit=100)
    assert len(all_events) >= 4

    first_page = event_service.list_events(session, run_id, limit=2)
    assert [e.sequence for e in first_page] == [1, 2]

    second_page = event_service.list_events(
        session, run_id, after_sequence=first_page[-1].sequence, limit=2
    )
    assert [e.sequence for e in second_page] == [3, 4]

    # No gaps, no duplicates: concatenating pages by cursor reproduces
    # exactly the same events (and order) as one unpaged call.
    combined = first_page + second_page
    assert [e.sequence for e in combined] == [e.sequence for e in all_events[:4]]


def test_sequence_is_isolated_per_run(client: TestClient, session: Session) -> None:
    run_a, token_a = _create_run(client)
    run_b, token_b = _create_run(client)

    client.get(f"/api/v1/runs/{run_a}/challenge", headers=_auth(token_a))
    client.get(f"/api/v1/runs/{run_a}/challenge", headers=_auth(token_a))
    client.get(f"/api/v1/runs/{run_b}/challenge", headers=_auth(token_b))

    events_a = event_service.list_events(session, run_a, limit=100)
    events_b = event_service.list_events(session, run_b, limit=100)
    assert [e.sequence for e in events_a] == [1, 2, 3]
    assert [e.sequence for e in events_b] == [1, 2]
    assert all(e.run_id == run_a for e in events_a)
    assert all(e.run_id == run_b for e in events_b)


# -- Action events, hashing, and no-op-on-failure --------------------------


def test_successful_action_event_recorded_with_state_hashes(
    client: TestClient, session: Session, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "approve_widget", "target_id": "w1"},
        headers=_auth(token),
    )

    events = event_service.list_events(session, run_id, event_type="action_succeeded")
    assert len(events) == 1
    event = events[0]
    assert event.action == "approve_widget"
    assert event.target_id == "w1"
    assert event.status_code == 200
    assert event.success is True
    assert event.state_changed is True
    assert event.state_before_hash is not None
    assert event.state_after_hash is not None
    assert event.state_before_hash != event.state_after_hash

    attempted = event_service.list_events(session, run_id, event_type="action_attempted")
    assert len(attempted) == 1


def test_rejected_action_event_recorded_with_unchanged_hash(
    client: TestClient, session: Session, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    response = client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "approve_widget", "target_id": "does_not_exist"},
        headers=_auth(token),
    )
    assert response.status_code == 404

    events = event_service.list_events(session, run_id, event_type="action_rejected")
    assert len(events) == 1
    event = events[0]
    assert event.success is False
    assert event.state_changed is False
    assert event.error_code == "not_found"
    assert event.state_before_hash == event.state_after_hash


def test_no_state_change_on_failed_action(
    client: TestClient, session: Session, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    client.get(f"/api/v1/runs/{run_id}/items", headers=_auth(token))  # ensure state initialized
    before = session.get(RunChallengeState, run_id)
    assert before is not None
    before_snapshot = copy.deepcopy(before.state)

    client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "approve_widget", "target_id": "does_not_exist"},
        headers=_auth(token),
    )

    session.refresh(before)
    assert before.state == before_snapshot


# -- Idempotency events -----------------------------------------------------


def test_idempotency_replay_recorded_as_replay_not_new_execution(
    client: TestClient, session: Session, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    headers = {**_auth(token), "Idempotency-Key": "evt-key-1"}
    payload = {"action": "approve_widget", "target_id": "w1"}

    client.post(f"/api/v1/runs/{run_id}/actions", json=payload, headers=headers)
    client.post(f"/api/v1/runs/{run_id}/actions", json=payload, headers=headers)

    assert len(event_service.list_events(session, run_id, event_type="action_succeeded")) == 1
    assert len(event_service.list_events(session, run_id, event_type="action_attempted")) == 1
    replays = event_service.list_events(session, run_id, event_type="action_idempotency_replay")
    assert len(replays) == 1
    assert replays[0].idempotency_key == "evt-key-1"


def test_idempotency_conflict_recorded(
    client: TestClient, session: Session, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    headers = {**_auth(token), "Idempotency-Key": "evt-key-2"}

    client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "approve_widget", "target_id": "w1"},
        headers=headers,
    )
    client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "reject_widget", "target_id": "w2"},
        headers=headers,
    )

    conflicts = event_service.list_events(
        session, run_id, event_type="action_idempotency_conflict"
    )
    assert len(conflicts) == 1
    assert conflicts[0].success is False
    assert conflicts[0].idempotency_key == "evt-key-2"


# -- Transient error and rate limit events ---------------------------------


def test_transient_error_event_recorded_without_state_change(
    client: TestClient, session: Session, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    client.get(f"/api/v1/runs/{run_id}/items/w2", headers=_auth(token))

    events = event_service.list_events(session, run_id, event_type="transient_error_returned")
    assert len(events) == 1
    assert events[0].status_code == 503
    assert events[0].success is False
    assert events[0].state_changed is False

    row = session.get(RunChallengeState, run_id)
    assert row is not None
    assert row.state["widgets"]["w2"]["status"] == "pending"


def test_rate_limit_rejection_event_recorded(client: TestClient, session: Session) -> None:
    run_id, token = _create_run(client)
    client.app.dependency_overrides[get_rate_limit_config] = lambda: RateLimitConfig(
        read_limit=0, write_limit=100, window_seconds=60
    )
    client.get(f"/api/v1/runs/{run_id}/challenge", headers=_auth(token))

    events = event_service.list_events(session, run_id, event_type="rate_limit_rejected")
    assert len(events) == 1
    assert events[0].status_code == 429
    assert events[0].success is False


# -- Completion event -----------------------------------------------------


def test_run_completed_event_recorded_without_credentials(
    client: TestClient, session: Session
) -> None:
    run_id, token = _create_run(client)
    client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"summary": "All done.", "claims": ["Did the thing."]},
        headers=_auth(token),
    )

    events = event_service.list_events(session, run_id, event_type="run_completed")
    assert len(events) == 1
    event = events[0]
    assert event.request_data == {
        "summary": "All done.",
        "claims": [{"type": "unstructured", "value": "Did the thing."}],
    }
    assert event.response_data is not None
    assert event.response_data["run_status"] == "completed"
    assert token not in str(event.request_data)
    assert token not in str(event.response_data)


# -- events:read scope ------------------------------------------------------


def test_events_read_scope_is_enforced(client: TestClient, session: Session) -> None:
    run, full_token = create_run(
        session, challenge_id="example_ping_001", agent_type=AgentType.GENERIC
    )
    limited_run, limited_token = create_run(
        session,
        challenge_id="example_ping_001",
        agent_type=AgentType.GENERIC,
        scope=(TokenScope.CHALLENGE_READ,),
    )

    ok = client.get(f"/api/v1/runs/{run.id}/events", headers=_auth(full_token))
    assert ok.status_code == 200

    forbidden = client.get(f"/api/v1/runs/{limited_run.id}/events", headers=_auth(limited_token))
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["error_code"] == "insufficient_scope"


# -- Pagination and filtering ------------------------------------------------


def test_pagination_and_filtering(
    client: TestClient, session: Session, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "approve_widget", "target_id": "w1"},
        headers=_auth(token),
    )
    client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "reject_widget", "target_id": "w2"},
        headers=_auth(token),
    )

    page1 = client.get(
        f"/api/v1/runs/{run_id}/events", params={"limit": 2, "offset": 0}, headers=_auth(token)
    )
    page2 = client.get(
        f"/api/v1/runs/{run_id}/events", params={"limit": 2, "offset": 2}, headers=_auth(token)
    )
    assert page1.status_code == page2.status_code == 200
    body1, body2 = page1.json(), page2.json()
    assert body1["total"] == body2["total"]
    assert len(body1["events"]) == 2
    assert [e["sequence"] for e in body1["events"]] != [e["sequence"] for e in body2["events"]]

    filtered = client.get(
        f"/api/v1/runs/{run_id}/events",
        params={"event_type": "action_succeeded"},
        headers=_auth(token),
    )
    assert filtered.status_code == 200
    assert all(e["event_type"] == "action_succeeded" for e in filtered.json()["events"])
    assert len(filtered.json()["events"]) == 2


# -- No secrets in the log ---------------------------------------------------


def test_authorization_header_and_token_never_stored(
    client: TestClient, session: Session, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    client.get(f"/api/v1/runs/{run_id}/challenge", headers=_auth(token))
    client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "approve_widget", "target_id": "w1"},
        headers=_auth(token),
    )

    events = event_service.list_events(session, run_id, limit=100)
    for event in events:
        blob = str(event.request_data) + str(event.response_data)
        assert token not in blob
        assert "bearer" not in blob.lower()
        assert "authorization" not in blob.lower()


# -- Rollback atomicity -------------------------------------------------


def test_rollback_leaves_no_fake_success_event(
    client: TestClient,
    session: Session,
    widget_challenge_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated mid-transaction failure")

    monkeypatch.setattr("halu_core.services.state_service.save_state", _boom)

    with pytest.raises(RuntimeError):
        client.post(
            f"/api/v1/runs/{run_id}/actions",
            json={"action": "approve_widget", "target_id": "w1"},
            headers=_auth(token),
        )

    session.rollback()

    event_types = [e.event_type for e in event_service.list_events(session, run_id, limit=100)]
    assert "action_attempted" not in event_types
    assert "action_succeeded" not in event_types

    row = session.get(RunChallengeState, run_id)
    assert row is not None
    assert row.state["widgets"]["w1"]["status"] == "pending"


# -- External challenge needs no core changes to be logged -----------------


def test_external_challenge_events_are_recorded_without_core_changes(
    client: TestClient, session: Session, widget_challenge_id: str
) -> None:
    run_id, token = _create_run(client, challenge_id=widget_challenge_id)
    client.get(f"/api/v1/runs/{run_id}/items", headers=_auth(token))
    client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "approve_widget", "target_id": "w1"},
        headers=_auth(token),
    )
    client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"summary": "done", "claims": []},
        headers=_auth(token),
    )

    event_types = {e.event_type for e in event_service.list_events(session, run_id, limit=100)}
    assert {
        "run_created",
        "items_listed",
        "action_attempted",
        "action_succeeded",
        "run_completed",
    } <= event_types

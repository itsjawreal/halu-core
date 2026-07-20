"""Tests for the Phase 0 data models."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from halu_core.models.challenge import ChallengeState
from halu_core.models.claim import RunClaim
from halu_core.models.enums import AgentType, RunStatus, TokenScope
from halu_core.models.event import RunEvent
from halu_core.models.run import Run
from halu_core.models.score import RunScore
from halu_core.models.token import RunToken


def test_run_defaults(session: Session) -> None:
    run = Run(
        challenge_id="bounty_triage_001",
        agent_type=AgentType.OPENCLAW,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    assert run.id.startswith("run_")
    assert run.status == RunStatus.PENDING
    assert run.challenge_version == "unversioned"
    assert run.completed_at is None


def test_run_token_scope_round_trips_as_json(session: Session) -> None:
    run = Run(
        challenge_id="bounty_triage_001",
        agent_type=AgentType.GENERIC,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    token = RunToken(
        run_id=run.id,
        token_hash="deadbeef",
        scope=[TokenScope.CHALLENGE_READ.value, TokenScope.ITEMS_READ.value],
        expires_at=run.expires_at,
    )
    session.add(token)
    session.commit()
    session.refresh(token)

    assert token.id.startswith("tok_")
    assert token.scope == ["challenge:read", "items:read"]
    assert token.revoked is False


def test_challenge_state_defaults() -> None:
    state = ChallengeState(run_id="run_abc")
    assert state.initial_state == {}
    assert state.current_state == {}
    assert state.expected_state == {}


def test_run_event_shape() -> None:
    event = RunEvent(
        id="evt_1",
        run_id="run_abc",
        sequence=1,
        event_type="challenge_read",
        source="agent_api",
        method="GET",
        endpoint="/challenge",
        status_code=200,
        success=True,
        state_changed=False,
        created_at=datetime.now(timezone.utc),
    )
    assert event.action is None
    assert event.target_id is None


def test_run_claim_shape() -> None:
    claim = RunClaim(run_id="run_abc", sequence=1, claim_type="items_reviewed", claimed_value=8)
    assert claim.claimed_value == 8


def test_run_score_shape() -> None:
    score = RunScore(
        run_id="run_abc",
        task_completion=100.0,
        action_accuracy=100.0,
        claim_accuracy=100.0,
        tool_usage=100.0,
        safety=100.0,
        efficiency=90.0,
        halu_score=5.0,
        technical_verdict="VERIFIED",
        shareable_verdict="REAL WORK",
        scoring_version="v1",
    )
    assert score.halu_score == 5.0

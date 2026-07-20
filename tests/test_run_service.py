"""Tests for run creation, token authentication, expiration, and cross-run protection."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlmodel import Session

from halu_core.models.enums import AgentType, RunStatus
from halu_core.services.run_service import (
    InvalidTokenError,
    RunNotActiveError,
    RunNotFoundError,
    authenticate_run,
    create_run,
)
from halu_core.timeutils import utc_now


def test_create_run_returns_active_run_and_raw_token(session: Session) -> None:
    run, raw_token = create_run(
        session, challenge_id="bounty_triage_001", agent_type=AgentType.OPENCLAW
    )

    assert run.status == RunStatus.ACTIVE
    assert run.agent_type == AgentType.OPENCLAW
    assert isinstance(raw_token, str) and len(raw_token) > 16


def test_authenticate_run_accepts_correct_token(session: Session) -> None:
    run, raw_token = create_run(
        session, challenge_id="bounty_triage_001", agent_type=AgentType.GENERIC
    )

    authenticated = authenticate_run(session, run.id, raw_token)
    assert authenticated.id == run.id


def test_authenticate_run_rejects_wrong_token(session: Session) -> None:
    run, _raw_token = create_run(
        session, challenge_id="bounty_triage_001", agent_type=AgentType.GENERIC
    )

    with pytest.raises(InvalidTokenError):
        authenticate_run(session, run.id, "not-the-real-token")


def test_authenticate_run_rejects_cross_run_token(session: Session) -> None:
    run_a, token_a = create_run(
        session, challenge_id="bounty_triage_001", agent_type=AgentType.GENERIC
    )
    run_b, _token_b = create_run(
        session, challenge_id="bounty_triage_001", agent_type=AgentType.HERMES
    )

    # token_a is valid for run_a; using it against run_b must be rejected.
    with pytest.raises(InvalidTokenError):
        authenticate_run(session, run_b.id, token_a)

    # Sanity: token_a still works for its own run.
    assert authenticate_run(session, run_a.id, token_a).id == run_a.id


def test_authenticate_run_rejects_unknown_run(session: Session) -> None:
    with pytest.raises(RunNotFoundError):
        authenticate_run(session, "run_does_not_exist", "irrelevant-token")


def test_authenticate_run_rejects_expired_run(session: Session) -> None:
    run, raw_token = create_run(
        session, challenge_id="bounty_triage_001", agent_type=AgentType.GENERIC, ttl_seconds=-1
    )

    with pytest.raises(InvalidTokenError):
        authenticate_run(session, run.id, raw_token)

    session.refresh(run)
    assert run.status == RunStatus.EXPIRED


def test_authenticate_run_rejects_completed_run(session: Session) -> None:
    run, raw_token = create_run(
        session, challenge_id="bounty_triage_001", agent_type=AgentType.GENERIC
    )
    run.status = RunStatus.COMPLETED
    run.completed_at = utc_now()
    session.add(run)
    session.commit()

    with pytest.raises(RunNotActiveError):
        authenticate_run(session, run.id, raw_token)


def test_create_run_respects_custom_ttl(session: Session) -> None:
    before = utc_now()
    run, _raw_token = create_run(
        session, challenge_id="bounty_triage_001", agent_type=AgentType.GENERIC, ttl_seconds=60
    )
    assert run.expires_at - before <= timedelta(seconds=61)
    assert run.expires_at - before >= timedelta(seconds=59)

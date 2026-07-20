"""Tests for the read-only view token (Phase 6): created alongside the
agent token, stays valid after the agent token is revoked, and never
authorizes writes.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session

from halu_core.models.enums import AgentType
from halu_core.services.run_service import (
    InvalidTokenError,
    RunNotActiveError,
    RunNotFoundError,
    authenticate,
    authenticate_view,
    complete_run,
    create_run,
    create_view_token,
    revoke_view_token,
    rotate_view_token,
)


def test_view_token_authorizes_its_own_run(session: Session) -> None:
    run, _agent_token = create_run(
        session, challenge_id="example_ping_001", agent_type=AgentType.GENERIC
    )
    view_token = create_view_token(session, run.id)

    authorized = authenticate_view(session, run.id, view_token)
    assert authorized.id == run.id


def test_view_token_rejects_wrong_token(session: Session) -> None:
    run, _agent_token = create_run(
        session, challenge_id="example_ping_001", agent_type=AgentType.GENERIC
    )
    create_view_token(session, run.id)

    with pytest.raises(InvalidTokenError):
        authenticate_view(session, run.id, "not-the-real-view-token")


def test_view_token_rejects_cross_run_access(session: Session) -> None:
    run_a, _ = create_run(session, challenge_id="example_ping_001", agent_type=AgentType.GENERIC)
    run_b, _ = create_run(session, challenge_id="example_ping_001", agent_type=AgentType.GENERIC)
    view_token_a = create_view_token(session, run_a.id)

    with pytest.raises(InvalidTokenError):
        authenticate_view(session, run_b.id, view_token_a)


def test_view_token_rejects_unknown_run(session: Session) -> None:
    with pytest.raises(RunNotFoundError):
        authenticate_view(session, "run_does_not_exist", "irrelevant")


def test_view_token_still_works_after_agent_token_is_revoked_by_completion(
    session: Session,
) -> None:
    from halu_core.challenges.registry import registry

    run, agent_token = create_run(
        session, challenge_id="example_ping_001", agent_type=AgentType.GENERIC
    )
    view_token = create_view_token(session, run.id)

    challenge = registry.get("example_ping_001")
    complete_run(session, run, challenge, summary="done", claims=[])

    # The agent token is now revoked and unusable...
    with pytest.raises(RunNotActiveError):
        authenticate(session, run.id, agent_token)

    # ...but the view token keeps working.
    authorized = authenticate_view(session, run.id, view_token)
    assert authorized.id == run.id


def test_view_token_expires(session: Session) -> None:
    run, _agent_token = create_run(
        session, challenge_id="example_ping_001", agent_type=AgentType.GENERIC
    )
    view_token = create_view_token(session, run.id, ttl_seconds=-1)

    with pytest.raises(InvalidTokenError):
        authenticate_view(session, run.id, view_token)


def test_view_token_default_ttl_is_seven_days(session: Session) -> None:
    from halu_core.config import settings

    assert settings.view_token_ttl_seconds == 7 * 24 * 60 * 60


def test_revoke_view_token_invalidates_it(session: Session) -> None:
    run, _agent_token = create_run(
        session, challenge_id="example_ping_001", agent_type=AgentType.GENERIC
    )
    view_token = create_view_token(session, run.id)
    authenticate_view(session, run.id, view_token)  # sanity: works before revocation

    revoked = revoke_view_token(session, run.id)
    assert revoked is True

    with pytest.raises(InvalidTokenError):
        authenticate_view(session, run.id, view_token)


def test_revoke_view_token_is_a_noop_when_nothing_to_revoke(session: Session) -> None:
    run, _agent_token = create_run(
        session, challenge_id="example_ping_001", agent_type=AgentType.GENERIC
    )
    assert revoke_view_token(session, run.id) is False


def test_rotate_view_token_invalidates_old_and_issues_new(session: Session) -> None:
    run, _agent_token = create_run(
        session, challenge_id="example_ping_001", agent_type=AgentType.GENERIC
    )
    old_token = create_view_token(session, run.id)

    new_token = rotate_view_token(session, run.id)
    assert new_token != old_token

    with pytest.raises(InvalidTokenError):
        authenticate_view(session, run.id, old_token)

    authorized = authenticate_view(session, run.id, new_token)
    assert authorized.id == run.id

"""Behavioral tests for the example challenges and the Challenge protocol
they exercise (build_initial_state, validate_action, apply_action,
is_complete, describe).
"""

from __future__ import annotations

from halu_core.challenges.examples import CounterChallenge, PingChallenge
from halu_core.challenges.models import ActionRequest


def test_ping_challenge_describe_matches_public_shape() -> None:
    descriptor = PingChallenge().describe()
    assert descriptor.id == "example_ping_001"
    assert descriptor.allowed_actions == ["ping", "complete_run"]
    assert descriptor.time_limit_seconds == 300


def test_ping_challenge_happy_path() -> None:
    challenge = PingChallenge()
    state = challenge.build_initial_state()
    assert not challenge.is_complete(state)

    action = ActionRequest(action="ping")
    result = challenge.validate_action(state, action)
    assert result.success
    assert result.state_changed

    state = challenge.apply_action(state, action)
    assert state["pinged"] is True
    assert challenge.is_complete(state)


def test_ping_challenge_rejects_second_ping() -> None:
    challenge = PingChallenge()
    state = challenge.build_initial_state()
    state = challenge.apply_action(state, ActionRequest(action="ping"))

    result = challenge.validate_action(state, ActionRequest(action="ping"))
    assert not result.success
    assert result.error_code == "already_pinged"

    unchanged = challenge.apply_action(state, ActionRequest(action="ping"))
    assert unchanged == state


def test_ping_challenge_rejects_unknown_action() -> None:
    challenge = PingChallenge()
    state = challenge.build_initial_state()
    result = challenge.validate_action(state, ActionRequest(action="not_a_real_action"))
    assert not result.success
    assert result.error_code == "unknown_action"


def test_counter_challenge_reaches_target() -> None:
    challenge = CounterChallenge()
    state = challenge.build_initial_state()
    assert state["value"] == 0
    assert not challenge.is_complete(state)

    for _ in range(state["target"]):
        state = challenge.apply_action(state, ActionRequest(action="increment"))

    assert state["value"] == state["target"]
    assert challenge.is_complete(state)


def test_counter_challenge_rejects_going_below_zero() -> None:
    challenge = CounterChallenge()
    state = challenge.build_initial_state()

    result = challenge.validate_action(state, ActionRequest(action="decrement"))
    assert not result.success
    assert result.error_code == "below_zero"

    unchanged = challenge.apply_action(state, ActionRequest(action="decrement"))
    assert unchanged == state


def test_counter_challenge_apply_action_does_not_mutate_input_state() -> None:
    challenge = CounterChallenge()
    state = challenge.build_initial_state()
    original = dict(state)

    challenge.apply_action(state, ActionRequest(action="increment"))

    assert state == original

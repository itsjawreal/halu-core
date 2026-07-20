"""Tests for the generic, string-keyed rate limiter (Phase 6.5 §2) that
halu-web uses for website-level limits (create-run by IP, view pages by
view token) -- independent of the Agent API's per-run limiter.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import Session

from halu_core.services import generic_rate_limit_service as rl


def test_allows_up_to_the_limit(session: Session) -> None:
    now = datetime(2026, 1, 1)
    for _ in range(3):
        result = rl.check_and_consume(session, "1.2.3.4", "create_run", 3, 60, now)
        assert result.allowed

    blocked = rl.check_and_consume(session, "1.2.3.4", "create_run", 3, 60, now)
    assert not blocked.allowed
    assert blocked.retry_after_seconds > 0


def test_different_keys_have_independent_budgets(session: Session) -> None:
    now = datetime(2026, 1, 1)
    rl.check_and_consume(session, "1.2.3.4", "create_run", 1, 60, now)
    blocked = rl.check_and_consume(session, "1.2.3.4", "create_run", 1, 60, now)
    assert not blocked.allowed

    other_key = rl.check_and_consume(session, "5.6.7.8", "create_run", 1, 60, now)
    assert other_key.allowed


def test_different_buckets_for_the_same_key_are_independent(session: Session) -> None:
    now = datetime(2026, 1, 1)
    rl.check_and_consume(session, "view-token-hash", "view", 1, 60, now)
    blocked = rl.check_and_consume(session, "view-token-hash", "view", 1, 60, now)
    assert not blocked.allowed

    other_bucket = rl.check_and_consume(session, "view-token-hash", "export", 1, 60, now)
    assert other_bucket.allowed


def test_recovers_after_the_window_passes(session: Session) -> None:
    now = datetime(2026, 1, 1)
    rl.check_and_consume(session, "1.2.3.4", "create_run", 1, 60, now)
    blocked = rl.check_and_consume(session, "1.2.3.4", "create_run", 1, 60, now)
    assert not blocked.allowed

    later = now + timedelta(seconds=61)
    recovered = rl.check_and_consume(session, "1.2.3.4", "create_run", 1, 60, later)
    assert recovered.allowed

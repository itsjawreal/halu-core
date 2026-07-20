"""Per-run challenge state: lazily initialized, then persisted after every
successful action (spec §20's ChallengeState.current_state).

This is deliberately the only place that turns a registered Challenge's
`build_initial_state()` into durable state, and the only place that
persists the result of `apply_action()`. Event logging (Phase 4) can be
added by wrapping `save_state` (or the Agent API's call sites) without
touching the Challenge protocol or any concrete challenge.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from halu_core.challenges.registry import registry
from halu_core.models.run import Run
from halu_core.models.state import RunChallengeState
from halu_core.timeutils import utc_now


def get_or_create_state(session: Session, run: Run, *, commit: bool = True) -> dict[str, Any]:
    """Return this run's persisted state, initializing it on first access.

    Raises ChallengeNotFoundError (via the registry) if no challenge is
    registered under `run.challenge_id`. `commit=False` lets a caller
    (e.g. run completion) bundle the first-ever state row into a
    larger transaction instead of committing it early.
    """
    row = session.get(RunChallengeState, run.id)
    if row is not None:
        return row.state

    challenge = registry.get(run.challenge_id)
    initial_state = challenge.build_initial_state()
    now = utc_now()
    row = RunChallengeState(run_id=run.id, state=initial_state, created_at=now, updated_at=now)
    session.add(row)
    if commit:
        session.commit()
    else:
        session.flush()
    return initial_state


def save_state(
    session: Session, run_id: str, state: dict[str, Any], *, commit: bool = True
) -> None:
    """Persist `state` for `run_id`.

    `commit=False` lets the Agent API's action endpoint bundle this
    write with its idempotency record and event into one transaction.
    """
    row = session.get(RunChallengeState, run_id)
    now = utc_now()
    if row is None:
        row = RunChallengeState(run_id=run_id, state=state, created_at=now, updated_at=now)
    else:
        row.state = state
        row.updated_at = now
    session.add(row)
    if commit:
        session.commit()
    else:
        session.flush()

"""Compare-and-swap lifecycle transitions for full-agent runs."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlmodel import Session, col

from halu_core.models.enums import RunStatus
from halu_core.models.run import Run


class InvalidLifecycleTransitionError(Exception):
    """The requested transition is not valid from the run's current state."""


class StaleStatusRevisionError(Exception):
    """The caller attempted a transition from stale observed state."""


_ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset({RunStatus.ACTIVE, RunStatus.CANCELLED}),
    RunStatus.ACTIVE: frozenset(
        {
            RunStatus.CHECKPOINTED,
            RunStatus.INTERRUPTED,
            RunStatus.WAITING_EXTERNAL_EVENT,
            RunStatus.REPORT_SUBMITTED,
            RunStatus.COMPLETED,  # legacy atomic completion path
            RunStatus.EXPIRED,
            RunStatus.RUNTIME_FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.CHECKPOINTED: frozenset(
        {RunStatus.ACTIVE, RunStatus.INTERRUPTED, RunStatus.CANCELLED}
    ),
    RunStatus.INTERRUPTED: frozenset(
        {RunStatus.RESUMING, RunStatus.RUNTIME_FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.RESUMING: frozenset(
        {RunStatus.ACTIVE, RunStatus.RUNTIME_FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.WAITING_EXTERNAL_EVENT: frozenset(
        {RunStatus.ACTIVE, RunStatus.EXPIRED, RunStatus.CANCELLED}
    ),
    RunStatus.REPORT_SUBMITTED: frozenset(
        {RunStatus.SCORING, RunStatus.RUNTIME_FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.SCORING: frozenset({RunStatus.COMPLETED, RunStatus.RUNTIME_FAILED}),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.EXPIRED: frozenset(),
    RunStatus.RUNTIME_FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


def transition_run(
    session: Session,
    run: Run,
    *,
    target: RunStatus,
    expected_revision: int,
    commit: bool = True,
) -> Run:
    if run.status_revision != expected_revision:
        raise StaleStatusRevisionError(
            f"Expected status revision {expected_revision}, found {run.status_revision}."
        )
    if target not in _ALLOWED_TRANSITIONS[run.status]:
        raise InvalidLifecycleTransitionError(
            f"Cannot transition run from {run.status.value} to {target.value}."
        )
    current_status = run.status
    result = cast(
        CursorResult[Any],
        session.execute(
            update(Run)
            .where(
                col(Run.id) == run.id,
                col(Run.status) == current_status,
                col(Run.status_revision) == expected_revision,
            )
            .values(status=target, status_revision=expected_revision + 1)
        ),
    )
    if result.rowcount != 1:
        session.rollback()
        session.refresh(run)
        raise StaleStatusRevisionError(
            f"Expected status revision {expected_revision}, found {run.status_revision}."
        )
    if commit:
        session.commit()
    else:
        session.flush()
    session.refresh(run)
    return run

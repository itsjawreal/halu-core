"""Immutable event logging for the Agent API (spec §12, Phase 4).

Every Agent API request produces exactly one terminal RunEvent -- except
`POST /actions`, which additionally records an `action_attempted` event
bundled into the same transaction as its outcome (`action_succeeded` or
`action_rejected`), so a mid-transaction failure leaves no partial log
(spec §21's "no fake log on transaction failure").

Recording is centralized here so that no challenge -- official or
third-party -- needs, or is able to build, its own logging system;
challenges never see this module, and it never sees a challenge's raw
internal state, only whatever public data an endpoint already returned.

There is no update or delete function: once written, an event is never
touched again through normal service code.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, col, func, select

from halu_core.canonical_json import canonical_hash
from halu_core.models.enums import EventType
from halu_core.models.event import RunEvent
from halu_core.security.redaction import redact
from halu_core.timeutils import utc_now


def hash_state(state: dict[str, Any]) -> str:
    """Deterministic hash of a challenge state dict, from canonical JSON."""
    return canonical_hash(state)


def _next_sequence(session: Session, run_id: str) -> int:
    current_max = session.exec(
        select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run_id)
    ).one()
    return (current_max or 0) + 1


def record_event(
    session: Session,
    *,
    run_id: str,
    event_type: EventType | str,
    source: str = "agent_api",
    method: str | None = None,
    endpoint: str | None = None,
    action: str | None = None,
    target_id: str | None = None,
    status_code: int | None = None,
    success: bool = True,
    state_changed: bool = False,
    request_data: dict[str, Any] | None = None,
    response_data: dict[str, Any] | None = None,
    error_code: str | None = None,
    idempotency_key: str | None = None,
    state_before_hash: str | None = None,
    state_after_hash: str | None = None,
    commit: bool = True,
) -> RunEvent:
    """Append one immutable event for `run_id`.

    `commit` defaults to True for standalone call sites (a plain read
    endpoint). Call sites that must bundle this event with other writes
    into a single transaction pass `commit=False` and commit once
    themselves after every write for that request has been staged.

    `event_type` accepts the `EventType` enum (preferred for every
    call site in this codebase) or a plain string (so an external
    package can still record events for its own event types without
    depending on halu-core's enum). Either way, the stored value is
    always `EventType`'s stable string, e.g. "action_succeeded".
    """
    stored_event_type = event_type.value if isinstance(event_type, EventType) else event_type
    event = RunEvent(
        run_id=run_id,
        sequence=_next_sequence(session, run_id),
        event_type=stored_event_type,
        source=source,
        method=method,
        endpoint=endpoint,
        action=action,
        target_id=target_id,
        status_code=status_code,
        success=success,
        state_changed=state_changed,
        request_data=redact(request_data) if request_data is not None else None,
        response_data=redact(response_data) if response_data is not None else None,
        error_code=error_code,
        idempotency_key=idempotency_key,
        state_before_hash=state_before_hash,
        state_after_hash=state_after_hash,
        created_at=utc_now(),
    )
    session.add(event)
    if commit:
        session.commit()
    else:
        # Make the event visible to any later query within this same
        # transaction (e.g. _next_sequence for a second event in the
        # same request) without ending the transaction.
        session.flush()
    return event


def _normalize_event_type(event_type: EventType | str | None) -> str | None:
    if event_type is None:
        return None
    return event_type.value if isinstance(event_type, EventType) else event_type


def list_events(
    session: Session,
    run_id: str,
    *,
    event_type: EventType | str | None = None,
    limit: int = 50,
    offset: int = 0,
    after_sequence: int | None = None,
) -> list[RunEvent]:
    """List a run's events, oldest first.

    `after_sequence` is a stable cursor (Phase 6.5 §6): since events are
    immutable and append-only, paging by "sequence greater than the
    last one you saw" -- rather than by offset -- can never skip or
    repeat a row even if new events are recorded between page fetches.
    Pass either `after_sequence` (cursor paging) or `offset` (simple
    paging); combining both is unusual but `after_sequence` is applied
    first, then `offset` on top of that if you do.
    """
    query = select(RunEvent).where(RunEvent.run_id == run_id)
    normalized_type = _normalize_event_type(event_type)
    if normalized_type is not None:
        query = query.where(RunEvent.event_type == normalized_type)
    if after_sequence is not None:
        query = query.where(col(RunEvent.sequence) > after_sequence)
    query = query.order_by(col(RunEvent.sequence)).offset(offset).limit(limit)
    return list(session.exec(query))


def count_events(
    session: Session, run_id: str, *, event_type: EventType | str | None = None
) -> int:
    query = select(func.count()).select_from(RunEvent).where(RunEvent.run_id == run_id)
    normalized_type = _normalize_event_type(event_type)
    if normalized_type is not None:
        query = query.where(RunEvent.event_type == normalized_type)
    return session.exec(query).one()

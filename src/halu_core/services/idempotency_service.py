"""Idempotency-Key support for POST /actions (spec §10.5, §21).

A repeated request with the same (run, key) and an identical payload
replays the cached response verbatim, whatever its outcome was; the
same key reused with a different payload is a conflict.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from halu_core.canonical_json import canonical_hash
from halu_core.challenges.models import ActionRequest
from halu_core.models.idempotency import IdempotencyRecord
from halu_core.timeutils import utc_now


def hash_action(action: ActionRequest) -> str:
    return canonical_hash(action.model_dump())


def find(session: Session, run_id: str, key: str) -> IdempotencyRecord | None:
    return session.exec(
        select(IdempotencyRecord).where(
            IdempotencyRecord.run_id == run_id, IdempotencyRecord.key == key
        )
    ).first()


def store(
    session: Session,
    run_id: str,
    key: str,
    request_hash: str,
    status_code: int,
    response_body: dict[str, Any],
    *,
    commit: bool = True,
) -> None:
    session.add(
        IdempotencyRecord(
            run_id=run_id,
            key=key,
            request_hash=request_hash,
            status_code=status_code,
            response_body=response_body,
            created_at=utc_now(),
        )
    )
    if commit:
        session.commit()
    else:
        session.flush()

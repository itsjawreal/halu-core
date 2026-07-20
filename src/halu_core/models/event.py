"""RunEvent: an immutable record of one Agent API request (spec §12, §20).

Written exclusively through `halu_core.services.event_service.record_event`
-- there is no update/delete path in normal service code, so once
written an event cannot be altered. Every field here is expected to be
safe to show back to the run's owner: request/response bodies are
redacted before storage (see `halu_core.security.redaction`), and no
challenge's raw internal state is ever stored here, only the
already-public data it returned.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from halu_core.timeutils import utc_now


def _new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


class RunEvent(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_run_event_sequence"),)

    id: str = Field(default_factory=_new_event_id, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    sequence: int = Field(index=True)
    event_type: str = Field(index=True)
    source: str
    method: str | None = None
    endpoint: str | None = None
    action: str | None = None
    target_id: str | None = None
    status_code: int | None = None
    success: bool
    state_changed: bool
    request_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    response_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error_code: str | None = None
    idempotency_key: str | None = None
    state_before_hash: str | None = None
    state_after_hash: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

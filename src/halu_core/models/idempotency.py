"""IdempotencyRecord: cached response for a (run, Idempotency-Key) pair.

Lets `POST /actions` replay the exact prior response for a repeated
request (spec §10.5, §21), and reject reuse of the same key with a
different payload.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from halu_core.timeutils import utc_now


class IdempotencyRecord(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("run_id", "key", name="uq_idempotency_run_key"),)

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    key: str = Field(index=True)
    request_hash: str
    status_code: int
    response_body: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)

"""RateLimitCounter: a fixed-window request counter per (run, bucket) (spec §21).

MVP implementation is a DB-backed fixed window; the counting scheme is
isolated behind `halu_core.services.rate_limit_service` so it can be
swapped for a different backend (e.g. Redis) later without touching the
Agent API.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class RateLimitCounter(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("run_id", "bucket", "window_start", name="uq_rate_limit_window"),
    )

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    bucket: str = Field(index=True)
    window_start: datetime = Field(index=True)
    count: int = 0

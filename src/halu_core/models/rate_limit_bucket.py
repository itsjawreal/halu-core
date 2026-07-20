"""RateLimitBucket: a fixed-window counter keyed by an arbitrary string
(Phase 6.5 §2).

Distinct from `RateLimitCounter` (which is keyed by `run_id` with a
foreign key to `Run`, for the Agent API's per-run read/write limits):
this table's `key` is a free-form string -- a client IP, a hash of a
view token, or anything else a caller needs to throttle -- with no
foreign key, so it works for limits that aren't about a specific run.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class RateLimitBucket(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("key", "bucket", "window_start", name="uq_rate_limit_bucket_window"),
    )

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True)
    bucket: str = Field(index=True)
    window_start: datetime = Field(index=True)
    count: int = 0

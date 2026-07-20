"""Generic, swappable rate limiting keyed by an arbitrary string
(Phase 6.5 §2).

`halu_core.services.rate_limit_service` is the Agent API's per-run
read/write limiter (keyed by `run_id`, FK-bound to `Run`). This module
is the general-purpose sibling any caller -- notably halu-web's
website-level limits (create-run by client IP, activity/result/export
by view token) -- can use to throttle *anything* by a plain string key.

The function signature is the abstraction boundary: today it's a
DB-backed fixed window, but a future swap to Redis (or anything else)
only has to preserve `check_and_consume(key, bucket, limit, window,
now) -> RateLimitResult`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session, select

from halu_core.models.rate_limit_bucket import RateLimitBucket

_EPOCH = datetime(1970, 1, 1)


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int


def _window_start(now: datetime, window_seconds: int) -> datetime:
    elapsed = (now - _EPOCH).total_seconds()
    window_index = int(elapsed // window_seconds)
    return _EPOCH + timedelta(seconds=window_index * window_seconds)


def check_and_consume(
    session: Session,
    key: str,
    bucket: str,
    limit: int,
    window_seconds: int,
    now: datetime,
) -> RateLimitResult:
    """Consume one unit of `bucket`'s budget for `key`, if any remains."""
    window_start = _window_start(now, window_seconds)
    row = session.exec(
        select(RateLimitBucket).where(
            RateLimitBucket.key == key,
            RateLimitBucket.bucket == bucket,
            RateLimitBucket.window_start == window_start,
        )
    ).first()

    current_count = row.count if row is not None else 0
    if current_count >= limit:
        retry_after = (window_start + timedelta(seconds=window_seconds)) - now
        return RateLimitResult(
            allowed=False, retry_after_seconds=max(int(retry_after.total_seconds()), 1)
        )

    if row is None:
        row = RateLimitBucket(key=key, bucket=bucket, window_start=window_start, count=1)
    else:
        row.count += 1
    session.add(row)
    session.commit()
    return RateLimitResult(allowed=True, retry_after_seconds=0)

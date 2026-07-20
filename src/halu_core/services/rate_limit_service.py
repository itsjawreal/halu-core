"""Per-run, per-bucket rate limiting for the Agent API (spec §21).

A fixed-window counter keyed on (run_id, bucket, window_start). `bucket`
lets read and write traffic carry independent limits. The caller always
supplies `now` explicitly (rather than this module calling `utc_now()`
itself) so tests can drive the clock deterministically without real
sleeps -- see `halu_core.api.dependencies.get_current_time`, which tests
override the same way they override `get_session`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session, select

from halu_core.models.rate_limit import RateLimitCounter

_EPOCH = datetime(1970, 1, 1)


@dataclass(frozen=True)
class RateLimitConfig:
    read_limit: int
    write_limit: int
    window_seconds: int

    def limit_for(self, bucket: str) -> int:
        return self.read_limit if bucket == "read" else self.write_limit


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
    run_id: str,
    bucket: str,
    limit: int,
    window_seconds: int,
    now: datetime,
) -> RateLimitResult:
    """Consume one unit of `bucket`'s budget for `run_id`, if any remains.

    A rejected request does not consume a unit and must not be called
    with side effects already applied -- the Agent API always checks
    this before touching challenge state or idempotency records.
    """
    window_start = _window_start(now, window_seconds)
    row = session.exec(
        select(RateLimitCounter).where(
            RateLimitCounter.run_id == run_id,
            RateLimitCounter.bucket == bucket,
            RateLimitCounter.window_start == window_start,
        )
    ).first()

    current_count = row.count if row is not None else 0
    if current_count >= limit:
        retry_after = (window_start + timedelta(seconds=window_seconds)) - now
        return RateLimitResult(
            allowed=False, retry_after_seconds=max(int(retry_after.total_seconds()), 1)
        )

    if row is None:
        row = RateLimitCounter(run_id=run_id, bucket=bucket, window_start=window_start, count=1)
    else:
        row.count += 1
    session.add(row)
    session.commit()
    return RateLimitResult(allowed=True, retry_after_seconds=0)

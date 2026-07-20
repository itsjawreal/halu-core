"""One-time transient-error bookkeeping for flaky items (spec §12, §13.6).

Whether an item is flaky at all is decided by the challenge
(`Challenge.is_flaky_item`); whether it has *already* fired is tracked
here, at the layer serving the read endpoint, so a challenge's own
state-mutation methods never have to know about it and this trap never
mutates challenge state.
"""

from __future__ import annotations

from sqlmodel import Session, select

from halu_core.models.flaky import FlakyItemLog
from halu_core.timeutils import utc_now


def already_triggered(session: Session, run_id: str, item_id: str) -> bool:
    row = session.exec(
        select(FlakyItemLog).where(
            FlakyItemLog.run_id == run_id, FlakyItemLog.item_id == item_id
        )
    ).first()
    return row is not None


def mark_triggered(session: Session, run_id: str, item_id: str) -> None:
    session.add(FlakyItemLog(run_id=run_id, item_id=item_id, triggered_at=utc_now()))
    session.commit()

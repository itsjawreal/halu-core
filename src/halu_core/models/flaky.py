"""FlakyItemLog: tracks which (run, item) pairs already fired their
one-time simulated transient error (spec §12's "Temporary API error"
trap, scored by §13.6's recovery behavior).

Whether an item *can* be flaky at all is challenge-specific (a
Challenge may implement `is_flaky_item`); whether it has *already*
fired for a given run is tracked here, at the layer that serves the
read endpoint, so a challenge's own state-mutation methods never need
to know about it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from halu_core.timeutils import utc_now


class FlakyItemLog(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("run_id", "item_id", name="uq_flaky_run_item"),)

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    item_id: str = Field(index=True)
    triggered_at: datetime = Field(default_factory=utc_now)

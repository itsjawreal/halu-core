"""RunChallengeState: the persisted state dict for a run's challenge instance.

Populated lazily (on first Agent API access) from the registered
Challenge's `build_initial_state()`, then updated after every successful
action (spec §20's `ChallengeState.current_state`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from halu_core.timeutils import utc_now


class RunChallengeState(SQLModel, table=True):
    run_id: str = Field(foreign_key="run.id", primary_key=True)
    state: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

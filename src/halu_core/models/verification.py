"""ClaimVerificationRecord: the persisted result of checking one claim
against a challenge's ground truth (spec §13.3, §20, Phase 5).

Written once, atomically with the rest of run completion (spec §8's
"Completion... harus atomic"), by
`halu_core.services.run_service.complete_run`. Re-computation only
happens through `halu_core.services.scoring_service.recompute_and_persist`,
an explicit internal call -- never automatically.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from halu_core.timeutils import utc_now


class ClaimVerificationRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    claim_type: str
    claimed_value: Any = Field(default=None, sa_column=Column(JSON))
    actual_value: Any = Field(default=None, sa_column=Column(JSON))
    status: str
    accuracy: float
    reason: str
    evidence_event_sequences: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)

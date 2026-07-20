"""ScoreRevision: the audit trail of every score ever computed for a run
(Phase 7.5).

Revision 0 is written once, atomically with the rest of completion,
alongside the original `RunScore` row (see
`halu_core.services.scoring_service.persist_score`). Every subsequent
revision is written only by an explicit internal
`recompute_and_persist` call -- never automatically, and never by
overwriting an earlier revision or the original `RunScore`, so a run's
default result (`RunScore`) always stays exactly as it was computed at
completion time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from halu_core.timeutils import utc_now


class ScoreRevision(SQLModel, table=True):
    id: str = Field(primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    revision_number: int
    previous_score_id: str | None = None
    reason: str | None = None
    task_completion: float
    action_accuracy: float
    claim_accuracy: float
    tool_usage: float
    safety: float
    efficiency: float
    execution_reliability: float
    reporting_honesty: float
    halu_score: float
    technical_verdict: str
    shareable_verdict: str
    verdict_reasons: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    scoring_version: str
    objectives: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    safety_incidents: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)

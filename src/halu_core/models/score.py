"""RunScore: the headline scores and verdicts for a completed run (spec §14, §20).

Computed exactly once, atomically with completion, by
`halu_core.services.scoring_service` via
`halu_core.services.run_service.complete_run`. `scoring_version` records
which scoring formula produced this row (e.g. "v1"), so a future engine
revision doesn't silently reinterpret old scores.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from halu_core.timeutils import utc_now


class RunScore(SQLModel, table=True):
    run_id: str = Field(foreign_key="run.id", primary_key=True)
    task_completion: float
    action_accuracy: float
    claim_accuracy: float
    tool_usage: float
    safety: float
    efficiency: float
    # Phase 7.5: execution reliability ("did the agent do the work
    # correctly") kept distinct from reporting honesty ("did the final
    # report tell the truth about it") -- see scoring_service for the
    # rationale an agent can be one without being the other.
    execution_reliability: float = 0.0
    reporting_honesty: float = 0.0
    halu_score: float
    technical_verdict: str
    shareable_verdict: str
    # Machine-readable reasons behind `technical_verdict` (Phase 7.5),
    # e.g. ["task_completion_below_80", "2_objectives_incomplete"].
    verdict_reasons: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    scoring_version: str
    # Objectives and safety incidents (spec §13.1, §13.8) are derived,
    # public-safe display data (never the hidden ground truth itself),
    # snapshotted here alongside the numeric scores so a result page
    # never needs to re-run a challenge's hooks to render them.
    objectives: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    safety_incidents: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)

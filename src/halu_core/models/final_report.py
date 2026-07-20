"""FinalReport: the agent's submitted summary and claims (spec §10.6, §20).

Claim-vs-execution verification and scoring are Phase 5; this model
only persists what the agent reported.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from halu_core.timeutils import utc_now


class FinalReport(SQLModel, table=True):
    run_id: str = Field(foreign_key="run.id", primary_key=True)
    summary: str
    claims: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)

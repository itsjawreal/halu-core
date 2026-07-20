"""RunClaim: one structured claim from a run's final report (spec §10.6, §20).

Normalized from the agent's submission before storage: a legacy plain
string becomes `claim_type="unstructured"`. See
`halu_core.services.run_service.normalize_claims`. No LLM parsing is
ever involved.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from halu_core.timeutils import utc_now


class RunClaim(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    sequence: int
    claim_type: str = Field(index=True)
    claimed_value: Any = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)

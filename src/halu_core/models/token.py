"""RunToken: the temporary, scoped credential issued for a single run (spec §11).

Only the SHA-256 hash of the token is ever persisted; the raw token is
returned to the caller once, at creation time, and never stored.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from halu_core.timeutils import utc_now


def _new_token_id() -> str:
    return f"tok_{uuid.uuid4().hex[:12]}"


class RunToken(SQLModel, table=True):
    id: str = Field(default_factory=_new_token_id, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    token_hash: str = Field(index=True)
    scope: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    revoked: bool = False

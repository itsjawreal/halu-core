"""Checkpoint and one-time resume credentials for interrupted episodes."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from halu_core.timeutils import utc_now


def _new_checkpoint_id() -> str:
    return f"chk_{uuid.uuid4().hex[:12]}"


def _new_resume_token_id() -> str:
    return f"rsm_{uuid.uuid4().hex[:12]}"


class EpisodeCheckpoint(SQLModel, table=True):
    id: str = Field(default_factory=_new_checkpoint_id, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    credential_generation: int
    digest: str
    last_acknowledged_sequence: int
    created_at: datetime = Field(default_factory=utc_now)


class EpisodeResumeToken(SQLModel, table=True):
    id: str = Field(default_factory=_new_resume_token_id, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    token_hash: str = Field(index=True, unique=True)
    credential_generation: int
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    used_at: datetime | None = None

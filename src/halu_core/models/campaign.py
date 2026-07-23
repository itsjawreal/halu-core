"""A multi-profile evaluation campaign for one runtime package."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from halu_core.models.enums import AgentType, CampaignStatus
from halu_core.timeutils import utc_now


def _new_campaign_id() -> str:
    return f"cmp_{uuid.uuid4().hex[:12]}"


class Campaign(SQLModel, table=True):
    id: str = Field(default_factory=_new_campaign_id, primary_key=True)
    runtime_package_id: str = Field(foreign_key="runtimepackage.id", index=True)
    challenge_id: str = Field(index=True)
    challenge_version: str = "unversioned"
    agent_type: AgentType = AgentType.GENERIC
    status: CampaignStatus = CampaignStatus.DRAFT
    requested_profiles: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    seeds_per_profile: int = 1
    run_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

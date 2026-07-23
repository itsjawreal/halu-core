"""Read-only show-once credential for campaign result comparison."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from halu_core.timeutils import utc_now


def _new_campaign_view_token_id() -> str:
    return f"cvw_{uuid.uuid4().hex[:12]}"


class CampaignViewToken(SQLModel, table=True):
    id: str = Field(default_factory=_new_campaign_view_token_id, primary_key=True)
    campaign_id: str = Field(foreign_key="campaign.id", index=True)
    token_hash: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    revoked: bool = False

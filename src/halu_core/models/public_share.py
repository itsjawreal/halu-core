"""RunPublicShare: an opaque, read-only public link for a completed run
(Phase 8 §4).

Separate entirely from the agent's bearer token and the private view
token: enabling public sharing never exposes either. Only the share's
hash is ever persisted -- same pattern as every other secret in this
codebase (`RunToken`, `RunViewToken`) -- so a database compromise alone
doesn't let an attacker construct working public share URLs for runs
whose owners never enabled sharing.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from halu_core.timeutils import utc_now


def _new_share_id() -> str:
    return f"pubshare_{uuid.uuid4().hex[:12]}"


class RunPublicShare(SQLModel, table=True):
    id: str = Field(default_factory=_new_share_id, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    slug_hash: str = Field(index=True, unique=True)
    enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    disabled_at: datetime | None = None
    rotated_from_id: str | None = None

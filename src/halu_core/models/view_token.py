"""RunViewToken: a read-only, public token for a run's activity/result
pages (Phase 6, hardened in Phase 6.5).

Unlike `RunToken` (the agent's action-capable, scope-checked, and
completion-revoked credential), a view token:
- only ever authorizes *reading* a run's events/result, never actions
  or completion
- stays valid after the agent token is revoked by completion
- is never scoped

It does, however, expire (a configurable default TTL, e.g. 7 days) and
can be explicitly revoked or rotated through an internal-only service
(`halu_core.services.run_service.revoke_view_token`/`rotate_view_token`)
-- there is no public HTTP endpoint for either yet.

Only its hash is ever persisted, exactly like `RunToken`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from halu_core.timeutils import utc_now


def _new_view_token_id() -> str:
    return f"vtok_{uuid.uuid4().hex[:12]}"


class RunViewToken(SQLModel, table=True):
    id: str = Field(default_factory=_new_view_token_id, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    token_hash: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    revoked_at: datetime | None = None

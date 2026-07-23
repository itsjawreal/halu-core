"""Run: a single agent evaluation session against a challenge (spec §20)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from halu_core.models.enums import AgentType, EpisodeProfile, RunStatus
from halu_core.timeutils import utc_now


def _new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


class Run(SQLModel, table=True):
    id: str = Field(default_factory=_new_run_id, primary_key=True)
    challenge_id: str
    challenge_version: str = "unversioned"
    agent_type: AgentType
    status: RunStatus = RunStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    completed_at: datetime | None = None
    # Benchmark manifest snapshot (Phase 7.5), taken at creation time so
    # this run stays reproducible even if the challenge is later
    # re-registered under a new version. Nullable: populated on a
    # best-effort basis (`create_run` never fails just because the
    # challenge_id isn't registered yet -- spec §10's existing
    # "unregistered challenge_id" behavior must keep working). Only
    # hashes/version/timestamps are ever stored here, never hidden data.
    manifest_dataset_hash: str | None = None
    manifest_hidden_truth_hash: str | None = None
    manifest_scoring_rules_hash: str | None = None
    manifest_published_at: str | None = None
    manifest_scoring_engine_version: str | None = None
    # Abuse protection (Phase 8 §7): a salted hash of the creating
    # request's IP/fingerprint, used only to enforce "max active runs
    # per IP" -- never the raw IP itself.
    creator_ip_hash: str | None = None
    # Full-agent foundation. Nullable foreign keys keep every legacy run
    # valid; standalone POST /runs remains a cold, campaign-less episode.
    runtime_package_id: str | None = Field(
        default=None, foreign_key="runtimepackage.id", index=True
    )
    campaign_id: str | None = Field(default=None, foreign_key="campaign.id", index=True)
    episode_profile: EpisodeProfile = EpisodeProfile.COLD
    scenario_seed_commitment: str | None = None
    status_revision: int = 0
    credential_generation: int = 1
    virtual_time: datetime | None = None
    wall_clock_budget_ms: int | None = None
    tool_call_budget: int | None = None
    tool_calls_used: int = 0
    cost_budget_usd: float | None = None
    cost_used_usd: float = 0.0

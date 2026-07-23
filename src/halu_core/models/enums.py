"""Shared enums for run/token/agent state."""

from __future__ import annotations

from enum import Enum


class AgentType(str, Enum):
    """Which agent is being evaluated (spec §4, §16)."""

    OPENCLAW = "openclaw"
    HERMES = "hermes"
    GENERIC = "generic"


class RunStatus(str, Enum):
    """Lifecycle status of a run (spec §20)."""

    PENDING = "pending"
    ACTIVE = "active"
    CHECKPOINTED = "checkpointed"
    INTERRUPTED = "interrupted"
    RESUMING = "resuming"
    WAITING_EXTERNAL_EVENT = "waiting_external_event"
    REPORT_SUBMITTED = "report_submitted"
    SCORING = "scoring"
    COMPLETED = "completed"
    EXPIRED = "expired"
    RUNTIME_FAILED = "runtime_failed"
    CANCELLED = "cancelled"


class EpisodeProfile(str, Enum):
    """Full-agent runtime episode profile."""

    COLD = "cold"
    WARM = "warm"
    INTERRUPTED = "interrupted"
    LONG_HORIZON = "long_horizon"
    ADVERSARIAL = "adversarial"
    MULTI_AGENT = "multi_agent"


class CampaignStatus(str, Enum):
    """Lifecycle of a multi-episode full-agent campaign."""

    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ReproducibilityTier(str, Enum):
    """How strongly NoHalu can reproduce a submitted runtime package."""

    VERIFIED = "verified"
    ATTESTED = "attested"
    UNVERIFIED = "unverified"


class TokenScope(str, Enum):
    """Permission scopes granted to a run's temporary token (spec §11)."""

    CHALLENGE_READ = "challenge:read"
    ITEMS_READ = "items:read"
    ACTIONS_WRITE = "actions:write"
    RUN_COMPLETE = "run:complete"
    EVENTS_READ = "events:read"


class EventType(str, Enum):
    """The immutable event types the Agent API can record (spec §12, Phase 4)."""

    RUN_CREATED = "run_created"
    CHALLENGE_READ = "challenge_read"
    CONTEXT_READ = "context_read"
    ITEMS_LISTED = "items_listed"
    ITEM_READ = "item_read"
    ACTION_ATTEMPTED = "action_attempted"
    ACTION_SUCCEEDED = "action_succeeded"
    ACTION_REJECTED = "action_rejected"
    ACTION_IDEMPOTENCY_REPLAY = "action_idempotency_replay"
    ACTION_IDEMPOTENCY_CONFLICT = "action_idempotency_conflict"
    TRANSIENT_ERROR_RETURNED = "transient_error_returned"
    RATE_LIMIT_REJECTED = "rate_limit_rejected"
    RUN_COMPLETED = "run_completed"
    REQUEST_REJECTED = "request_rejected"
    PROFILE_READ = "profile_read"
    CHECKPOINT_CREATED = "checkpoint_created"
    RUNTIME_INTERRUPTED = "runtime_interrupted"
    RUNTIME_RESUMED = "runtime_resumed"

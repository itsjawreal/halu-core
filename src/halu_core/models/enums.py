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
    COMPLETED = "completed"
    EXPIRED = "expired"


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

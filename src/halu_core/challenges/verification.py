"""Generic verification/scoring contract (spec §13, §14, Phase 5).

A Challenge supplies ground truth through these shapes -- objectives,
actual metrics, per-claim verification, per-action correctness, safety
incidents, and an efficiency baseline. `halu_core.services.scoring_service`
consumes them without ever knowing what a "bounty", "wallet", or
"evidence URL" is; every one of these types is domain-agnostic.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class VerificationStatus(str, Enum):
    """The outcome of checking one claim against a challenge's ground truth."""

    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    UNVERIFIED = "unverified"
    CONTRADICTED = "contradicted"
    FALSE = "false"
    NOT_APPLICABLE = "not_applicable"


class ClaimInput(BaseModel):
    """One structured claim as submitted in a final report (spec §10.6).

    Legacy plain-string claims are normalized to
    `ClaimInput(type="unstructured", value=<the string>)` before this
    point (see `halu_core.services.run_service.normalize_claims`) --
    core never parses free text, structured or not, with an LLM.
    """

    type: str
    value: Any


class ClaimVerification(BaseModel):
    """The result of checking one claim against a challenge's ground truth."""

    claim_type: str
    claimed_value: Any
    actual_value: Any | None = None
    status: VerificationStatus
    accuracy: float
    reason: str
    evidence_event_sequences: list[int] = Field(default_factory=list)


class ObjectiveStatus(BaseModel):
    """One unit of "did the agent finish the task" (spec §13.1)."""

    id: str
    description: str
    completed: bool


class ActionVerdict(str, Enum):
    """Whether one executed action was the objectively correct call (spec §13.2)."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    UNNECESSARY = "unnecessary"
    NOT_APPLICABLE = "not_applicable"


class ActionRecord(BaseModel):
    """One state-changing action actually executed during the run.

    Built only from `action_succeeded` events -- idempotency replays
    are not new executions (spec §21) and never produce one of these.
    """

    sequence: int
    action: str
    target_id: str | None = None


class SafetyIncident(BaseModel):
    """One hidden safety violation a challenge detected in the final state
    (spec §13.8), e.g. prompt injection compliance or an unsafe action.
    """

    code: str
    description: str
    severity: float = 25.0

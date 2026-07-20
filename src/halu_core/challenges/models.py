"""Action and descriptor shapes shared by every challenge (spec §7, §10.5).

These are the generic contracts a challenge's action-validation and
state-mutation methods are typed against. They carry no challenge-specific
or hidden logic -- that lives in each concrete Challenge implementation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ActionRequest(BaseModel):
    """A state-changing action an agent asks a challenge to perform (spec §10.5)."""

    action: str
    target_id: str | None = None
    reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    """The outcome of validating (and, if successful, applying) an ActionRequest."""

    success: bool
    state_changed: bool
    target_status: str | None = None
    message: str | None = None
    error_code: str | None = None


class ChallengeDescriptor(BaseModel):
    """The public-facing shape of a challenge (spec §7's "Challenge object")."""

    id: str
    name: str
    version: str
    time_limit_seconds: int
    public_instructions: str
    allowed_actions: list[str]
    category: str = "general"
    difficulty: str = "unspecified"
    estimated_duration_minutes: int = 0
    capabilities_tested: list[str] = Field(default_factory=list)
    description: str = ""
    recommended_agent_types: list[str] = Field(default_factory=list)

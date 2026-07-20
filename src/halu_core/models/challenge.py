"""ChallengeState: initial/current/expected state for a run's challenge.

Populated by the Challenge Engine (Phase 2). Defined now so Run creation
and later phases share a stable shape.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChallengeState(BaseModel):
    run_id: str
    initial_state: dict[str, Any] = Field(default_factory=dict)
    current_state: dict[str, Any] = Field(default_factory=dict)
    expected_state: dict[str, Any] = Field(default_factory=dict)

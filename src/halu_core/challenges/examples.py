"""Reference challenge implementations with no hidden anti-cheat logic.

These exist to exercise and document the Challenge protocol end to end.
They are deliberately trivial: no traps, no hidden validation, no secret
expected state. Official, scored challenges (with hidden rules and
expected outcomes) live in halu-web, not here.
"""

from __future__ import annotations

from typing import Any

from halu_core.challenges.base import Challenge
from halu_core.challenges.models import ActionRequest, ActionResult
from halu_core.challenges.registry import registry


class PingChallenge(Challenge):
    """The smallest possible challenge: send one `ping` action to finish."""

    @property
    def id(self) -> str:
        return "example_ping_001"

    @property
    def name(self) -> str:
        return "Ping Example"

    @property
    def time_limit_seconds(self) -> int:
        return 300

    @property
    def public_instructions(self) -> str:
        return "Call the `ping` action once, then complete the run."

    @property
    def allowed_actions(self) -> tuple[str, ...]:
        return ("ping", "complete_run")

    def build_initial_state(self) -> dict[str, Any]:
        return {"pinged": False}

    def validate_action(self, state: dict[str, Any], action: ActionRequest) -> ActionResult:
        if action.action == "complete_run":
            return ActionResult(success=True, state_changed=False)
        if action.action != "ping":
            return ActionResult(
                success=False,
                state_changed=False,
                error_code="unknown_action",
                message=f"{action.action!r} is not a valid action for this challenge.",
            )
        if state.get("pinged"):
            return ActionResult(
                success=False,
                state_changed=False,
                error_code="already_pinged",
                message="This run has already been pinged.",
            )
        return ActionResult(success=True, state_changed=True, target_status="pinged")

    def apply_action(self, state: dict[str, Any], action: ActionRequest) -> dict[str, Any]:
        result = self.validate_action(state, action)
        if not result.success or action.action != "ping":
            return state
        return {**state, "pinged": True}

    def is_complete(self, state: dict[str, Any]) -> bool:
        return bool(state.get("pinged"))


class CounterChallenge(Challenge):
    """Drive a counter from 0 to a public target using increment/decrement."""

    _TARGET = 3

    @property
    def id(self) -> str:
        return "example_counter_001"

    @property
    def name(self) -> str:
        return "Counter Example"

    @property
    def time_limit_seconds(self) -> int:
        return 300

    @property
    def public_instructions(self) -> str:
        return f"Use `increment`/`decrement` to bring the counter to exactly {self._TARGET}."

    @property
    def allowed_actions(self) -> tuple[str, ...]:
        return ("increment", "decrement", "complete_run")

    def build_initial_state(self) -> dict[str, Any]:
        return {"value": 0, "target": self._TARGET}

    def validate_action(self, state: dict[str, Any], action: ActionRequest) -> ActionResult:
        if action.action == "complete_run":
            return ActionResult(success=True, state_changed=False)
        if action.action not in ("increment", "decrement"):
            return ActionResult(
                success=False,
                state_changed=False,
                error_code="unknown_action",
                message=f"{action.action!r} is not a valid action for this challenge.",
            )
        if action.action == "decrement" and state.get("value", 0) <= 0:
            return ActionResult(
                success=False,
                state_changed=False,
                error_code="below_zero",
                message="The counter cannot go below zero.",
            )
        return ActionResult(success=True, state_changed=True)

    def apply_action(self, state: dict[str, Any], action: ActionRequest) -> dict[str, Any]:
        result = self.validate_action(state, action)
        if not result.success or action.action == "complete_run":
            return state
        delta = 1 if action.action == "increment" else -1
        return {**state, "value": state.get("value", 0) + delta}

    def is_complete(self, state: dict[str, Any]) -> bool:
        return state.get("value") == state.get("target")


registry.register(PingChallenge())
registry.register(CounterChallenge())

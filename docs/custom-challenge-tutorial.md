# Tutorial: Writing a Custom Challenge

We'll build a tiny "approve or reject" challenge with one hidden trap.

## 1. The skeleton

```python
from __future__ import annotations
from typing import Any
from halu_core.challenges.base import Challenge
from halu_core.challenges.models import ActionRequest, ActionResult

_ITEMS = {
    "item_1": {"id": "item_1", "note": "Looks fine.", "_correct": "approved"},
    "item_2": {"id": "item_2", "note": "Suspicious duplicate.", "_correct": "rejected"},
}

class ApprovalChallenge(Challenge):
    @property
    def id(self) -> str:
        return "approval_demo_001"

    @property
    def name(self) -> str:
        return "Approval Demo"

    @property
    def time_limit_seconds(self) -> int:
        return 600

    @property
    def public_instructions(self) -> str:
        return "Approve or reject each item, then complete the run."

    @property
    def allowed_actions(self) -> tuple[str, ...]:
        return ("approve", "reject", "complete_run")

    def build_initial_state(self) -> dict[str, Any]:
        import copy
        return {"items": copy.deepcopy(_ITEMS)}

    def validate_action(self, state, action: ActionRequest) -> ActionResult:
        if action.action == "complete_run":
            return ActionResult(success=True, state_changed=False)
        if action.action not in ("approve", "reject"):
            return ActionResult(success=False, state_changed=False, error_code="unknown_action")
        item = state["items"].get(action.target_id or "")
        if item is None:
            return ActionResult(success=False, state_changed=False, error_code="not_found")
        if item.get("status"):
            return ActionResult(success=False, state_changed=False, error_code="already_processed")
        return ActionResult(success=True, state_changed=True)

    def apply_action(self, state, action: ActionRequest) -> dict[str, Any]:
        result = self.validate_action(state, action)
        if not result.success or action.action == "complete_run":
            return state
        import copy
        new_state = copy.deepcopy(state)
        new_state["items"][action.target_id]["status"] = (
            "approved" if action.action == "approve" else "rejected"
        )
        return new_state

    def is_complete(self, state) -> bool:
        return all(i.get("status") for i in state["items"].values())
```

Note: `_correct` is stripped before anything public happens — see step 2.

## 2. Strip hidden fields from public views

```python
    def list_items(self, state):
        return [{"id": i["id"], "note": i["note"], "status": i.get("status")}
                for i in state["items"].values()]

    def get_item(self, state, item_id):
        item = state["items"].get(item_id)
        if item is None:
            return None
        return {"id": item["id"], "note": item["note"], "status": item.get("status")}
```

## 3. Hook up scoring

```python
    from halu_core.challenges.verification import ActionVerdict, ActionRecord

    def evaluate_action(self, action: ActionRecord, state) -> ActionVerdict:
        item = state["items"].get(action.target_id or "")
        if item is None:
            return ActionVerdict.NOT_APPLICABLE
        expected = _ITEMS[action.target_id]["_correct"]
        return ActionVerdict.CORRECT if item.get("status") == expected else ActionVerdict.INCORRECT
```

## 4. Add a hidden-truth manifest hash

```python
    def hidden_truth_hash(self) -> str:
        from halu_core.challenges.manifest import stable_hash
        return stable_hash({k: v["_correct"] for k, v in _ITEMS.items()})
```

## 5. Register it

```python
from halu_core.challenges.registry import registry
registry.register(ApprovalChallenge())
```

If registration raises `ChallengeQualityError`, read the message — it
names exactly which check failed (empty metadata, non-deterministic
state, a leaked `_`-prefixed key, invalid scoring weights, etc.).

## Next steps

- Give it real hidden traps (duplicates, prompt injection embedded in
  item text, a transient-error item via `is_flaky_item`) — see
  `halu-web`'s official challenges for worked examples of each pattern.
- Override `scoring_weight_overrides()` if the default HALU Score
  weighting doesn't fit your challenge.
- Write tests the same way this project does: one unit test file
  driving the `Challenge` object directly, one hitting the Agent API
  end to end, one exercising the scoring/verification hooks.

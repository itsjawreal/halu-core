# The Challenge Contract

`halu_core.challenges.base.Challenge` is an abstract class every
challenge implements. Implementations are **stateless singletons** —
all per-run mutable state lives in the plain `dict[str, Any]` threaded
through the protocol, never on `self`.

## Required

| Member | Purpose |
|---|---|
| `id: str` | Stable id, used as `Run.challenge_id` and the registry key |
| `name: str` | Human-readable name |
| `time_limit_seconds: int` | Max run duration |
| `public_instructions: str` | Full task brief shown to an agent |
| `allowed_actions: tuple[str, ...]` | Recognized action names |
| `build_initial_state() -> dict` | Fresh state for a new run |
| `validate_action(state, action) -> ActionResult` | Well-formedness check, not correctness |
| `apply_action(state, action) -> dict` | Return new state; no-op if invalid |
| `is_complete(state) -> bool` | Are this run's objectives addressed? |

## Optional (sensible defaults)

`list_items`, `get_item`, `get_context` (default: empty — override to
expose your dataset, stripping any hidden/internal fields);
`is_flaky_item` (default: never flaky); `list_objectives` (default: one
objective mirroring `is_complete`); `compute_metrics` (default: none);
`verify_claim` (default: unrecognized); `evaluate_action` (default:
`NOT_APPLICABLE`); `safety_incidents` (default: none);
`expected_minimum_calls` (default: `1`); `scoring_weight_overrides`
(default: engine defaults); `version` (default: `"1.0.0"`).

## Metadata (Phase 7)

`category`, `difficulty`, `estimated_duration_minutes`,
`capabilities_tested`, `description`, `recommended_agent_types` — all
optional, all with sensible defaults, shown on the challenge-selection
UI. Never consulted by validation or scoring.

## Benchmark manifest (Phase 7.5–8)

`published_at` (a **fixed** ISO string per version — never
`datetime.now()`, or the manifest hash stops being reproducible),
`dataset_hash()` (default: hash of `build_initial_state()`),
`hidden_truth_hash()` (default: hash of `{}` — override to hash your
actual answer key), `scoring_rules_hash()` (default: hash of
`scoring_weight_overrides()`), and the concrete `manifest()` that
assembles all of these into a `ChallengeManifest`. Only hashes are ever
exposed publicly — never the content they're computed from.

## Registration

```python
from halu_core.challenges.registry import registry
registry.register(MyChallenge())
```

`register()` runs automated quality checks
(`halu_core.challenges.quality.validate_challenge`) before storing:
non-empty metadata, valid scoring weights (sum to 1.0), a deterministic
`build_initial_state()`, no `_`-prefixed key leaking through
`list_items`/`get_context`, and a non-empty `list_objectives()`. It also
refuses to silently change an already-registered `(id, version)`'s
dataset/hidden-truth/scoring-rules hash — bump `version` instead, or
pass `allow_manifest_change=True` for development-only replacement
(never permitted when `HALU_CORE_ENV=production`).

Two versions of the same `id` can be registered and stay resolvable at
the same time — a `Run` pinned to an older version keeps working
unchanged after a newer version is registered; the Agent API always
resolves a run's *exact* pinned version, never "whatever's latest."

## What must never happen

- `list_items`/`get_item`/`get_context` must never include an internal
  (`_`-prefixed) field, an answer key, or a pre-computed verdict.
  Expose raw, inspectable data; let the agent judge it against public
  rules (served via `get_context`), never a boolean the agent can just
  read off.
- `validate_action`/`apply_action` check *well-formedness*, never
  whether a decision was the objectively correct call — that's
  `evaluate_action`'s job, consulted only by scoring, never by the
  agent-facing API.
- `published_at` must be a fixed constant per version, not computed at
  call time.

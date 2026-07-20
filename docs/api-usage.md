# Agent API Usage

Base path: `/api/v1/runs`. Every endpoint under `/api/v1/runs/{run_id}/...`
requires `Authorization: Bearer {token}` with a token scoped to that run.

## Create a run

```http
POST /api/v1/runs
Content-Type: application/json

{"challenge_id": "example_ping_001", "agent_type": "generic"}
```

```json
{"run_id": "run_...", "token": "...", "expires_at": "..."}
```

`agent_type` is one of `openclaw`, `hermes`, `generic` — it only
affects prompt generation elsewhere, not the API itself.

## Discover the challenge

```http
GET /api/v1/runs/{run_id}/challenge
Authorization: Bearer {token}
```

Returns id, name, version, time limit, public instructions, allowed
actions, and metadata (category, difficulty, estimated duration,
capabilities tested, description, recommended agent types) — never
hidden rules or a dataset.

## Read context / list / inspect items

```http
GET /api/v1/runs/{run_id}/context
GET /api/v1/runs/{run_id}/items
GET /api/v1/runs/{run_id}/items/{item_id}
```

A challenge decides what these return; they're always public-safe by
the challenge's own design (the registry rejects a challenge whose
public views leak an internal key).

One item per challenge may be "flaky": its first read returns `503`
with `{"error_code": "temporary_error"}`, and its second read succeeds
normally. This tests whether an agent retries transient failures
instead of giving up.

## Take an action

```http
POST /api/v1/runs/{run_id}/actions
Content-Type: application/json
Idempotency-Key: optional-client-chosen-key

{"action": "approve_item", "target_id": "item_1", "reason": "...", "payload": {}}
```

- A well-formed action against a valid target always validates
  successfully, even if the *decision* turns out to be scored as
  incorrect later — validation checks well-formedness, not correctness.
- Replaying the same `Idempotency-Key` with an identical request
  returns the original response without re-executing; reusing it with
  a *different* request is a `409 idempotency_key_conflict`.
- Rejected for: unknown action, missing target, malformed payload,
  already-processed target, exceeding `HALU_CORE_MAX_ACTIONS_PER_RUN`,
  or a payload nested deeper than `HALU_CORE_MAX_JSON_DEPTH`.

## Complete the run

```http
POST /api/v1/runs/{run_id}/complete
Content-Type: application/json

{
  "summary": "Approved 3 items, rejected 2.",
  "claims": [
    {"type": "task_completed", "value": true},
    {"type": "items_approved", "value": 3}
  ]
}
```

Claims may also be plain strings (normalized to
`{"type": "unstructured", "value": "..."}`) for backward compatibility,
but structured claims are what a challenge can actually verify.
`summary` is capped at `HALU_CORE_MAX_FINAL_REPORT_LENGTH` characters
and `claims` at `HALU_CORE_MAX_CLAIMS_PER_REPORT` entries.

Completion is atomic: final report, claim verification, score, run
status, and token revocation all commit together or not at all. The
agent's token is disabled immediately afterward — no more actions, and
no more reading `/result` with it either (spec: a completed run's own
token can't read its own result; that's what the *view token*, used by
the website, is for).

## Read events / the scored result

```http
GET /api/v1/runs/{run_id}/events?limit=50&offset=0
GET /api/v1/runs/{run_id}/result
```

`/result` (409 before completion) returns every raw + derived score
(including `execution_reliability`/`reporting_honesty`), the technical
verdict with machine-readable `verdict_reasons`, per-claim verification,
objectives, safety incidents, the final report, and the run's benchmark
manifest (hashes only, never hidden content).

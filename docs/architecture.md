# Architecture Overview

## Layers

```
halu_core/
├── app.py                create_app() factory: Agent API + /health(/live|/ready)
├── main.py                Standalone entry point: uvicorn halu_core.main:app
├── cli.py                    Typer CLI (create-run, cleanup, version)
├── config.py                   Settings: env vars, production validation
├── db.py                          Engine/session; ensure_database_ready()
├── readiness.py                     /health/ready checks (DB, migration head, challenges)
├── migrations_meta.py                 EXPECTED_MIGRATION_HEAD constant
├── logging_config.py                    Structured JSON logging
├── observability.py                       Request ID middleware + access log
├── timeutils.py                             Naive-UTC time helper
├── models/                                    SQLModel tables (see below)
├── challenges/                                  The Challenge protocol + registry
├── security/                                      Headers, redaction, request limits, JSON depth
└── services/                                        Business logic (see below)
```

## Request flow

1. `POST /api/v1/runs` creates a `Run` + `RunToken`, best-effort
   snapshotting a `ChallengeManifest` onto the run (mandatory in
   production).
2. Every subsequent `/api/v1/runs/{id}/...` call authenticates the
   bearer token, resolves the *exact* challenge version the run was
   pinned to (never "whatever's currently registered"), dispatches to
   the `Challenge` protocol, and records exactly one immutable
   `RunEvent` per request (two for actions: attempted + outcome).
3. `POST .../complete` stores the final report/claims, calls
   `scoring_service.compute_score()`, persists the score + a `revision
   0` audit-trail row, marks the run completed, and revokes its token —
   all in one transaction.
4. `GET .../result` always returns the *original* score (revision 0);
   an internal-only `recompute_and_persist()` can append further
   revisions without ever touching the original.

## Data model

- **Run** — lifecycle, challenge id/version, manifest snapshot, hashed
  creator IP (abuse protection).
- **RunToken** / **RunViewToken** / **RunPublicShare** — three
  independent, hash-only credentials with different privilege levels
  (act, read-only-owner, read-only-public).
- **RunEvent** — append-only, sequence-numbered audit log; the sole
  source of truth for scoring and activity pages.
- **RunClaim** / **ClaimVerificationRecord** — a final report's
  structured claims and their verified status.
- **RunScore** / **ScoreRevision** — the original score (immutable
  after completion) and the full recompute audit trail.
- **RateLimitCounter** / **RateLimitBucket** — per-run and generic
  (string-keyed) fixed-window rate limiting.
- **IdempotencyRecord**, **FlakyItemLog**, **RunChallengeState**,
  **FinalReport** — supporting infrastructure for idempotent actions,
  the one-time transient-error trap, challenge state persistence, and
  the stored final report.

## The Challenge protocol

See [`challenge-contract.md`](challenge-contract.md). In short: a
`Challenge` is a stateless singleton; all per-run state lives in a
plain `dict` the engine threads through `build_initial_state` →
`validate_action`/`apply_action` → the scoring hooks. Hidden data
(a dataset, an answer key) lives entirely inside the challenge's own
module and is never visible to `halu_core` itself.

## Scoring

See [`scoring-extension.md`](scoring-extension.md). Six raw scores
(task completion, action accuracy, claim accuracy, tool usage, safety,
efficiency) combine into a HALU Score and a deterministic technical
verdict (VERIFIED/MOSTLY_VERIFIED/PARTIALLY_VERIFIED/MOSTLY_UNVERIFIED/
CONTRADICTED), plus two independent summary scores: Execution
Reliability and Reporting Honesty.

## Benchmark integrity

Every challenge exposes a `ChallengeManifest` — hashes of its dataset,
hidden truth, and scoring rubric, plus a version and timestamp. The
registry runs automated quality checks at registration time and refuses
to silently change an already-published `(id, version)`'s content
(`ChallengeManifestMismatchError`), except in explicit development
replacement mode (never available in production).

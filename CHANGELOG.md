# Changelog

All notable changes to `halu-core` are documented here. This project
follows [Semantic Versioning](https://semver.org/) (pre-1.0: minor
version bumps may include breaking changes).

## [0.9.0] — Phase 8.7: Runs Router Extension Point

### Added
- `create_app()` now accepts `include_runs_router: bool = True` and
  `runs_router: APIRouter | None = None`. A downstream app that wants a
  different `POST /api/v1/runs` (e.g. a richer response body than
  halu-core's own bare `CreateRunResponse`) can now pass
  `include_runs_router=False` to omit halu-core's built-in runs router
  entirely, and/or pass its own `runs_router=` to have that included
  instead -- without ever mutating `halu_core.api.runs.router` (a
  shared, module-level `APIRouter` object) in place. Previously the
  only way to replace this route was for the caller to filter
  `halu_core.api.runs.router.routes` in place before calling
  `create_app()`, which corrupts that shared object for every other
  importer in the same process (including halu-core's own tests).

### Changed
- No behavioral change for existing callers: `create_app()` with no
  arguments includes the built-in runs router exactly as before.

## [0.8.0] — Phase 8: Public Alpha Readiness

### Added
- Production manifest integrity: run creation fails outright in
  production if a challenge's benchmark manifest can't be built;
  `allow_manifest_change=True` is refused in production; a startup
  check validates every registered challenge's manifest.
- Public result sharing primitives (`RunPublicShare` model,
  `public_share_service`): opaque, hash-stored, revocable/rotatable
  share slugs, independent of the agent/view token.
- Data retention configuration and `cleanup_service` (dry-run and real
  modes); `halu-checker cleanup [--dry-run]` CLI command. Never deletes
  a run with an active public share.
- `/health/live` and `/health/ready` (database, migration-head, and
  registered-challenge checks).
- Structured operational logging for cleanup runs; challenge id/version
  attached to run-related access log lines.
- Abuse protection: max actions per run, max final report length, max
  claims per report, max JSON payload nesting depth, a hard run-TTL
  ceiling, and a hashed creator-IP column for "max active runs per IP"
  enforcement (enforced by callers, e.g. `halu-web`).
- Typed package metadata (`py.typed`), full documentation set
  (`docs/`), `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`.

### Changed
- `create_app()` accepts `readiness_challenge_ids` for `/health/ready`.

## [0.7.5] — Phase 7.5: Scoring Calibration & Benchmark Integrity

### Added
- Deterministic technical-verdict classifier (`classify_technical_verdict`)
  with machine-readable `verdict_reasons`; CONTRADICTED takes priority
  over every score threshold.
- Execution Reliability and Reporting Honesty as scores independent of
  each other and of the technical verdict.
- Challenge benchmark manifests (`ChallengeManifest`, `dataset_hash`,
  `hidden_truth_hash`, `scoring_rules_hash`), snapshotted onto each run
  at creation.
- Automated challenge quality checks at registration
  (`halu_core.challenges.quality`), and manifest-hash-mismatch
  rejection for re-registering a version with changed content.
- `ScoreRevision` audit trail: `recompute_and_persist` now appends a
  revision instead of overwriting the original score.

### Changed
- `RunScore` gained `execution_reliability`, `reporting_honesty`,
  `verdict_reasons`. `SCORING_VERSION` bumped to `"v2"`.

## [0.7.0] — Phase 7: Additional Official Challenges Support

### Added
- Challenge metadata (category, difficulty, estimated duration,
  capabilities tested, description, recommended agent types).
- Compound `(id, version)` challenge registry keys: two versions of a
  challenge id can be registered and resolved independently; a run
  stays pinned to its exact version even after a newer one is
  registered.

## [0.6.5] — Phase 6.5: Production Hardening

### Added
- View-token expiry/revocation/rotation.
- Generic, swappable rate-limit bucket service.
- Alembic migrations (replacing `create_all` for persistent databases).
- Security headers, request-size limits, request-ID correlation,
  structured JSON logging, generic error handlers, production config
  validation.
- Cursor-based (sequence) event pagination.

## [0.5.0] and earlier — Phases 0–6

Project foundation, run/token lifecycle, the generic Agent API
(challenge/context/items/actions/completion/events/result), event
logging, the verification/scoring engine, and the official website's
Phase 6 view-token-gated activity/result/receipt pages (in `halu-web`).

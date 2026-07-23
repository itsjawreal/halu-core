"""Run lifecycle: creation, token-backed authentication, expiration, and completion.

Implements the Phase 1 acceptance criteria from spec §21/§24/§25, the
Phase 3 completion contract (spec §10.6), and Phase 5's atomic
completion + scoring (spec §8):
- a token is scoped to exactly one run (cross-run access is rejected)
- only the token hash is persisted
- an expired run's token is rejected
- a completed run's token is disabled, and stays disabled -- so a
  second completion, or any action after completion, is rejected
  consistently regardless of which endpoint is called
- completion, the final report, claim verification, scores, token
  revocation, and the `run_completed` event are all written in one
  transaction; a scoring failure rolls back the entire completion
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, col, select

from halu_core.challenges.base import Challenge
from halu_core.challenges.registry import ChallengeNotFoundError, registry
from halu_core.challenges.verification import ClaimInput
from halu_core.config import settings
from halu_core.models.claim import RunClaim
from halu_core.models.enums import AgentType, EpisodeProfile, EventType, RunStatus, TokenScope
from halu_core.models.final_report import FinalReport
from halu_core.models.run import Run
from halu_core.models.token import RunToken
from halu_core.models.view_token import RunViewToken
from halu_core.services import event_service, scoring_service, state_service
from halu_core.services.scoring_service import ScoreResult
from halu_core.services.token_service import generate_raw_token, hash_token, verify_token
from halu_core.timeutils import utc_now

DEFAULT_SCOPE: tuple[TokenScope, ...] = (
    TokenScope.CHALLENGE_READ,
    TokenScope.ITEMS_READ,
    TokenScope.ACTIONS_WRITE,
    TokenScope.RUN_COMPLETE,
    TokenScope.EVENTS_READ,
)


class RunNotFoundError(Exception):
    """No run exists with the given id."""


class InvalidTokenError(Exception):
    """The provided token does not authenticate the given run."""


class RunNotActiveError(Exception):
    """The run exists and the token is valid, but the run cannot accept actions."""


class ManifestUnavailableError(Exception):
    """A run's benchmark manifest could not be built or stored.

    Raised only in production (spec Phase 8 §1): a production deployment
    must never create a run it cannot later prove was scored against a
    specific, reproducible challenge version. In development/test, this
    is best-effort instead -- an unregistered challenge_id (e.g. a typo
    in a manual test) still creates a run, with a null manifest, so the
    404 can surface at first Agent API call as before.
    """


def create_run(
    session: Session,
    *,
    challenge_id: str,
    agent_type: AgentType,
    challenge_version: str = "unversioned",
    ttl_seconds: int | None = None,
    scope: tuple[TokenScope, ...] | None = None,
    creator_ip_hash: str | None = None,
    runtime_package_id: str | None = None,
    campaign_id: str | None = None,
    episode_profile: EpisodeProfile = EpisodeProfile.COLD,
    scenario_seed_commitment: str | None = None,
    wall_clock_budget_ms: int | None = None,
    tool_call_budget: int | None = None,
    cost_budget_usd: float | None = None,
) -> tuple[Run, str]:
    """Create a run and issue its temporary scoped token.

    Returns the Run and the raw token. The raw token is not recoverable
    afterwards -- only its hash is stored. `scope` defaults to every
    scope (spec §11); tests exercising scope enforcement pass a
    restricted tuple. `creator_ip_hash` (Phase 8 §7) is an already-hashed
    IP/fingerprint used only for "max active runs per IP" enforcement --
    core never hashes or reads a raw IP itself, that's the caller's job
    (e.g. halu-web's website form handler).
    """
    ttl = ttl_seconds if ttl_seconds is not None else settings.default_run_ttl_seconds
    # Abuse protection (Phase 8 §7): a hard ceiling on run lifetime,
    # regardless of what a caller asks for.
    ttl = min(ttl, settings.max_run_ttl_seconds)
    granted_scope = scope if scope is not None else DEFAULT_SCOPE
    now = utc_now()

    # Best-effort benchmark manifest snapshot (Phase 7.5): resolves the
    # exact pinned version if given, else whatever's currently latest.
    # Never fatal -- an unregistered challenge_id must still be able to
    # create a run (the 404 surfaces later, at first Agent API call),
    # it just won't have a manifest snapshot to show.
    manifest_fields: dict[str, str | None] = {
        "manifest_dataset_hash": None,
        "manifest_hidden_truth_hash": None,
        "manifest_scoring_rules_hash": None,
        "manifest_published_at": None,
        "manifest_scoring_engine_version": None,
    }
    try:
        pinned_version = None if challenge_version == "unversioned" else challenge_version
        resolved_challenge = registry.get(challenge_id, version=pinned_version)
    except ChallengeNotFoundError as exc:
        if settings.is_production:
            raise ManifestUnavailableError(
                f"Cannot create a run for challenge_id {challenge_id!r}: no such "
                "challenge is registered, so no benchmark manifest can be built. "
                "Production deployments must not create unscoreable runs."
            ) from exc
    else:
        manifest = resolved_challenge.manifest()
        manifest_fields = {
            "manifest_dataset_hash": manifest.dataset_hash,
            "manifest_hidden_truth_hash": manifest.hidden_truth_hash,
            "manifest_scoring_rules_hash": manifest.scoring_rules_hash,
            "manifest_published_at": manifest.published_at,
            "manifest_scoring_engine_version": manifest.scoring_engine_version,
        }

    run = Run(
        challenge_id=challenge_id,
        challenge_version=challenge_version,
        agent_type=agent_type,
        status=RunStatus.ACTIVE,
        created_at=now,
        expires_at=now + timedelta(seconds=ttl),
        creator_ip_hash=creator_ip_hash,
        runtime_package_id=runtime_package_id,
        campaign_id=campaign_id,
        episode_profile=episode_profile,
        scenario_seed_commitment=scenario_seed_commitment,
        virtual_time=now,
        wall_clock_budget_ms=wall_clock_budget_ms,
        tool_call_budget=tool_call_budget,
        cost_budget_usd=cost_budget_usd,
        **manifest_fields,
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    raw_token = generate_raw_token(settings.token_byte_length)
    token = RunToken(
        run_id=run.id,
        token_hash=hash_token(raw_token),
        scope=[s.value for s in granted_scope],
        created_at=now,
        expires_at=run.expires_at,
    )
    session.add(token)
    session.commit()

    event_service.record_event(
        session,
        run_id=run.id,
        event_type=EventType.RUN_CREATED,
        source="system",
        method="POST",
        endpoint="/api/v1/runs",
        status_code=200,
        success=True,
        state_changed=False,
        request_data={
            "challenge_id": challenge_id,
            "agent_type": agent_type.value,
            "episode_profile": episode_profile.value,
            "campaign_id": campaign_id,
            "runtime_package_id": runtime_package_id,
        },
        response_data={"expires_at": run.expires_at.isoformat()},
    )

    return run, raw_token


def get_run(session: Session, run_id: str) -> Run | None:
    return session.get(Run, run_id)


def count_active_runs_for_ip_hash(session: Session, creator_ip_hash: str) -> int:
    """How many currently-ACTIVE runs were created by this hashed IP/
    fingerprint (Phase 8 §7: "max active runs per IP"). Only ACTIVE
    counts -- a completed or expired run no longer occupies a slot.
    """
    return len(
        session.exec(
            select(Run).where(
                Run.creator_ip_hash == creator_ip_hash, Run.status == RunStatus.ACTIVE
            )
        ).all()
    )


def _mark_expired_if_due(session: Session, run: Run, now: datetime) -> Run:
    if run.status not in (RunStatus.COMPLETED, RunStatus.EXPIRED) and run.expires_at <= now:
        run.status = RunStatus.EXPIRED
        session.add(run)
        session.commit()
        session.refresh(run)
    return run


def authenticate(session: Session, run_id: str, raw_token: str) -> tuple[Run, RunToken]:
    """Validate a raw token against the run it claims to belong to.

    Raises RunNotFoundError, InvalidTokenError, or RunNotActiveError.
    A token generated for a different run will never match the stored
    hash for this run_id, so cross-run access is rejected as an
    InvalidTokenError rather than silently succeeding.

    Returns both the Run and its RunToken so callers (e.g. the Agent
    API's scope check) can inspect the token's granted scope without a
    second lookup.
    """
    run = get_run(session, run_id)
    if run is None:
        raise RunNotFoundError(f"No run with id {run_id!r}")

    tokens = session.exec(select(RunToken).where(RunToken.run_id == run_id)).all()
    token = next((item for item in tokens if verify_token(raw_token, item.token_hash)), None)
    if token is None:
        raise InvalidTokenError("Token does not authenticate this run.")

    if token.revoked:
        # The only thing that revokes a token today is completion, so a
        # revoked token on a completed run gets the more specific
        # "already completed" signal; anything else is a plain invalid token.
        if run.status == RunStatus.COMPLETED:
            raise RunNotActiveError("Run already completed; token is disabled.")
        raise InvalidTokenError("Token has been revoked.")

    now = utc_now()
    run = _mark_expired_if_due(session, run, now)

    if run.status == RunStatus.EXPIRED or token.expires_at <= now:
        raise InvalidTokenError("Token has expired.")
    if run.status != RunStatus.ACTIVE:
        raise RunNotActiveError(f"Run is {run.status.value}; it cannot accept agent requests.")

    return run, token


def authenticate_run(session: Session, run_id: str, raw_token: str) -> Run:
    """Validate a raw token against the run it claims to belong to.

    Thin wrapper around `authenticate()` for callers that only need the
    Run (e.g. existing tests and any future non-scope-aware caller).
    """
    run, _token = authenticate(session, run_id, raw_token)
    return run


def create_view_token(session: Session, run_id: str, *, ttl_seconds: int | None = None) -> str:
    """Issue a run's read-only, public view token (Phase 6, hardened §1).

    Unlike the agent token, a view token is never scoped and is never
    revoked by completion -- it authorizes reading a run's
    activity/result pages independent of the agent token's lifecycle.
    It does expire (default `settings.view_token_ttl_seconds`, e.g. 7
    days) and can be revoked or rotated explicitly. Only its hash is
    persisted.
    """
    ttl = ttl_seconds if ttl_seconds is not None else settings.view_token_ttl_seconds
    raw_token = generate_raw_token(settings.token_byte_length)
    now = utc_now()
    session.add(
        RunViewToken(
            run_id=run_id,
            token_hash=hash_token(raw_token),
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
    )
    session.commit()
    return raw_token


def authenticate_view(session: Session, run_id: str, raw_token: str) -> Run:
    """Validate a raw view token against the run it claims to belong to.

    Raises RunNotFoundError or InvalidTokenError -- expired, revoked,
    and simply-wrong tokens all raise the same InvalidTokenError, so a
    caller (e.g. halu-web's page routes) can map all three to the same
    404 without opening an oracle for which case applied. Never checks
    scope or completion status -- a view token keeps working after the
    agent token is revoked, and it never grants write access (there is
    no action/complete endpoint that accepts it).
    """
    run = get_run(session, run_id)
    if run is None:
        raise RunNotFoundError(f"No run with id {run_id!r}")

    view_tokens = session.exec(select(RunViewToken).where(RunViewToken.run_id == run_id)).all()
    matching = next((t for t in view_tokens if verify_token(raw_token, t.token_hash)), None)
    if matching is None:
        raise InvalidTokenError("View token does not authorize this run.")

    now = utc_now()
    if matching.revoked_at is not None or matching.expires_at <= now:
        raise InvalidTokenError("View token has expired or been revoked.")

    return run


def revoke_view_token(session: Session, run_id: str) -> bool:
    """Revoke every currently-active view token for `run_id`.

    Internal-only (spec §1: no public revoke endpoint yet). Returns
    True if at least one token was revoked.
    """
    active_tokens = session.exec(
        select(RunViewToken).where(
            RunViewToken.run_id == run_id, col(RunViewToken.revoked_at).is_(None)
        )
    ).all()
    if not active_tokens:
        return False
    now = utc_now()
    for token in active_tokens:
        token.revoked_at = now
        session.add(token)
    session.commit()
    return True


def rotate_view_token(session: Session, run_id: str, *, ttl_seconds: int | None = None) -> str:
    """Revoke the run's current view token(s) and issue a fresh one.

    Internal-only (spec §1: no public rotate endpoint yet). The old raw
    token stops working immediately; only the newly returned raw token
    is valid afterwards.
    """
    revoke_view_token(session, run_id)
    return create_view_token(session, run_id, ttl_seconds=ttl_seconds)


def normalize_claims(raw_claims: list[ClaimInput | str]) -> list[tuple[str, Any]]:
    """Normalize a final report's claims to (claim_type, value) pairs.

    A structured claim keeps its own type. A legacy plain-string claim
    (spec §2's backward-compatibility requirement) becomes
    `("unstructured", <the string>)` -- an "unstructured" claim type is
    never recognized by any challenge's `verify_claim`, so it is scored
    as UNVERIFIED rather than silently ignored. No LLM parsing is ever
    involved.
    """
    normalized: list[tuple[str, Any]] = []
    for item in raw_claims:
        if isinstance(item, str):
            normalized.append(("unstructured", item))
        else:
            normalized.append((item.type, item.value))
    return normalized


def complete_run(
    session: Session,
    run: Run,
    challenge: Challenge,
    *,
    summary: str,
    claims: list[ClaimInput | str],
) -> tuple[Run, ScoreResult]:
    """Store the final report, verify its claims, score the run, complete
    it, and disable its token -- all in one transaction (spec §8).

    If scoring raises (e.g. a challenge hook misbehaves), nothing here
    is committed: no final report, no claims, no score, no completion,
    no token revocation, and no `run_completed` event.
    """
    now = utc_now()
    normalized_claims = normalize_claims(claims)

    session.add(
        FinalReport(
            run_id=run.id,
            summary=summary,
            claims=[{"type": t, "value": v} for t, v in normalized_claims],
            created_at=now,
        )
    )

    claim_rows = [
        RunClaim(run_id=run.id, sequence=i, claim_type=claim_type, claimed_value=value)
        for i, (claim_type, value) in enumerate(normalized_claims, start=1)
    ]
    for row in claim_rows:
        session.add(row)

    final_state = state_service.get_or_create_state(session, run, commit=False)
    score_result = scoring_service.compute_score(
        session, challenge, run_id=run.id, final_state=final_state, claims=claim_rows
    )
    scoring_service.persist_score(session, run.id, score_result, commit=False)

    run.status = RunStatus.COMPLETED
    run.completed_at = now
    session.add(run)

    token = session.exec(select(RunToken).where(RunToken.run_id == run.id)).first()
    if token is not None:
        token.revoked = True
        session.add(token)

    event_service.record_event(
        session,
        run_id=run.id,
        event_type=EventType.RUN_COMPLETED,
        source="agent_api",
        method="POST",
        endpoint=f"/api/v1/runs/{run.id}/complete",
        status_code=200,
        success=True,
        state_changed=False,
        request_data={
            "summary": summary,
            "claims": [{"type": t, "value": v} for t, v in normalized_claims],
        },
        response_data={
            "run_status": RunStatus.COMPLETED.value,
            "halu_score": score_result.halu_score,
            "technical_verdict": score_result.technical_verdict,
            "shareable_verdict": score_result.shareable_verdict,
        },
        commit=False,
    )

    session.commit()
    session.refresh(run)
    return run, score_result

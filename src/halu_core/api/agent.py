"""Generic Agent API: challenge, context, items, actions, completion,
events, and result (spec §10.2-§10.6, §12, §14, Phase 5).

Every endpoint here is challenge-agnostic: it resolves whichever
Challenge is registered under the run's `challenge_id` via
`halu_core.challenges.registry` and drives it through the Challenge
protocol. Hidden validation rules, item schemas, requirements/rubric
data, expected decisions, and scoring truth belong to each concrete
Challenge (e.g. halu-web's Bounty Manager), never here -- and neither
does event logging or scoring: every request here produces exactly one
immutable event (two for actions: `action_attempted` plus its outcome,
bundled into one transaction), and completion always scores atomically
with the rest of completion, and no challenge can opt in or out of any
of that.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from halu_core.api.dependencies import (
    get_current_time,
    get_rate_limit_config,
    get_session,
    require_actions_write,
    require_challenge_read,
    require_events_read,
    require_items_read,
    require_run_complete,
)
from halu_core.challenges.base import Challenge
from halu_core.challenges.models import ActionRequest
from halu_core.challenges.registry import ChallengeNotFoundError, registry
from halu_core.challenges.verification import ClaimInput
from halu_core.config import settings
from halu_core.logging_config import access_logger
from halu_core.models.enums import EventType, RunStatus
from halu_core.models.event import RunEvent
from halu_core.models.run import Run
from halu_core.security.json_limits import exceeds_max_depth
from halu_core.services import (
    event_service,
    flaky_service,
    idempotency_service,
    rate_limit_service,
    result_service,
    state_service,
)
from halu_core.services.rate_limit_service import RateLimitConfig
from halu_core.services.run_service import complete_run as complete_run_service

router = APIRouter(prefix="/api/v1/runs/{run_id}", tags=["agent"])

# Maps a challenge's validate_action error_code to the HTTP status a
# structured error response is returned with. Codes not listed default
# to 400 (a well-formed-but-invalid request).
_VALIDATION_ERROR_STATUS: dict[str, int] = {
    "unknown_action": 400,
    "missing_target_id": 400,
    "missing_reason": 400,
    "not_found": 404,
    "already_processed": 409,
    "duplicate_position": 409,
}


class ChallengeView(BaseModel):
    id: str
    name: str
    version: str
    time_limit_seconds: int
    public_instructions: str
    allowed_actions: list[str]
    category: str
    difficulty: str
    estimated_duration_minutes: int
    capabilities_tested: list[str]
    description: str
    recommended_agent_types: list[str]
    completion_endpoint: str


class ActionResponse(BaseModel):
    success: bool
    action_id: str
    state_changed: bool
    target_status: str | None = None
    message: str | None = None
    error_code: str | None = None


class CompleteRunRequest(BaseModel):
    summary: str
    # Structured claims (`{"type": ..., "value": ...}`) are the primary
    # format; a bare string is still accepted for backward
    # compatibility and normalized to an "unstructured" claim type
    # (spec §2) -- never parsed with an LLM either way.
    claims: list[ClaimInput | str] = Field(default_factory=list)


class CompleteRunResponse(BaseModel):
    success: bool
    run_status: RunStatus


class EventView(BaseModel):
    id: str
    run_id: str
    sequence: int
    event_type: str
    source: str
    method: str | None
    endpoint: str | None
    action: str | None
    target_id: str | None
    status_code: int | None
    success: bool
    state_changed: bool
    request_data: dict[str, Any] | None
    response_data: dict[str, Any] | None
    error_code: str | None
    idempotency_key: str | None
    state_before_hash: str | None
    state_after_hash: str | None
    created_at: datetime


class EventListResponse(BaseModel):
    events: list[EventView]
    total: int
    limit: int
    offset: int


class ClaimVerificationView(BaseModel):
    claim_type: str
    claimed_value: Any
    actual_value: Any
    status: str
    accuracy: float
    reason: str
    evidence_event_sequences: list[int]


class ResultResponse(BaseModel):
    run_id: str
    status: str
    scores: dict[str, float]
    technical_verdict: str
    shareable_verdict: str
    verdict_reasons: list[str]
    claim_verifications: list[ClaimVerificationView]
    objectives: list[dict[str, Any]]
    safety_incidents: list[dict[str, Any]]
    summary: dict[str, Any]
    benchmark_manifest: dict[str, Any] | None = None


def _resolve_challenge(run: Run, session: Session, *, method: str, endpoint: str) -> Challenge:
    """Resolve the exact Challenge a run is pinned to.

    A run created against a specific `challenge_version` always
    resolves that exact registered version, never "whatever the
    latest registered version happens to be" -- so registering a newer
    version of an id never changes the behavior of an existing run
    (spec: existing runs must not change when a new challenge version is
    registered). Only `challenge_version == "unversioned"` (legacy runs
    predating this pinning) falls back to the latest registered version.
    """
    pinned_version = None if run.challenge_version == "unversioned" else run.challenge_version
    try:
        challenge = registry.get(run.challenge_id, version=pinned_version)
    except ChallengeNotFoundError as exc:
        if pinned_version is not None and registry.is_registered(run.challenge_id):
            message = (
                f"Run was created for challenge version {pinned_version!r}, "
                f"but no such version of {run.challenge_id!r} is registered."
            )
            event_service.record_event(
                session,
                run_id=run.id,
                event_type=EventType.REQUEST_REJECTED,
                method=method,
                endpoint=endpoint,
                status_code=409,
                success=False,
                state_changed=False,
                error_code="challenge_version_mismatch",
                response_data={"message": message},
            )
            raise HTTPException(
                status_code=409,
                detail={"error_code": "challenge_version_mismatch", "message": message},
            ) from exc

        event_service.record_event(
            session,
            run_id=run.id,
            event_type=EventType.REQUEST_REJECTED,
            method=method,
            endpoint=endpoint,
            status_code=404,
            success=False,
            state_changed=False,
            error_code="challenge_not_registered",
            response_data={"message": str(exc)},
        )
        raise HTTPException(
            status_code=404,
            detail={"error_code": "challenge_not_registered", "message": str(exc)},
        ) from exc

    access_logger.info(
        "run_challenge_resolved",
        extra={"challenge_id": challenge.id, "challenge_version": challenge.version},
    )
    return challenge


def _new_action_id() -> str:
    return f"act_{uuid.uuid4().hex[:12]}"


def _enforce_rate_limit(
    session: Session,
    run_id: str,
    bucket: str,
    config: RateLimitConfig,
    now: datetime,
    *,
    method: str,
    endpoint: str,
) -> None:
    """Reject over-limit requests before any state, idempotency, or
    action logic runs, so a rate-limited request never mutates
    challenge state and never creates an idempotency record.
    """
    result = rate_limit_service.check_and_consume(
        session, run_id, bucket, config.limit_for(bucket), config.window_seconds, now
    )
    if not result.allowed:
        event_service.record_event(
            session,
            run_id=run_id,
            event_type=EventType.RATE_LIMIT_REJECTED,
            method=method,
            endpoint=endpoint,
            status_code=429,
            success=False,
            state_changed=False,
            error_code="rate_limit_exceeded",
            request_data={"bucket": bucket},
            response_data={"retry_after_seconds": result.retry_after_seconds},
        )
        raise HTTPException(
            status_code=429,
            detail={"error_code": "rate_limit_exceeded", "message": "Too many requests."},
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


@router.get("/challenge", response_model=ChallengeView)
def get_challenge(
    run: Run = Depends(require_challenge_read),
    session: Session = Depends(get_session),
    rate_config: RateLimitConfig = Depends(get_rate_limit_config),
    now: datetime = Depends(get_current_time),
) -> ChallengeView:
    endpoint = f"/api/v1/runs/{run.id}/challenge"
    _enforce_rate_limit(session, run.id, "read", rate_config, now, method="GET", endpoint=endpoint)
    challenge = _resolve_challenge(run, session, method="GET", endpoint=endpoint)
    state_service.get_or_create_state(session, run)
    descriptor = challenge.describe()
    response = ChallengeView(
        **descriptor.model_dump(),
        completion_endpoint=f"/api/v1/runs/{run.id}/complete",
    )
    event_service.record_event(
        session,
        run_id=run.id,
        event_type=EventType.CHALLENGE_READ,
        method="GET",
        endpoint=endpoint,
        status_code=200,
        success=True,
        state_changed=False,
        response_data=response.model_dump(),
    )
    return response


@router.get("/context")
def get_context(
    run: Run = Depends(require_challenge_read),
    session: Session = Depends(get_session),
    rate_config: RateLimitConfig = Depends(get_rate_limit_config),
    now: datetime = Depends(get_current_time),
) -> dict[str, Any]:
    endpoint = f"/api/v1/runs/{run.id}/context"
    _enforce_rate_limit(session, run.id, "read", rate_config, now, method="GET", endpoint=endpoint)
    challenge = _resolve_challenge(run, session, method="GET", endpoint=endpoint)
    state = state_service.get_or_create_state(session, run)
    context = challenge.get_context(state)
    event_service.record_event(
        session,
        run_id=run.id,
        event_type=EventType.CONTEXT_READ,
        method="GET",
        endpoint=endpoint,
        status_code=200,
        success=True,
        state_changed=False,
        response_data=context,
    )
    return context


@router.get("/items")
def list_items(
    run: Run = Depends(require_items_read),
    session: Session = Depends(get_session),
    rate_config: RateLimitConfig = Depends(get_rate_limit_config),
    now: datetime = Depends(get_current_time),
) -> list[dict[str, Any]]:
    endpoint = f"/api/v1/runs/{run.id}/items"
    _enforce_rate_limit(session, run.id, "read", rate_config, now, method="GET", endpoint=endpoint)
    challenge = _resolve_challenge(run, session, method="GET", endpoint=endpoint)
    state = state_service.get_or_create_state(session, run)
    items = challenge.list_items(state)
    event_service.record_event(
        session,
        run_id=run.id,
        event_type=EventType.ITEMS_LISTED,
        method="GET",
        endpoint=endpoint,
        status_code=200,
        success=True,
        state_changed=False,
        response_data={"count": len(items), "item_ids": [item.get("id") for item in items]},
    )
    return items


@router.get("/items/{item_id}")
def get_item(
    item_id: str,
    run: Run = Depends(require_items_read),
    session: Session = Depends(get_session),
    rate_config: RateLimitConfig = Depends(get_rate_limit_config),
    now: datetime = Depends(get_current_time),
) -> dict[str, Any]:
    endpoint = f"/api/v1/runs/{run.id}/items/{item_id}"
    _enforce_rate_limit(session, run.id, "read", rate_config, now, method="GET", endpoint=endpoint)
    challenge = _resolve_challenge(run, session, method="GET", endpoint=endpoint)
    state = state_service.get_or_create_state(session, run)

    if challenge.is_flaky_item(state, item_id) and not flaky_service.already_triggered(
        session, run.id, item_id
    ):
        flaky_service.mark_triggered(session, run.id, item_id)
        event_service.record_event(
            session,
            run_id=run.id,
            event_type=EventType.TRANSIENT_ERROR_RETURNED,
            method="GET",
            endpoint=endpoint,
            target_id=item_id,
            status_code=503,
            success=False,
            state_changed=False,
            error_code="temporary_error",
            response_data={"message": "Temporary upstream error. Please retry."},
        )
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "temporary_error",
                "message": "Temporary upstream error. Please retry.",
            },
        )

    item = challenge.get_item(state, item_id)
    if item is None:
        event_service.record_event(
            session,
            run_id=run.id,
            event_type=EventType.REQUEST_REJECTED,
            method="GET",
            endpoint=endpoint,
            target_id=item_id,
            status_code=404,
            success=False,
            state_changed=False,
            error_code="not_found",
            response_data={"message": f"No item {item_id!r}."},
        )
        raise HTTPException(
            status_code=404,
            detail={"error_code": "not_found", "message": f"No item {item_id!r}."},
        )

    event_service.record_event(
        session,
        run_id=run.id,
        event_type=EventType.ITEM_READ,
        method="GET",
        endpoint=endpoint,
        target_id=item_id,
        status_code=200,
        success=True,
        state_changed=False,
        response_data=item,
    )
    return item


@router.post("/actions")
def perform_action(
    payload: ActionRequest,
    run: Run = Depends(require_actions_write),
    session: Session = Depends(get_session),
    rate_config: RateLimitConfig = Depends(get_rate_limit_config),
    now: datetime = Depends(get_current_time),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    endpoint = f"/api/v1/runs/{run.id}/actions"
    _enforce_rate_limit(
        session, run.id, "write", rate_config, now, method="POST", endpoint=endpoint
    )
    challenge = _resolve_challenge(run, session, method="POST", endpoint=endpoint)

    # Abuse protection (Phase 8 §7): a hard ceiling on actions attempted
    # per run, and a rejection of pathologically deep action payloads
    # (a JSON-bomb-style DoS vector), both checked before any
    # idempotency/validation work.
    attempted_so_far = event_service.count_events(
        session, run.id, event_type=EventType.ACTION_ATTEMPTED.value
    )
    if attempted_so_far >= settings.max_actions_per_run:
        event_service.record_event(
            session,
            run_id=run.id,
            event_type=EventType.REQUEST_REJECTED,
            method="POST",
            endpoint=endpoint,
            status_code=429,
            success=False,
            state_changed=False,
            error_code="max_actions_exceeded",
            response_data={"message": "This run has reached its maximum number of actions."},
        )
        raise HTTPException(
            status_code=429,
            detail={
                "error_code": "max_actions_exceeded",
                "message": "This run has reached its maximum number of actions.",
            },
        )
    if exceeds_max_depth(payload.payload, settings.max_json_depth):
        event_service.record_event(
            session,
            run_id=run.id,
            event_type=EventType.REQUEST_REJECTED,
            method="POST",
            endpoint=endpoint,
            status_code=400,
            success=False,
            state_changed=False,
            error_code="payload_too_deep",
            response_data={"message": "Action payload is nested too deeply."},
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "payload_too_deep",
                "message": "Action payload is nested too deeply.",
            },
        )

    request_hash = idempotency_service.hash_action(payload)
    sanitized_request = payload.model_dump()

    if idempotency_key:
        existing = idempotency_service.find(session, run.id, idempotency_key)
        if existing is not None:
            if existing.request_hash != request_hash:
                event_service.record_event(
                    session,
                    run_id=run.id,
                    event_type=EventType.ACTION_IDEMPOTENCY_CONFLICT,
                    method="POST",
                    endpoint=endpoint,
                    action=payload.action,
                    target_id=payload.target_id,
                    status_code=409,
                    success=False,
                    state_changed=False,
                    error_code="idempotency_key_conflict",
                    request_data=sanitized_request,
                    idempotency_key=idempotency_key,
                )
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error_code": "idempotency_key_conflict",
                        "message": (
                            "This Idempotency-Key was already used with a different request."
                        ),
                    },
                )
            event_service.record_event(
                session,
                run_id=run.id,
                event_type=EventType.ACTION_IDEMPOTENCY_REPLAY,
                method="POST",
                endpoint=endpoint,
                action=payload.action,
                target_id=payload.target_id,
                status_code=existing.status_code,
                success=existing.status_code < 400,
                state_changed=False,
                request_data=sanitized_request,
                response_data=existing.response_body,
                idempotency_key=idempotency_key,
            )
            return JSONResponse(
                status_code=existing.status_code, content=existing.response_body
            )

    state = state_service.get_or_create_state(session, run)
    state_before_hash = event_service.hash_state(state)
    result = challenge.validate_action(state, payload)
    action_id = _new_action_id()

    # Recorded regardless of outcome, and bundled into the same
    # transaction as that outcome (see the commit calls below) so a
    # mid-request failure leaves neither event behind.
    event_service.record_event(
        session,
        run_id=run.id,
        event_type=EventType.ACTION_ATTEMPTED,
        method="POST",
        endpoint=endpoint,
        action=payload.action,
        target_id=payload.target_id,
        success=True,
        state_changed=False,
        request_data=sanitized_request,
        idempotency_key=idempotency_key,
        state_before_hash=state_before_hash,
        commit=False,
    )

    if not result.success:
        status_code = _VALIDATION_ERROR_STATUS.get(result.error_code or "", 400)
        body = ActionResponse(
            success=False,
            action_id=action_id,
            state_changed=False,
            target_status=result.target_status,
            message=result.message,
            error_code=result.error_code,
        ).model_dump()
        event_service.record_event(
            session,
            run_id=run.id,
            event_type=EventType.ACTION_REJECTED,
            method="POST",
            endpoint=endpoint,
            action=payload.action,
            target_id=payload.target_id,
            status_code=status_code,
            success=False,
            state_changed=False,
            error_code=result.error_code,
            request_data=sanitized_request,
            response_data=body,
            idempotency_key=idempotency_key,
            state_before_hash=state_before_hash,
            state_after_hash=state_before_hash,
            commit=False,
        )
        if idempotency_key:
            idempotency_service.store(
                session, run.id, idempotency_key, request_hash, status_code, body, commit=False
            )
        session.commit()
        return JSONResponse(status_code=status_code, content=body)

    new_state = challenge.apply_action(state, payload)
    state_after_hash = event_service.hash_state(new_state)
    state_service.save_state(session, run.id, new_state, commit=False)

    body = ActionResponse(
        success=True,
        action_id=action_id,
        state_changed=result.state_changed,
        target_status=result.target_status,
        message=result.message,
        error_code=None,
    ).model_dump()

    event_service.record_event(
        session,
        run_id=run.id,
        event_type=EventType.ACTION_SUCCEEDED,
        method="POST",
        endpoint=endpoint,
        action=payload.action,
        target_id=payload.target_id,
        status_code=200,
        success=True,
        state_changed=result.state_changed,
        request_data=sanitized_request,
        response_data=body,
        idempotency_key=idempotency_key,
        state_before_hash=state_before_hash,
        state_after_hash=state_after_hash,
        commit=False,
    )
    if idempotency_key:
        idempotency_service.store(
            session, run.id, idempotency_key, request_hash, 200, body, commit=False
        )
    session.commit()
    return JSONResponse(status_code=200, content=body)


@router.post("/complete", response_model=CompleteRunResponse)
def complete_run(
    payload: CompleteRunRequest,
    run: Run = Depends(require_run_complete),
    session: Session = Depends(get_session),
    rate_config: RateLimitConfig = Depends(get_rate_limit_config),
    now: datetime = Depends(get_current_time),
) -> CompleteRunResponse:
    endpoint = f"/api/v1/runs/{run.id}/complete"
    _enforce_rate_limit(
        session, run.id, "write", rate_config, now, method="POST", endpoint=endpoint
    )
    challenge = _resolve_challenge(run, session, method="POST", endpoint=endpoint)

    # Abuse protection (Phase 8 §7): cap the final report's size, claim
    # count, and nesting depth before any of it is normalized/stored.
    if len(payload.summary) > settings.max_final_report_length:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "final_report_too_large",
                "message": (
                    f"summary must be at most {settings.max_final_report_length} characters."
                ),
            },
        )
    if len(payload.claims) > settings.max_claims_per_report:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "too_many_claims",
                "message": f"At most {settings.max_claims_per_report} claims are allowed.",
            },
        )
    for claim in payload.claims:
        claimed_value = claim.value if isinstance(claim, ClaimInput) else claim
        if exceeds_max_depth(claimed_value, settings.max_json_depth):
            raise HTTPException(
                status_code=400,
                detail={
                    "error_code": "payload_too_deep",
                    "message": "A claim's value is nested too deeply.",
                },
            )

    # complete_run_service records the run_completed event itself,
    # bundled with the final report/claims/verification/score/
    # status/token-revocation writes into one atomic transaction.
    completed, _score_result = complete_run_service(
        session, run, challenge, summary=payload.summary, claims=payload.claims
    )
    return CompleteRunResponse(success=True, run_status=completed.status)


@router.get("/events", response_model=EventListResponse)
def list_run_events(
    run: Run = Depends(require_events_read),
    session: Session = Depends(get_session),
    rate_config: RateLimitConfig = Depends(get_rate_limit_config),
    now: datetime = Depends(get_current_time),
    event_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> EventListResponse:
    endpoint = f"/api/v1/runs/{run.id}/events"
    _enforce_rate_limit(session, run.id, "read", rate_config, now, method="GET", endpoint=endpoint)
    bounded_limit = max(1, min(limit, 200))
    bounded_offset = max(0, offset)
    events = event_service.list_events(
        session, run.id, event_type=event_type, limit=bounded_limit, offset=bounded_offset
    )
    total = event_service.count_events(session, run.id, event_type=event_type)
    return EventListResponse(
        events=[_to_event_view(event) for event in events],
        total=total,
        limit=bounded_limit,
        offset=bounded_offset,
    )


@router.get("/result", response_model=ResultResponse)
def get_result(
    run: Run = Depends(require_events_read),
    session: Session = Depends(get_session),
    rate_config: RateLimitConfig = Depends(get_rate_limit_config),
    now: datetime = Depends(get_current_time),
) -> ResultResponse:
    """The scored result of a completed run (spec §9).

    Reuses `events:read`: there is no dedicated scope for this in the
    spec, and by the time a run is completed its token is already
    revoked (spec §9's "revoked token cannot read result" requirement
    is therefore already enforced by `require_events_read` itself,
    with no special-casing needed here).
    """
    endpoint = f"/api/v1/runs/{run.id}/result"
    _enforce_rate_limit(session, run.id, "read", rate_config, now, method="GET", endpoint=endpoint)

    if run.status != RunStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "run_not_completed",
                "message": "This run has not been completed yet.",
            },
        )

    result = result_service.get_result(session, run.id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "result_not_found", "message": "No score exists for this run."},
        )

    return ResultResponse(
        run_id=result["run_id"],
        status=run.status.value,
        scores=result["scores"],
        technical_verdict=result["technical_verdict"],
        shareable_verdict=result["shareable_verdict"],
        verdict_reasons=result["verdict_reasons"],
        claim_verifications=[
            ClaimVerificationView(**v) for v in result["claim_verifications"]
        ],
        objectives=result["objectives"],
        safety_incidents=result["safety_incidents"],
        summary=result["summary"],
        benchmark_manifest=result["benchmark_manifest"],
    )


def _to_event_view(event: RunEvent) -> EventView:
    return EventView(
        id=event.id,
        run_id=event.run_id,
        sequence=event.sequence,
        event_type=event.event_type,
        source=event.source,
        method=event.method,
        endpoint=event.endpoint,
        action=event.action,
        target_id=event.target_id,
        status_code=event.status_code,
        success=event.success,
        state_changed=event.state_changed,
        request_data=event.request_data,
        response_data=event.response_data,
        error_code=event.error_code,
        idempotency_key=event.idempotency_key,
        state_before_hash=event.state_before_hash,
        state_after_hash=event.state_after_hash,
        created_at=event.created_at,
    )

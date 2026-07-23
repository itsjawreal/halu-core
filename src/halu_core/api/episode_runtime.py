"""Participant-facing full-agent profile, checkpoint, and resume protocol."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from halu_core.api.dependencies import get_session, require_challenge_read, require_events_read
from halu_core.challenges.registry import registry
from halu_core.models.enums import EpisodeProfile
from halu_core.models.run import Run
from halu_core.services import event_service
from halu_core.services.episode_runtime_service import (
    EpisodeNotFoundError,
    InvalidCheckpointCursorError,
    InvalidLifecycleTransitionError,
    InvalidResumeTokenError,
    ProfileOperationNotAllowedError,
    StaleStatusRevisionError,
    create_checkpoint,
    resume_episode,
)

router = APIRouter(prefix="/api/v1/runs/{run_id}", tags=["episode-runtime"])

_BASE_PROFILE_CONTEXT: dict[EpisodeProfile, dict[str, Any]] = {
    EpisodeProfile.COLD: {
        "memory_mode": "clean",
        "faults": [],
        "beta": False,
    },
    EpisodeProfile.WARM: {
        "memory_mode": "benchmark_fixture",
        "faults": ["stale_memory"],
        "beta": False,
    },
    EpisodeProfile.INTERRUPTED: {
        "memory_mode": "runtime_managed",
        "faults": ["forced_interruption", "credential_rotation"],
        "beta": False,
        "recovery_contract": (
            "Checkpoint, accept interruption, resume with the one-time token, "
            "inspect authoritative state/events, then retry only if needed."
        ),
    },
    EpisodeProfile.LONG_HORIZON: {
        "memory_mode": "runtime_managed",
        "faults": ["virtual_time_events"],
        "beta": True,
    },
    EpisodeProfile.ADVERSARIAL: {
        "memory_mode": "clean",
        "faults": ["untrusted_instructions", "conflicting_evidence", "tool_degradation"],
        "beta": False,
    },
    EpisodeProfile.MULTI_AGENT: {
        "memory_mode": "runtime_managed",
        "faults": ["misleading_child_output"],
        "beta": True,
        "delegation_optional": True,
    },
}


class EpisodeProfileView(BaseModel):
    run_id: str
    profile: EpisodeProfile
    status_revision: int
    credential_generation: int
    scenario_seed_commitment: str | None
    profile_context: dict[str, Any]


class CheckpointCreate(BaseModel):
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    last_acknowledged_sequence: int = Field(ge=0)
    expected_revision: int = Field(ge=0)


class CheckpointCreated(BaseModel):
    checkpoint_id: str
    run_id: str
    status: str
    status_revision: int
    digest: str
    last_acknowledged_sequence: int
    created_at: datetime


class ResumeEventView(BaseModel):
    sequence: int
    event_type: str
    action: str | None
    target_id: str | None
    success: bool
    state_changed: bool
    error_code: str | None
    created_at: datetime


class EpisodeResumed(BaseModel):
    run_id: str
    status: str
    status_revision: int
    credential_generation: int
    agent_token: str
    checkpoint_digest: str | None
    last_acknowledged_sequence: int
    reconciliation_required: bool = True
    events_after_checkpoint: list[ResumeEventView]


def _resume_bearer(authorization: str | None) -> str:
    if authorization is None:
        raise HTTPException(status_code=401, detail={"error_code": "missing_resume_token"})
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail={"error_code": "missing_resume_token"})
    return token.strip()


@router.get("/profile", response_model=EpisodeProfileView)
def get_episode_profile(
    run: Run = Depends(require_challenge_read),
    session: Session = Depends(get_session),
) -> EpisodeProfileView:
    challenge = registry.get(
        run.challenge_id,
        version=None if run.challenge_version == "unversioned" else run.challenge_version,
    )
    profile_context = {
        **_BASE_PROFILE_CONTEXT[run.episode_profile],
        **challenge.get_episode_profile_context(run.episode_profile.value),
    }
    response = EpisodeProfileView(
        run_id=run.id,
        profile=run.episode_profile,
        status_revision=run.status_revision,
        credential_generation=run.credential_generation,
        scenario_seed_commitment=run.scenario_seed_commitment,
        profile_context=profile_context,
    )
    event_service.record_event(
        session,
        run_id=run.id,
        event_type="profile_read",
        method="GET",
        endpoint=f"/api/v1/runs/{run.id}/profile",
        status_code=200,
        response_data=response.model_dump(),
    )
    return response


@router.post("/checkpoint", response_model=CheckpointCreated, status_code=201)
def checkpoint_episode(
    payload: CheckpointCreate,
    run: Run = Depends(require_events_read),
    session: Session = Depends(get_session),
) -> CheckpointCreated:
    try:
        checkpoint = create_checkpoint(session, run, **payload.model_dump())
    except ProfileOperationNotAllowedError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "profile_operation_not_allowed", "message": str(exc)},
        ) from exc
    except InvalidCheckpointCursorError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "invalid_checkpoint_cursor", "message": str(exc)},
        ) from exc
    except (InvalidLifecycleTransitionError, StaleStatusRevisionError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "invalid_state", "message": str(exc)},
        ) from exc
    return CheckpointCreated(
        checkpoint_id=checkpoint.id,
        run_id=run.id,
        status=run.status.value,
        status_revision=run.status_revision,
        digest=checkpoint.digest,
        last_acknowledged_sequence=checkpoint.last_acknowledged_sequence,
        created_at=checkpoint.created_at,
    )


@router.post("/resume", response_model=EpisodeResumed)
def resume_interrupted_episode(
    run_id: str,
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> EpisodeResumed:
    raw_resume_token = _resume_bearer(authorization)
    try:
        result = resume_episode(session, run_id, raw_resume_token)
    except InvalidResumeTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail={"error_code": "invalid_resume_token", "message": str(exc)},
        ) from exc
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "episode_not_found", "message": str(exc)},
        ) from exc
    checkpoint = result.checkpoint
    return EpisodeResumed(
        run_id=result.run.id,
        status=result.run.status.value,
        status_revision=result.run.status_revision,
        credential_generation=result.run.credential_generation,
        agent_token=result.agent_token,
        checkpoint_digest=checkpoint.digest if checkpoint else None,
        last_acknowledged_sequence=(
            checkpoint.last_acknowledged_sequence if checkpoint else 0
        ),
        events_after_checkpoint=[
            ResumeEventView.model_validate(event, from_attributes=True)
            for event in result.events
        ],
    )

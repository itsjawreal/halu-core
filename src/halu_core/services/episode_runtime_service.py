"""Checkpoint, deterministic interruption, and one-time resume semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlmodel import Session, col, func, select

from halu_core.config import settings
from halu_core.models.campaign import Campaign
from halu_core.models.enums import EpisodeProfile, EventType, RunStatus
from halu_core.models.episode_runtime import EpisodeCheckpoint, EpisodeResumeToken
from halu_core.models.event import RunEvent
from halu_core.models.run import Run
from halu_core.models.token import RunToken
from halu_core.services import event_service
from halu_core.services.lifecycle_service import (
    InvalidLifecycleTransitionError,
    StaleStatusRevisionError,
    transition_run,
)
from halu_core.services.run_service import DEFAULT_SCOPE
from halu_core.services.token_service import generate_raw_token, hash_token, verify_token
from halu_core.timeutils import utc_now


class EpisodeRuntimeError(Exception):
    """Base error for invalid runtime-protocol operations."""


class EpisodeNotFoundError(EpisodeRuntimeError):
    """The episode does not exist or does not belong to the campaign."""


class ProfileOperationNotAllowedError(EpisodeRuntimeError):
    """The requested protocol operation is unavailable for this profile."""


class InvalidCheckpointCursorError(EpisodeRuntimeError):
    """Checkpoint cursor does not reference an existing event boundary."""


class InvalidResumeTokenError(EpisodeRuntimeError):
    """Resume credential is missing, expired, used, or bound elsewhere."""


@dataclass(frozen=True)
class ResumeResult:
    run: Run
    agent_token: str
    checkpoint: EpisodeCheckpoint | None
    events: list[RunEvent]


def latest_event_sequence(session: Session, run_id: str) -> int:
    current = session.exec(
        select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run_id)
    ).one()
    return int(current or 0)


def latest_checkpoint(session: Session, run_id: str) -> EpisodeCheckpoint | None:
    return session.exec(
        select(EpisodeCheckpoint)
        .where(EpisodeCheckpoint.run_id == run_id)
        .order_by(col(EpisodeCheckpoint.created_at).desc())
    ).first()


def create_checkpoint(
    session: Session,
    run: Run,
    *,
    digest: str,
    last_acknowledged_sequence: int,
    expected_revision: int,
) -> EpisodeCheckpoint:
    if run.episode_profile != EpisodeProfile.INTERRUPTED:
        raise ProfileOperationNotAllowedError(
            "Checkpoint/interruption is only enabled for interrupted episodes."
        )
    latest = latest_event_sequence(session, run.id)
    if last_acknowledged_sequence < 0 or last_acknowledged_sequence > latest:
        raise InvalidCheckpointCursorError(
            f"Checkpoint cursor {last_acknowledged_sequence} is outside 0..{latest}."
        )

    transition_run(
        session,
        run,
        target=RunStatus.CHECKPOINTED,
        expected_revision=expected_revision,
        commit=False,
    )
    checkpoint = EpisodeCheckpoint(
        run_id=run.id,
        credential_generation=run.credential_generation,
        digest=digest,
        last_acknowledged_sequence=last_acknowledged_sequence,
    )
    session.add(checkpoint)
    event_service.record_event(
        session,
        run_id=run.id,
        event_type=EventType.CHECKPOINT_CREATED,
        source="runtime_protocol",
        method="POST",
        endpoint=f"/api/v1/runs/{run.id}/checkpoint",
        status_code=201,
        request_data={
            "digest": digest,
            "last_acknowledged_sequence": last_acknowledged_sequence,
        },
        response_data={"checkpoint_id": checkpoint.id},
        commit=False,
    )
    session.commit()
    session.refresh(checkpoint)
    return checkpoint


def interrupt_episode(
    session: Session,
    campaign_id: str,
    run_id: str,
    *,
    expected_revision: int,
) -> tuple[Run, str]:
    campaign = session.get(Campaign, campaign_id)
    run = session.get(Run, run_id)
    if campaign is None or run is None or run.campaign_id != campaign.id:
        raise EpisodeNotFoundError(run_id)
    if run.episode_profile != EpisodeProfile.INTERRUPTED:
        raise ProfileOperationNotAllowedError(
            "Only interrupted-profile episodes can receive a forced interruption."
        )
    transition_run(
        session,
        run,
        target=RunStatus.INTERRUPTED,
        expected_revision=expected_revision,
        commit=False,
    )
    active_tokens = session.exec(select(RunToken).where(RunToken.run_id == run.id)).all()
    for token in active_tokens:
        token.revoked = True
        session.add(token)

    raw_resume_token = generate_raw_token(settings.token_byte_length)
    now = utc_now()
    session.add(
        EpisodeResumeToken(
            run_id=run.id,
            token_hash=hash_token(raw_resume_token),
            credential_generation=run.credential_generation,
            created_at=now,
            expires_at=min(run.expires_at, now + timedelta(minutes=15)),
        )
    )
    event_service.record_event(
        session,
        run_id=run.id,
        event_type=EventType.RUNTIME_INTERRUPTED,
        source="fault_injector",
        method="POST",
        endpoint=f"/api/v1/campaigns/{campaign.id}/episodes/{run.id}/interrupt",
        status_code=200,
        response_data={"credential_generation": run.credential_generation},
        commit=False,
    )
    session.commit()
    session.refresh(run)
    return run, raw_resume_token


def resume_episode(session: Session, run_id: str, raw_resume_token: str) -> ResumeResult:
    run = session.get(Run, run_id)
    if run is None:
        raise EpisodeNotFoundError(run_id)
    candidates = session.exec(
        select(EpisodeResumeToken)
        .where(EpisodeResumeToken.run_id == run_id)
        .with_for_update()
    ).all()
    resume_token = next(
        (item for item in candidates if verify_token(raw_resume_token, item.token_hash)),
        None,
    )
    now = utc_now()
    if (
        resume_token is None
        or resume_token.used_at is not None
        or resume_token.expires_at <= now
        or resume_token.credential_generation != run.credential_generation
        or run.status != RunStatus.INTERRUPTED
    ):
        raise InvalidResumeTokenError("Resume token is invalid, expired, or already used.")

    transition_run(
        session,
        run,
        target=RunStatus.RESUMING,
        expected_revision=run.status_revision,
        commit=False,
    )
    run.credential_generation += 1
    raw_agent_token = generate_raw_token(settings.token_byte_length)
    session.add(
        RunToken(
            run_id=run.id,
            token_hash=hash_token(raw_agent_token),
            scope=[scope.value for scope in DEFAULT_SCOPE],
            created_at=now,
            expires_at=run.expires_at,
        )
    )
    resume_token.used_at = now
    session.add(resume_token)
    transition_run(
        session,
        run,
        target=RunStatus.ACTIVE,
        expected_revision=run.status_revision,
        commit=False,
    )
    checkpoint = latest_checkpoint(session, run.id)
    after = checkpoint.last_acknowledged_sequence if checkpoint else 0
    event_service.record_event(
        session,
        run_id=run.id,
        event_type=EventType.RUNTIME_RESUMED,
        source="runtime_protocol",
        method="POST",
        endpoint=f"/api/v1/runs/{run.id}/resume",
        status_code=200,
        response_data={
            "credential_generation": run.credential_generation,
            "checkpoint_id": checkpoint.id if checkpoint else None,
            "reconciliation_required": True,
        },
        commit=False,
    )
    session.commit()
    session.refresh(run)
    events = event_service.list_events(session, run.id, after_sequence=after, limit=500)
    return ResumeResult(
        run=run,
        agent_token=raw_agent_token,
        checkpoint=checkpoint,
        events=events,
    )


__all__ = [
    "EpisodeNotFoundError",
    "EpisodeRuntimeError",
    "InvalidCheckpointCursorError",
    "InvalidLifecycleTransitionError",
    "InvalidResumeTokenError",
    "ProfileOperationNotAllowedError",
    "ResumeResult",
    "StaleStatusRevisionError",
    "create_checkpoint",
    "interrupt_episode",
    "latest_checkpoint",
    "resume_episode",
]

"""Control-plane API for multi-profile full-agent campaigns."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session

from halu_core.api.dependencies import get_session
from halu_core.models.campaign import Campaign
from halu_core.models.enums import AgentType, CampaignStatus, EpisodeProfile
from halu_core.services.campaign_service import (
    CampaignEpisodeCredential,
    ChallengeVersionNotFoundError,
    RuntimePackageNotFoundError,
    create_campaign,
    get_campaign,
)
from halu_core.services.episode_runtime_service import (
    EpisodeNotFoundError,
    InvalidLifecycleTransitionError,
    ProfileOperationNotAllowedError,
    StaleStatusRevisionError,
    interrupt_episode,
)

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    runtime_package_id: str
    challenge_id: str = Field(min_length=1, max_length=200)
    challenge_version: str | None = Field(default=None, min_length=1, max_length=100)
    agent_type: AgentType = AgentType.GENERIC
    profiles: list[EpisodeProfile] = Field(
        default_factory=lambda: [EpisodeProfile.COLD], min_length=1, max_length=6
    )
    seeds_per_profile: int = Field(default=1, ge=1, le=5)

    @field_validator("profiles")
    @classmethod
    def profiles_must_be_unique(cls, profiles: list[EpisodeProfile]) -> list[EpisodeProfile]:
        if len(set(profiles)) != len(profiles):
            raise ValueError("profiles must not contain duplicates")
        return profiles


class CampaignEpisodeCredentialView(BaseModel):
    run_id: str
    profile: EpisodeProfile
    token: str
    view_token: str


class CampaignView(BaseModel):
    id: str
    runtime_package_id: str
    challenge_id: str
    challenge_version: str
    agent_type: AgentType
    status: CampaignStatus
    requested_profiles: list[str]
    seeds_per_profile: int
    run_ids: list[str]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class CampaignCreated(CampaignView):
    episode_credentials: list[CampaignEpisodeCredentialView]


class EpisodeInterruptRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class EpisodeInterrupted(BaseModel):
    run_id: str
    status: str
    status_revision: int
    resume_token: str


def _view(campaign: Campaign) -> CampaignView:
    return CampaignView.model_validate(campaign, from_attributes=True)


def _credential_view(item: CampaignEpisodeCredential) -> CampaignEpisodeCredentialView:
    return CampaignEpisodeCredentialView(
        run_id=item.run_id,
        profile=item.profile,
        token=item.token,
        view_token=item.view_token,
    )


@router.post("", response_model=CampaignCreated, status_code=201)
def register_campaign(
    payload: CampaignCreate, session: Session = Depends(get_session)
) -> CampaignCreated:
    try:
        campaign, credentials = create_campaign(session, **payload.model_dump())
    except RuntimePackageNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "runtime_package_not_found", "message": str(exc)},
        ) from exc
    except ChallengeVersionNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "challenge_version_not_found", "message": str(exc)},
        ) from exc
    base = _view(campaign)
    return CampaignCreated(
        **base.model_dump(),
        episode_credentials=[_credential_view(item) for item in credentials],
    )


@router.get("/{campaign_id}", response_model=CampaignView)
def read_campaign(campaign_id: str, session: Session = Depends(get_session)) -> CampaignView:
    campaign = get_campaign(session, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return _view(campaign)


@router.post(
    "/{campaign_id}/episodes/{run_id}/interrupt",
    response_model=EpisodeInterrupted,
)
def interrupt_campaign_episode(
    campaign_id: str,
    run_id: str,
    payload: EpisodeInterruptRequest,
    session: Session = Depends(get_session),
) -> EpisodeInterrupted:
    try:
        run, resume_token = interrupt_episode(
            session,
            campaign_id,
            run_id,
            expected_revision=payload.expected_revision,
        )
    except EpisodeNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "episode_not_found", "message": str(exc)},
        ) from exc
    except ProfileOperationNotAllowedError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "profile_operation_not_allowed", "message": str(exc)},
        ) from exc
    except (InvalidLifecycleTransitionError, StaleStatusRevisionError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "invalid_state", "message": str(exc)},
        ) from exc
    return EpisodeInterrupted(
        run_id=run.id,
        status=run.status.value,
        status_revision=run.status_revision,
        resume_token=resume_token,
    )

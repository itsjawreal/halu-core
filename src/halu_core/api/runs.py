"""Run creation and lookup endpoints (spec §10.1, §10.7)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from halu_core.api.dependencies import get_session
from halu_core.config import settings
from halu_core.models.enums import AgentType, RunStatus
from halu_core.services.prompt_service import generate_prompt
from halu_core.services.run_service import create_run, create_view_token, get_run

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    challenge_id: str
    agent_type: AgentType


class CreateRunResponse(BaseModel):
    run_id: str
    prompt: str
    token: str
    view_token: str
    expires_at: datetime


class RunSummary(BaseModel):
    run_id: str
    challenge_id: str
    agent_type: AgentType
    status: RunStatus
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None


@router.post("", response_model=CreateRunResponse)
def create_run_endpoint(
    payload: CreateRunRequest, session: Session = Depends(get_session)
) -> CreateRunResponse:
    run, raw_token = create_run(
        session, challenge_id=payload.challenge_id, agent_type=payload.agent_type
    )
    raw_view_token = create_view_token(session, run.id)
    prompt = generate_prompt(run, raw_token, settings.base_url)
    return CreateRunResponse(
        run_id=run.id,
        prompt=prompt,
        token=raw_token,
        view_token=raw_view_token,
        expires_at=run.expires_at,
    )


@router.get("/{run_id}", response_model=RunSummary)
def get_run_endpoint(run_id: str, session: Session = Depends(get_session)) -> RunSummary:
    run = get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return RunSummary(
        run_id=run.id,
        challenge_id=run.challenge_id,
        agent_type=run.agent_type,
        status=run.status,
        created_at=run.created_at,
        expires_at=run.expires_at,
        completed_at=run.completed_at,
    )

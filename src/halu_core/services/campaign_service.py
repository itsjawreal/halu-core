"""Creation and lookup of multi-profile full-agent campaigns."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlmodel import Session

from halu_core.canonical_json import canonical_hash
from halu_core.challenges.registry import ChallengeNotFoundError, registry
from halu_core.models.campaign import Campaign
from halu_core.models.enums import AgentType, CampaignStatus, EpisodeProfile
from halu_core.models.runtime_package import RuntimePackage
from halu_core.services.run_service import create_run, create_view_token
from halu_core.timeutils import utc_now


class RuntimePackageNotFoundError(Exception):
    """Campaign references a runtime package that does not exist."""


class ChallengeVersionNotFoundError(Exception):
    """Campaign references a challenge/version that does not exist."""


@dataclass(frozen=True)
class CampaignEpisodeCredential:
    run_id: str
    profile: EpisodeProfile
    token: str
    view_token: str


def create_campaign(
    session: Session,
    *,
    runtime_package_id: str,
    challenge_id: str,
    challenge_version: str | None,
    agent_type: AgentType,
    profiles: list[EpisodeProfile],
    seeds_per_profile: int,
) -> tuple[Campaign, list[CampaignEpisodeCredential]]:
    if session.get(RuntimePackage, runtime_package_id) is None:
        raise RuntimePackageNotFoundError(runtime_package_id)

    try:
        challenge = registry.get(challenge_id, version=challenge_version)
    except ChallengeNotFoundError as exc:
        requested = challenge_version or "latest"
        raise ChallengeVersionNotFoundError(
            f"No challenge {challenge_id!r} version {requested!r} is registered."
        ) from exc
    resolved_challenge_version = challenge.version

    now = utc_now()
    campaign = Campaign(
        runtime_package_id=runtime_package_id,
        challenge_id=challenge_id,
        challenge_version=resolved_challenge_version,
        agent_type=agent_type,
        status=CampaignStatus.RUNNING,
        requested_profiles=[profile.value for profile in profiles],
        seeds_per_profile=seeds_per_profile,
        created_at=now,
        started_at=now,
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    credentials: list[CampaignEpisodeCredential] = []
    run_ids: list[str] = []
    for profile in profiles:
        for _ in range(seeds_per_profile):
            seed = secrets.token_hex(32)
            commitment = canonical_hash(
                {"campaign_id": campaign.id, "profile": profile.value, "seed": seed}
            )
            run, token = create_run(
                session,
                challenge_id=challenge_id,
                challenge_version=resolved_challenge_version,
                agent_type=agent_type,
                runtime_package_id=runtime_package_id,
                campaign_id=campaign.id,
                episode_profile=profile,
                scenario_seed_commitment=commitment,
            )
            run_ids.append(run.id)
            view_token = create_view_token(session, run.id)
            credentials.append(
                CampaignEpisodeCredential(
                    run_id=run.id,
                    profile=profile,
                    token=token,
                    view_token=view_token,
                )
            )

    campaign.run_ids = run_ids
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign, credentials


def get_campaign(session: Session, campaign_id: str) -> Campaign | None:
    return session.get(Campaign, campaign_id)

"""Creation and lookup of multi-profile full-agent campaigns."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlmodel import Session, select

from halu_core.canonical_json import canonical_hash
from halu_core.challenges.registry import ChallengeNotFoundError, registry
from halu_core.models.campaign import Campaign
from halu_core.models.campaign_view_token import CampaignViewToken
from halu_core.models.enums import AgentType, CampaignStatus, EpisodeProfile
from halu_core.models.runtime_package import RuntimePackage
from halu_core.services.run_service import create_run, create_view_token
from halu_core.services.token_service import generate_raw_token, hash_token, verify_token
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


def create_campaign_view_token(session: Session, campaign_id: str) -> str:
    """Mint a show-once, read-only campaign comparison credential."""
    raw_token = generate_raw_token(32)
    now = utc_now()
    session.add(
        CampaignViewToken(
            campaign_id=campaign_id,
            token_hash=hash_token(raw_token),
            created_at=now,
            expires_at=now + timedelta(days=30),
        )
    )
    session.commit()
    return raw_token


def authenticate_campaign_view(
    session: Session, campaign_id: str, raw_token: str
) -> Campaign | None:
    campaign = session.get(Campaign, campaign_id)
    if campaign is None or not raw_token:
        return None
    candidates = session.exec(
        select(CampaignViewToken).where(CampaignViewToken.campaign_id == campaign_id)
    ).all()
    now = utc_now()
    valid = any(
        not token.revoked
        and token.expires_at > now
        and verify_token(raw_token, token.token_hash)
        for token in candidates
    )
    return campaign if valid else None

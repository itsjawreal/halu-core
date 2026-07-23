"""Full-agent runtime package, campaign, and lifecycle contracts."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from halu_core.models.campaign_view_token import CampaignViewToken
from halu_core.models.enums import EpisodeProfile, RunStatus
from halu_core.models.run import Run
from halu_core.services.lifecycle_service import (
    InvalidLifecycleTransitionError,
    StaleStatusRevisionError,
    transition_run,
)

_DIGEST = "sha256:" + ("a" * 64)


def _register_runtime(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/runtime-packages",
        json={
            "name": "openclaw-evaluator",
            "version": "1.0.0",
            "reproducibility": "attested",
            "config_digest": _DIGEST,
            "soul_digest": "sha256:" + ("b" * 64),
            "declared_models": [{"provider": "openai", "model": "gpt-test"}],
            "public_metadata": {"framework": "OpenClaw"},
        },
    )
    assert response.status_code == 201
    return response.json()


def test_runtime_package_registration_is_immutable_and_readable(
    client: TestClient,
) -> None:
    package = _register_runtime(client)

    read = client.get(f"/api/v1/runtime-packages/{package['id']}")
    assert read.status_code == 200
    assert read.json() == package

    duplicate = client.post(
        "/api/v1/runtime-packages",
        json={
            "name": "openclaw-evaluator",
            "version": "1.0.0",
            "reproducibility": "attested",
            "config_digest": _DIGEST,
        },
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == package["id"]


def test_runtime_package_rejects_noncanonical_digest(client: TestClient) -> None:
    response = client.post(
        "/api/v1/runtime-packages",
        json={
            "name": "bad-package",
            "version": "1",
            "reproducibility": "unverified",
            "config_digest": "not-a-digest",
        },
    )
    assert response.status_code == 422


def test_campaign_creates_one_episode_per_profile_and_seed(
    client: TestClient, session: Session
) -> None:
    package = _register_runtime(client)
    response = client.post(
        "/api/v1/campaigns",
        json={
            "runtime_package_id": package["id"],
            "challenge_id": "example_ping_001",
            "profiles": ["cold", "interrupted", "adversarial"],
            "seeds_per_profile": 2,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "running"
    assert body["challenge_version"] == "1.0.0"
    assert len(body["run_ids"]) == 6
    assert len(body["episode_credentials"]) == 6
    assert len({item["token"] for item in body["episode_credentials"]}) == 6
    assert body["campaign_view_token"]
    stored_view_tokens = session.exec(
        select(CampaignViewToken).where(CampaignViewToken.campaign_id == body["id"])
    ).all()
    assert len(stored_view_tokens) == 1
    assert stored_view_tokens[0].token_hash != body["campaign_view_token"]

    denied = client.get(
        f"/api/v1/campaigns/{body['id']}/result",
        headers={"X-Campaign-View-Token": "wrong"},
    )
    assert denied.status_code == 404
    comparison = client.get(
        f"/api/v1/campaigns/{body['id']}/result",
        headers={"X-Campaign-View-Token": body["campaign_view_token"]},
    )
    assert comparison.status_code == 200
    assert comparison.json()["total_episodes"] == 6
    assert comparison.json()["completed_episodes"] == 0

    runs = [session.get(Run, run_id) for run_id in body["run_ids"]]
    assert all(run is not None for run in runs)
    assert {run.episode_profile for run in runs if run is not None} == {
        EpisodeProfile.COLD,
        EpisodeProfile.INTERRUPTED,
        EpisodeProfile.ADVERSARIAL,
    }
    assert all(run.runtime_package_id == package["id"] for run in runs if run is not None)
    assert all(run.campaign_id == body["id"] for run in runs if run is not None)
    assert all(run.scenario_seed_commitment for run in runs if run is not None)
    assert all(run.challenge_version == "1.0.0" for run in runs if run is not None)


def test_campaign_requires_existing_runtime_package(client: TestClient) -> None:
    response = client.post(
        "/api/v1/campaigns",
        json={
            "runtime_package_id": "rtpkg_missing",
            "challenge_id": "example_ping_001",
            "profiles": ["cold"],
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "runtime_package_not_found"


def test_campaign_requires_registered_challenge_version(client: TestClient) -> None:
    package = _register_runtime(client)
    response = client.post(
        "/api/v1/campaigns",
        json={
            "runtime_package_id": package["id"],
            "challenge_id": "example_ping_001",
            "challenge_version": "999.0.0",
            "profiles": ["cold"],
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "challenge_version_not_found"


def test_lifecycle_transition_uses_revision_compare_and_swap(
    client: TestClient, session: Session
) -> None:
    created = client.post(
        "/api/v1/runs",
        json={"challenge_id": "example_ping_001", "agent_type": "generic"},
    ).json()
    run = session.get(Run, created["run_id"])
    assert run is not None

    transition_run(
        session,
        run,
        target=RunStatus.INTERRUPTED,
        expected_revision=0,
    )
    assert run.status == RunStatus.INTERRUPTED
    assert run.status_revision == 1

    try:
        transition_run(
            session,
            run,
            target=RunStatus.RESUMING,
            expected_revision=0,
        )
    except StaleStatusRevisionError:
        pass
    else:
        raise AssertionError("A stale lifecycle revision must be rejected.")

    try:
        transition_run(
            session,
            run,
            target=RunStatus.COMPLETED,
            expected_revision=1,
        )
    except InvalidLifecycleTransitionError:
        pass
    else:
        raise AssertionError("An invalid lifecycle edge must be rejected.")


def test_interrupted_episode_checkpoint_rotates_credentials_and_resumes(
    client: TestClient,
) -> None:
    package = _register_runtime(client)
    campaign = client.post(
        "/api/v1/campaigns",
        json={
            "runtime_package_id": package["id"],
            "challenge_id": "example_ping_001",
            "profiles": ["interrupted"],
        },
    ).json()
    episode = campaign["episode_credentials"][0]
    run_id = episode["run_id"]
    old_auth = {"Authorization": f"Bearer {episode['token']}"}

    profile = client.get(f"/api/v1/runs/{run_id}/profile", headers=old_auth)
    assert profile.status_code == 200
    assert profile.json()["profile"] == "interrupted"
    assert profile.json()["profile_context"]["recovery_contract"]

    events = client.get(f"/api/v1/runs/{run_id}/events", headers=old_auth).json()
    last_sequence = events["events"][-1]["sequence"]
    checkpoint = client.post(
        f"/api/v1/runs/{run_id}/checkpoint",
        headers=old_auth,
        json={
            "digest": "sha256:" + ("c" * 64),
            "last_acknowledged_sequence": last_sequence,
            "expected_revision": 0,
        },
    )
    assert checkpoint.status_code == 201
    assert checkpoint.json()["status"] == "checkpointed"

    interrupted = client.post(
        f"/api/v1/campaigns/{campaign['id']}/episodes/{run_id}/interrupt",
        json={"expected_revision": 1},
    )
    assert interrupted.status_code == 200
    resume_token = interrupted.json()["resume_token"]

    assert client.get(f"/api/v1/runs/{run_id}/profile", headers=old_auth).status_code == 401

    resumed = client.post(
        f"/api/v1/runs/{run_id}/resume",
        headers={"Authorization": f"Bearer {resume_token}"},
    )
    assert resumed.status_code == 200
    body = resumed.json()
    assert body["status"] == "active"
    assert body["credential_generation"] == 2
    assert body["checkpoint_digest"] == "sha256:" + ("c" * 64)
    assert body["reconciliation_required"] is True
    assert {event["event_type"] for event in body["events_after_checkpoint"]} >= {
        "checkpoint_created",
        "runtime_interrupted",
        "runtime_resumed",
    }

    new_auth = {"Authorization": f"Bearer {body['agent_token']}"}
    assert client.get(f"/api/v1/runs/{run_id}/profile", headers=new_auth).status_code == 200
    replay = client.post(
        f"/api/v1/runs/{run_id}/resume",
        headers={"Authorization": f"Bearer {resume_token}"},
    )
    assert replay.status_code == 401


def test_checkpoint_is_rejected_for_non_interrupted_profile(client: TestClient) -> None:
    created = client.post(
        "/api/v1/runs",
        json={"challenge_id": "example_ping_001", "agent_type": "generic"},
    ).json()
    response = client.post(
        f"/api/v1/runs/{created['run_id']}/checkpoint",
        headers={"Authorization": f"Bearer {created['token']}"},
        json={
            "digest": "sha256:" + ("d" * 64),
            "last_acknowledged_sequence": 0,
            "expected_revision": 0,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "profile_operation_not_allowed"

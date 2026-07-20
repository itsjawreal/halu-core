"""Tests for Phase 7.5's benchmark integrity: challenge manifests
(dataset/hidden-truth/scoring-rules hashes), automated quality checks
run at registration, a run's manifest snapshot staying reproducible,
and the non-destructive score-revision audit trail.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from halu_core.challenges.base import Challenge
from halu_core.challenges.models import ActionRequest, ActionResult
from halu_core.challenges.quality import ChallengeQualityError
from halu_core.challenges.registry import (
    ChallengeManifestMismatchError,
    ChallengeRegistry,
)
from halu_core.models.enums import AgentType
from halu_core.models.score import RunScore
from halu_core.models.score_revision import ScoreRevision
from halu_core.services import result_service, scoring_service
from halu_core.services.run_service import create_run


class _ManifestChallenge(Challenge):
    """Minimal complete challenge for manifest/quality-check tests."""

    def __init__(self, target: int = 3) -> None:
        self._target = target

    @property
    def id(self) -> str:
        return "manifest_test_001"

    @property
    def name(self) -> str:
        return "Manifest Test Challenge"

    @property
    def time_limit_seconds(self) -> int:
        return 60

    @property
    def public_instructions(self) -> str:
        return "Increment the counter to the target."

    @property
    def allowed_actions(self) -> tuple[str, ...]:
        return ("increment", "complete_run")

    def build_initial_state(self) -> dict[str, Any]:
        return {"value": 0, "target": self._target}

    def validate_action(self, state: dict[str, Any], action: ActionRequest) -> ActionResult:
        if action.action == "complete_run":
            return ActionResult(success=True, state_changed=False)
        if action.action != "increment":
            return ActionResult(success=False, state_changed=False, error_code="unknown_action")
        return ActionResult(success=True, state_changed=True)

    def apply_action(self, state: dict[str, Any], action: ActionRequest) -> dict[str, Any]:
        result = self.validate_action(state, action)
        if not result.success or action.action == "complete_run":
            return state
        return {**state, "value": state["value"] + 1}

    def is_complete(self, state: dict[str, Any]) -> bool:
        return state["value"] >= state["target"]

    def hidden_truth_hash(self) -> str:
        from halu_core.challenges.manifest import stable_hash

        return stable_hash({"target": self._target})


@pytest.fixture()
def fresh_registry() -> ChallengeRegistry:
    return ChallengeRegistry()


# -- Manifest hashing ------------------------------------------------------


def test_manifest_hash_is_deterministic_across_instances() -> None:
    first = _ManifestChallenge().manifest()
    second = _ManifestChallenge().manifest()
    assert first.dataset_hash == second.dataset_hash
    assert first.hidden_truth_hash == second.hidden_truth_hash
    assert first.scoring_rules_hash == second.scoring_rules_hash
    assert first.content_hash == second.content_hash


def test_manifest_hash_changes_when_hidden_truth_changes() -> None:
    a = _ManifestChallenge(target=3).manifest()
    b = _ManifestChallenge(target=5).manifest()
    assert a.hidden_truth_hash != b.hidden_truth_hash
    assert a.content_hash != b.content_hash


def test_manifest_public_dict_exposes_only_hashes_and_version() -> None:
    manifest = _ManifestChallenge().manifest()
    public = manifest.to_public_dict()
    assert set(public) == {
        "challenge_id",
        "version",
        "dataset_hash",
        "hidden_truth_hash",
        "scoring_rules_hash",
        "published_at",
        "scoring_engine_version",
    }
    # No raw dataset/answer-key content anywhere in the public shape.
    assert "target" not in str(public)


# -- Registry: manifest-hash mismatch rejection ---------------------------


def test_registry_rejects_same_version_with_different_manifest(
    fresh_registry: ChallengeRegistry,
) -> None:
    fresh_registry.register(_ManifestChallenge(target=3))
    with pytest.raises(ChallengeManifestMismatchError):
        fresh_registry.register(_ManifestChallenge(target=99), replace=True)


def test_registry_allows_manifest_change_in_explicit_dev_mode(
    fresh_registry: ChallengeRegistry,
) -> None:
    fresh_registry.register(_ManifestChallenge(target=3))
    fresh_registry.register(
        _ManifestChallenge(target=99), replace=True, allow_manifest_change=True
    )
    assert fresh_registry.get("manifest_test_001").build_initial_state()["target"] == 99


def test_registry_allows_reregistering_identical_content(
    fresh_registry: ChallengeRegistry,
) -> None:
    fresh_registry.register(_ManifestChallenge(target=3))
    # Same content (same target) -- no mismatch, no need for allow_manifest_change.
    fresh_registry.register(_ManifestChallenge(target=3), replace=True)


# -- Registry: automated quality checks -----------------------------------


class _BrokenWeightsChallenge(_ManifestChallenge):
    @property
    def id(self) -> str:
        return "broken_weights_001"

    def scoring_weight_overrides(self) -> dict[str, float] | None:
        return {"claim_accuracy": 0.5, "task_completion": 0.9}  # sums to 1.4


class _NoNameChallenge(_ManifestChallenge):
    @property
    def id(self) -> str:
        return "broken_name_001"

    @property
    def name(self) -> str:
        return ""


class _NondeterministicChallenge(_ManifestChallenge):
    _counter = 0

    @property
    def id(self) -> str:
        return "nondeterministic_001"

    def build_initial_state(self) -> dict[str, Any]:
        _NondeterministicChallenge._counter += 1
        return {"value": 0, "target": self._target, "call": _NondeterministicChallenge._counter}


class _HiddenKeyLeakChallenge(_ManifestChallenge):
    @property
    def id(self) -> str:
        return "hidden_key_leak_001"

    def list_items(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"id": "x", "_secret_answer": "should never be public"}]


def test_registry_rejects_invalid_scoring_weights(fresh_registry: ChallengeRegistry) -> None:
    with pytest.raises(ChallengeQualityError, match="scoring_weight_overrides"):
        fresh_registry.register(_BrokenWeightsChallenge())


def test_registry_rejects_empty_name(fresh_registry: ChallengeRegistry) -> None:
    with pytest.raises(ChallengeQualityError, match="name"):
        fresh_registry.register(_NoNameChallenge())


def test_registry_rejects_nondeterministic_initial_state(
    fresh_registry: ChallengeRegistry,
) -> None:
    with pytest.raises(ChallengeQualityError, match="deterministic"):
        fresh_registry.register(_NondeterministicChallenge())


def test_registry_rejects_hidden_key_leak_in_list_items(
    fresh_registry: ChallengeRegistry,
) -> None:
    with pytest.raises(ChallengeQualityError, match="hidden"):
        fresh_registry.register(_HiddenKeyLeakChallenge())


def test_skip_quality_checks_bypasses_validation_for_test_stand_ins(
    fresh_registry: ChallengeRegistry,
) -> None:
    # Explicit opt-out for tests that intentionally exercise a broken
    # challenge -- never the default.
    fresh_registry.register(_NoNameChallenge(), skip_quality_checks=True)
    assert fresh_registry.is_registered("broken_name_001")


# -- Run manifest snapshot: reproducibility -------------------------------


@pytest.fixture()
def manifest_challenge_id(fresh_registry: ChallengeRegistry) -> Iterator[str]:
    from halu_core.challenges.registry import registry as global_registry

    challenge = _ManifestChallenge()
    global_registry.register(challenge, replace=True)
    yield challenge.id
    global_registry.unregister(challenge.id)


def test_run_snapshots_the_challenge_manifest_at_creation(
    session: Session, manifest_challenge_id: str
) -> None:
    expected = _ManifestChallenge().manifest()
    run, _token = create_run(
        session, challenge_id=manifest_challenge_id, agent_type=AgentType.GENERIC
    )
    assert run.manifest_dataset_hash == expected.dataset_hash
    assert run.manifest_hidden_truth_hash == expected.hidden_truth_hash
    assert run.manifest_scoring_rules_hash == expected.scoring_rules_hash
    assert run.manifest_scoring_engine_version == expected.scoring_engine_version


def test_run_creation_never_fails_for_an_unregistered_challenge_id(session: Session) -> None:
    run, _token = create_run(
        session, challenge_id="totally_unregistered_id", agent_type=AgentType.GENERIC
    )
    assert run.manifest_dataset_hash is None


def test_existing_run_manifest_is_unaffected_by_a_later_registered_version(
    session: Session, manifest_challenge_id: str
) -> None:
    from halu_core.challenges.registry import registry as global_registry

    run, _token = create_run(
        session, challenge_id=manifest_challenge_id, agent_type=AgentType.GENERIC
    )
    original_hash = run.manifest_hidden_truth_hash

    class _ManifestChallengeV2(_ManifestChallenge):
        @property
        def version(self) -> str:
            return "2.0.0"

    global_registry.register(_ManifestChallengeV2(target=999))
    try:
        assert run.manifest_hidden_truth_hash == original_hash
    finally:
        global_registry.unregister(manifest_challenge_id, version="2.0.0")


def test_benchmark_manifest_never_leaks_hidden_data_via_result(
    client: TestClient, session: Session, manifest_challenge_id: str
) -> None:
    response = client.post(
        "/api/v1/runs", json={"challenge_id": manifest_challenge_id, "agent_type": "generic"}
    )
    run_id, token = response.json()["run_id"], response.json()["token"]
    for _ in range(3):
        client.post(
            f"/api/v1/runs/{run_id}/actions",
            json={"action": "increment"},
            headers={"Authorization": f"Bearer {token}"},
        )
    client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"summary": "done", "claims": []},
        headers={"Authorization": f"Bearer {token}"},
    )

    result = result_service.get_result(session, run_id)
    assert result is not None
    manifest = result["benchmark_manifest"]
    assert manifest is not None
    assert set(manifest) == {
        "challenge_id",
        "version",
        "dataset_hash",
        "hidden_truth_hash",
        "scoring_rules_hash",
        "published_at",
        "scoring_engine_version",
    }
    assert "target" not in str(manifest)


# -- Score revision audit trail: recompute never overwrites the original --


def test_recompute_appends_a_revision_without_touching_the_original_score(
    client: TestClient, session: Session, manifest_challenge_id: str
) -> None:
    from halu_core.challenges.registry import registry as global_registry

    response = client.post(
        "/api/v1/runs", json={"challenge_id": manifest_challenge_id, "agent_type": "generic"}
    )
    run_id, token = response.json()["run_id"], response.json()["token"]
    client.post(
        f"/api/v1/runs/{run_id}/actions",
        json={"action": "increment"},
        headers={"Authorization": f"Bearer {token}"},
    )
    client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"summary": "done", "claims": []},
        headers={"Authorization": f"Bearer {token}"},
    )

    original_score = session.get(RunScore, run_id)
    assert original_score is not None
    original_task_completion = original_score.task_completion  # 1/3 -> ~33.3

    revisions_before = scoring_service.get_score_revisions(session, run_id)
    assert len(revisions_before) == 1
    assert revisions_before[0].revision_number == 0
    assert revisions_before[0].previous_score_id is None

    challenge = global_registry.get(manifest_challenge_id)
    new_revision = scoring_service.recompute_and_persist(
        session, challenge, run_id=run_id, reason="scoring_formula_fix"
    )

    assert new_revision.revision_number == 1
    assert new_revision.previous_score_id == revisions_before[0].id
    assert new_revision.reason == "scoring_formula_fix"
    assert new_revision.scoring_version == scoring_service.SCORING_VERSION

    # The original RunScore row is completely untouched.
    unchanged_score = session.get(RunScore, run_id)
    assert unchanged_score is not None
    assert unchanged_score.task_completion == original_task_completion

    # get_result() (the default/public path) still reflects the
    # original -- never the recompute.
    result = result_service.get_result(session, run_id)
    assert result is not None
    assert result["scores"]["task_completion"] == original_task_completion

    all_revisions = scoring_service.get_score_revisions(session, run_id)
    assert len(all_revisions) == 2
    assert [r.revision_number for r in all_revisions] == [0, 1]


def test_multiple_recomputes_chain_previous_score_ids(
    client: TestClient, session: Session, manifest_challenge_id: str
) -> None:
    from halu_core.challenges.registry import registry as global_registry

    response = client.post(
        "/api/v1/runs", json={"challenge_id": manifest_challenge_id, "agent_type": "generic"}
    )
    run_id, token = response.json()["run_id"], response.json()["token"]
    client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"summary": "done", "claims": []},
        headers={"Authorization": f"Bearer {token}"},
    )

    challenge = global_registry.get(manifest_challenge_id)
    rev1 = scoring_service.recompute_and_persist(session, challenge, run_id=run_id)
    rev2 = scoring_service.recompute_and_persist(session, challenge, run_id=run_id)

    assert rev1.revision_number == 1
    assert rev2.revision_number == 2
    assert rev2.previous_score_id == rev1.id

    all_scores = session.exec(select(RunScore).where(RunScore.run_id == run_id)).all()
    assert len(all_scores) == 1  # RunScore was never duplicated or replaced

    all_revisions = session.exec(
        select(ScoreRevision).where(ScoreRevision.run_id == run_id)
    ).all()
    assert len(all_revisions) == 3  # revision 0 (original) + 2 recomputes

"""Deterministic v0.11 reliability explanation contracts."""

from __future__ import annotations

from datetime import timedelta

from halu_core.models.enums import AgentType, EpisodeProfile
from halu_core.models.event import RunEvent
from halu_core.models.run import Run
from halu_core.models.score import RunScore
from halu_core.models.verification import ClaimVerificationRecord
from halu_core.services.explanation_service import build_explanation
from halu_core.timeutils import utc_now


def _run(*, profile: EpisodeProfile = EpisodeProfile.COLD) -> Run:
    return Run(
        id="run_explain",
        challenge_id="test",
        challenge_version="1.0.0",
        agent_type=AgentType.GENERIC,
        episode_profile=profile,
        expires_at=utc_now() + timedelta(hours=1),
    )


def _score(**overrides: object) -> RunScore:
    values: dict[str, object] = {
        "run_id": "run_explain",
        "task_completion": 100.0,
        "action_accuracy": 100.0,
        "claim_accuracy": 100.0,
        "tool_usage": 100.0,
        "safety": 100.0,
        "efficiency": 90.0,
        "execution_reliability": 100.0,
        "reporting_honesty": 100.0,
        "halu_score": 0.0,
        "technical_verdict": "VERIFIED",
        "shareable_verdict": "REAL WORK",
        "verdict_reasons": ["all_verified_thresholds_met"],
        "scoring_version": "v1",
        "objectives": [{"id": "o1", "description": "Do the work", "completed": True}],
        "safety_incidents": [],
    }
    values.update(overrides)
    return RunScore(**values)  # type: ignore[arg-type]


def _event(
    sequence: int,
    event_type: str,
    *,
    success: bool = True,
    target_id: str | None = None,
) -> RunEvent:
    return RunEvent(
        run_id="run_explain",
        sequence=sequence,
        event_type=event_type,
        source="test",
        success=success,
        state_changed=False,
        target_id=target_id,
    )


def _claim(*, status: str = "verified") -> ClaimVerificationRecord:
    return ClaimVerificationRecord(
        run_id="run_explain",
        claim_type="completed",
        claimed_value=True,
        actual_value=status == "verified",
        status=status,
        accuracy=1.0 if status == "verified" else 0.0,
        reason="checked",
        evidence_event_sequences=[2],
    )


def test_clean_run_gets_auditable_ready_verdict() -> None:
    result = build_explanation(
        run=_run(),
        score=_score(),
        verifications=[_claim()],
        events=[_event(1, "run_created"), _event(2, "action_succeeded")],
    )

    assert result["actionable_verdict"]["readiness"] == "production_ready"
    assert [item["key"] for item in result["reliability_profile"]] == [
        "outcome",
        "safety",
        "honesty",
        "recovery",
        "orchestration",
        "efficiency",
    ]
    assert result["reliability_profile"][3]["status"] == "not_evaluated"
    assert result["findings"][0]["severity"] == "success"
    assert result["timeline"][1]["sequence"] == 2


def test_false_claim_becomes_critical_blocker_with_evidence() -> None:
    result = build_explanation(
        run=_run(),
        score=_score(reporting_honesty=0.0, technical_verdict="CONTRADICTED"),
        verifications=[_claim(status="contradicted")],
        events=[_event(2, "action_succeeded")],
    )

    assert result["actionable_verdict"]["readiness"] == "needs_review"
    assert "contradicted claims" in result["actionable_verdict"]["blockers"][-1]
    finding = next(item for item in result["findings"] if item["category"] == "honesty")
    assert finding["severity"] == "critical"
    assert finding["evidence_event_sequences"] == [2]


def test_interruption_recovery_is_scored_from_event_order() -> None:
    result = build_explanation(
        run=_run(profile=EpisodeProfile.INTERRUPTED),
        score=_score(),
        verifications=[_claim()],
        events=[
            _event(1, "checkpoint_created"),
            _event(2, "runtime_interrupted"),
            _event(3, "runtime_resumed"),
        ],
    )

    recovery = next(item for item in result["reliability_profile"] if item["key"] == "recovery")
    assert recovery["score"] == 100.0
    assert recovery["status"] == "strong"
    assert recovery["evidence_event_sequences"] == [1, 2, 3]


def test_no_claims_is_not_misrepresented_as_strong_honesty() -> None:
    result = build_explanation(
        run=_run(),
        score=_score(reporting_honesty=100.0),
        verifications=[],
        events=[],
    )

    honesty = next(item for item in result["reliability_profile"] if item["key"] == "honesty")
    assert honesty["score"] is None
    assert honesty["status"] == "not_evaluated"
    assert result["actionable_verdict"]["readiness"] == "needs_review"
    assert "no checkable claims" in result["actionable_verdict"]["blockers"][-1]


def test_multi_agent_without_telemetry_is_explicitly_not_evaluated() -> None:
    result = build_explanation(
        run=_run(profile=EpisodeProfile.MULTI_AGENT),
        score=_score(),
        verifications=[_claim()],
        events=[],
    )

    orchestration = next(
        item for item in result["reliability_profile"] if item["key"] == "orchestration"
    )
    assert orchestration["score"] is None
    assert orchestration["status"] == "not_evaluated"
    assert "not verifiably exercised" in result["actionable_verdict"]["blockers"][-1]

"""Internal result access (spec §9, Phase 5).

A completed run's Agent API token is revoked, so the agent itself can
never read `GET /result` again -- by design (spec §9's "revoked token
cannot read result" requirement is enforced simply by that revocation,
via the same scope dependency every other endpoint uses). Until user
authentication exists (Phase 6), the website reads a run's result
through this internal service instead of the Agent API.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from halu_core.models.final_report import FinalReport
from halu_core.models.run import Run
from halu_core.models.score import RunScore
from halu_core.models.verification import ClaimVerificationRecord
from halu_core.services import event_service, explanation_service


def get_result(session: Session, run_id: str) -> dict[str, Any] | None:
    """Return the same shape as the Agent API's `GET /result`, or None
    if this run has no score yet (not completed, or completion failed
    and rolled back before a score was ever persisted).

    Always reflects the *original* score computed at completion time
    (Phase 7.5): `RunScore` is written exactly once and never touched
    by `scoring_service.recompute_and_persist`, which appends a new
    `ScoreRevision` instead -- so this never silently changes just
    because an internal recompute happened later.
    """
    score = session.get(RunScore, run_id)
    if score is None:
        return None

    verifications = session.exec(
        select(ClaimVerificationRecord).where(ClaimVerificationRecord.run_id == run_id)
    ).all()
    final_report = session.get(FinalReport, run_id)
    summary = (
        {"text": final_report.summary, "claims": final_report.claims}
        if final_report is not None
        else {}
    )

    run = session.get(Run, run_id)
    events = event_service.list_events(session, run_id, limit=10_000)
    explanation = (
        explanation_service.build_explanation(
            run=run,
            score=score,
            verifications=list(verifications),
            events=events,
        )
        if run is not None
        else {
            "actionable_verdict": None,
            "reliability_profile": [],
            "findings": [],
            "timeline": [],
        }
    )
    benchmark_manifest = (
        {
            "challenge_id": run.challenge_id,
            "version": run.challenge_version,
            "dataset_hash": run.manifest_dataset_hash,
            "hidden_truth_hash": run.manifest_hidden_truth_hash,
            "scoring_rules_hash": run.manifest_scoring_rules_hash,
            "published_at": run.manifest_published_at,
            "scoring_engine_version": run.manifest_scoring_engine_version,
        }
        if run is not None
        else None
    )

    return {
        "run_id": run_id,
        "scores": {
            "task_completion": score.task_completion,
            "action_accuracy": score.action_accuracy,
            "claim_accuracy": score.claim_accuracy,
            "tool_usage": score.tool_usage,
            "safety": score.safety,
            "efficiency": score.efficiency,
            "execution_reliability": score.execution_reliability,
            "reporting_honesty": score.reporting_honesty,
            "halu_score": score.halu_score,
        },
        "technical_verdict": score.technical_verdict,
        "shareable_verdict": score.shareable_verdict,
        "verdict_reasons": score.verdict_reasons,
        "claim_verifications": [
            {
                "claim_type": v.claim_type,
                "claimed_value": v.claimed_value,
                "actual_value": v.actual_value,
                "status": v.status,
                "accuracy": v.accuracy,
                "reason": v.reason,
                "evidence_event_sequences": v.evidence_event_sequences,
            }
            for v in verifications
        ],
        "objectives": score.objectives,
        "safety_incidents": score.safety_incidents,
        "summary": summary,
        "scoring_version": score.scoring_version,
        "benchmark_manifest": benchmark_manifest,
        **explanation,
    }

"""Data retention cleanup (Phase 8 §5).

Never runs automatically -- only via the explicit `halu-checker cleanup`
CLI command, so an operator always chooses exactly when this executes.
`--dry-run` computes and reports everything that *would* be deleted
without deleting anything; a real run commits those same deletions and
logs a structured summary line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlmodel import Session, col, select

from halu_core.config import settings
from halu_core.logging_config import operational_logger
from halu_core.models.claim import RunClaim
from halu_core.models.enums import RunStatus
from halu_core.models.event import RunEvent
from halu_core.models.final_report import FinalReport
from halu_core.models.flaky import FlakyItemLog
from halu_core.models.idempotency import IdempotencyRecord
from halu_core.models.public_share import RunPublicShare
from halu_core.models.rate_limit import RateLimitCounter
from halu_core.models.run import Run
from halu_core.models.score import RunScore
from halu_core.models.score_revision import ScoreRevision
from halu_core.models.state import RunChallengeState
from halu_core.models.token import RunToken
from halu_core.models.verification import ClaimVerificationRecord
from halu_core.models.view_token import RunViewToken

_RUN_CHILD_MODELS = (
    RunEvent,
    RunClaim,
    ClaimVerificationRecord,
    RunScore,
    ScoreRevision,
    FinalReport,
    RunChallengeState,
    IdempotencyRecord,
    FlakyItemLog,
    RateLimitCounter,
    RunPublicShare,
    RunToken,
    RunViewToken,
)


@dataclass
class CleanupReport:
    dry_run: bool
    incomplete_runs_deleted: list[str] = field(default_factory=list)
    completed_runs_deleted: list[str] = field(default_factory=list)
    completed_runs_skipped_public_share: list[str] = field(default_factory=list)
    expired_agent_tokens_deleted: int = 0
    expired_view_tokens_deleted: int = 0

    @property
    def total_runs_deleted(self) -> int:
        return len(self.incomplete_runs_deleted) + len(self.completed_runs_deleted)


def _delete_run_cascade(session: Session, run_id: str) -> None:
    """Delete every row belonging to `run_id`, then the run itself.

    A manual cascade -- SQLite doesn't enforce `ON DELETE CASCADE` by
    default, so this codebase never relies on the database to do it.
    Never touches `run.manifest_*` on any *other*, still-retained run:
    this only ever deletes rows scoped to this one `run_id`.
    """
    for model in _RUN_CHILD_MODELS:
        for row in session.exec(select(model).where(model.run_id == run_id)).all():
            session.delete(row)
    run = session.get(Run, run_id)
    if run is not None:
        session.delete(run)


def _public_share_blocks_deletion(
    session: Session, run_id: str, now: datetime, retention_public_share_days: int
) -> bool:
    """A completed run must never be deleted while actively publicly
    shared, and stays protected for `retention_public_share_days` after
    the share is disabled (spec: "tidak terhapus sebelum share
    dinonaktifkan atau retention khusus tercapai").
    """
    shares = session.exec(select(RunPublicShare).where(RunPublicShare.run_id == run_id)).all()
    if not shares:
        return False
    if any(s.enabled for s in shares):
        return True
    disabled_ats = [s.disabled_at for s in shares if s.disabled_at is not None]
    if not disabled_ats:
        return False
    eligible_at = max(disabled_ats) + timedelta(days=retention_public_share_days)
    return now < eligible_at


def cleanup_incomplete_runs(
    session: Session, *, now: datetime, retention_days: int, dry_run: bool
) -> list[str]:
    """Runs that never completed (pending/active/expired) and are older
    than `retention_days`. `retention_days <= 0` disables this bucket.
    """
    if retention_days <= 0:
        return []
    cutoff = now - timedelta(days=retention_days)
    candidates = session.exec(
        select(Run).where(
            col(Run.status).in_(
                [RunStatus.PENDING, RunStatus.ACTIVE, RunStatus.EXPIRED]
            ),
            Run.created_at < cutoff,
        )
    ).all()
    run_ids = [r.id for r in candidates]
    if not dry_run:
        for run_id in run_ids:
            _delete_run_cascade(session, run_id)
        session.commit()
    return run_ids


def cleanup_completed_runs(
    session: Session,
    *,
    now: datetime,
    retention_days: int,
    retention_public_share_days: int,
    dry_run: bool,
) -> tuple[list[str], list[str]]:
    """Completed runs older than `retention_days`, excluding any still
    protected by an active or recently-disabled public share. Returns
    (deleted_run_ids, skipped_run_ids_due_to_public_share).
    """
    if retention_days <= 0:
        return [], []
    cutoff = now - timedelta(days=retention_days)
    candidates = session.exec(
        select(Run).where(
            Run.status == RunStatus.COMPLETED,
            col(Run.completed_at).is_not(None),
            col(Run.completed_at) < cutoff,
        )
    ).all()
    deleted: list[str] = []
    skipped: list[str] = []
    for run in candidates:
        if _public_share_blocks_deletion(session, run.id, now, retention_public_share_days):
            skipped.append(run.id)
            continue
        deleted.append(run.id)
        if not dry_run:
            _delete_run_cascade(session, run.id)
    if not dry_run and deleted:
        session.commit()
    return deleted, skipped


def cleanup_expired_tokens(
    session: Session, *, now: datetime, retention_days: int, dry_run: bool
) -> tuple[int, int]:
    """Deletes long-expired/revoked token rows whose *run* is not
    otherwise being cleaned up this pass (e.g. an old, rotated-away
    view token on a run that's still active). Never deletes a Run.
    """
    if retention_days <= 0:
        return 0, 0
    cutoff = now - timedelta(days=retention_days)

    expired_agent_tokens = session.exec(
        select(RunToken).where(col(RunToken.revoked).is_(True), RunToken.expires_at < cutoff)
    ).all()
    expired_view_tokens = session.exec(
        select(RunViewToken).where(
            col(RunViewToken.revoked_at).is_not(None), RunViewToken.expires_at < cutoff
        )
    ).all()
    if not dry_run:
        for agent_token in expired_agent_tokens:
            session.delete(agent_token)
        for view_token in expired_view_tokens:
            session.delete(view_token)
        session.commit()
    return len(expired_agent_tokens), len(expired_view_tokens)


def run_cleanup(session: Session, *, now: datetime, dry_run: bool) -> CleanupReport:
    """Run every cleanup bucket using the configured retention windows
    and log one structured operational summary line.
    """
    incomplete = cleanup_incomplete_runs(
        session,
        now=now,
        retention_days=settings.retention_incomplete_run_days,
        dry_run=dry_run,
    )
    completed, skipped = cleanup_completed_runs(
        session,
        now=now,
        retention_days=settings.retention_completed_run_days,
        retention_public_share_days=settings.retention_public_share_days,
        dry_run=dry_run,
    )
    agent_tokens, view_tokens = cleanup_expired_tokens(
        session,
        now=now,
        retention_days=settings.retention_expired_token_days,
        dry_run=dry_run,
    )
    report = CleanupReport(
        dry_run=dry_run,
        incomplete_runs_deleted=incomplete,
        completed_runs_deleted=completed,
        completed_runs_skipped_public_share=skipped,
        expired_agent_tokens_deleted=agent_tokens,
        expired_view_tokens_deleted=view_tokens,
    )
    operational_logger.info(
        "cleanup_completed dry_run=%s incomplete_runs=%d completed_runs=%d "
        "skipped_public_share=%d expired_agent_tokens=%d expired_view_tokens=%d",
        dry_run,
        len(incomplete),
        len(completed),
        len(skipped),
        agent_tokens,
        view_tokens,
    )
    return report

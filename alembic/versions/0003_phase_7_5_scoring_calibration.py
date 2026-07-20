"""Phase 7.5 scoring calibration: execution reliability / reporting
honesty split, machine-readable verdict reasons, a benchmark manifest
snapshot on each run, and the score-revision audit trail.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- Run: benchmark manifest snapshot (nullable -- best-effort,
    # populated only when the challenge_id/version was resolvable at
    # creation time; never blocks run creation otherwise). ------------
    op.add_column("run", sa.Column("manifest_dataset_hash", sa.String(), nullable=True))
    op.add_column("run", sa.Column("manifest_hidden_truth_hash", sa.String(), nullable=True))
    op.add_column("run", sa.Column("manifest_scoring_rules_hash", sa.String(), nullable=True))
    op.add_column("run", sa.Column("manifest_published_at", sa.String(), nullable=True))
    op.add_column("run", sa.Column("manifest_scoring_engine_version", sa.String(), nullable=True))

    # -- RunScore: execution reliability / reporting honesty split, and
    # machine-readable verdict reasons. Existing rows backfill to 0.0 /
    # an empty reasons list -- their original technical_verdict string
    # is untouched, only these new descriptive fields are new. --------
    op.add_column(
        "runscore",
        sa.Column(
            "execution_reliability", sa.Float(), nullable=False, server_default=sa.text("0.0")
        ),
    )
    op.add_column(
        "runscore",
        sa.Column(
            "reporting_honesty", sa.Float(), nullable=False, server_default=sa.text("0.0")
        ),
    )
    op.add_column("runscore", sa.Column("verdict_reasons", sa.JSON(), nullable=True))
    with op.batch_alter_table("runscore") as batch_op:
        batch_op.alter_column("execution_reliability", server_default=None)
        batch_op.alter_column("reporting_honesty", server_default=None)

    # -- ScoreRevision: audit trail of every score ever computed for a
    # run. Revision 0 is written alongside the original RunScore at
    # completion time; later revisions only via an explicit internal
    # recompute, which never touches RunScore itself. ------------------
    op.create_table(
        "scorerevision",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("previous_score_id", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("task_completion", sa.Float(), nullable=False),
        sa.Column("action_accuracy", sa.Float(), nullable=False),
        sa.Column("claim_accuracy", sa.Float(), nullable=False),
        sa.Column("tool_usage", sa.Float(), nullable=False),
        sa.Column("safety", sa.Float(), nullable=False),
        sa.Column("efficiency", sa.Float(), nullable=False),
        sa.Column("execution_reliability", sa.Float(), nullable=False),
        sa.Column("reporting_honesty", sa.Float(), nullable=False),
        sa.Column("halu_score", sa.Float(), nullable=False),
        sa.Column("technical_verdict", sa.String(), nullable=False),
        sa.Column("shareable_verdict", sa.String(), nullable=False),
        sa.Column("verdict_reasons", sa.JSON(), nullable=True),
        sa.Column("scoring_version", sa.String(), nullable=False),
        sa.Column("objectives", sa.JSON(), nullable=True),
        sa.Column("safety_incidents", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scorerevision_run_id"), "scorerevision", ["run_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_scorerevision_run_id"), table_name="scorerevision")
    op.drop_table("scorerevision")

    with op.batch_alter_table("runscore") as batch_op:
        batch_op.drop_column("verdict_reasons")
        batch_op.drop_column("reporting_honesty")
        batch_op.drop_column("execution_reliability")

    with op.batch_alter_table("run") as batch_op:
        batch_op.drop_column("manifest_scoring_engine_version")
        batch_op.drop_column("manifest_published_at")
        batch_op.drop_column("manifest_scoring_rules_hash")
        batch_op.drop_column("manifest_hidden_truth_hash")
        batch_op.drop_column("manifest_dataset_hash")

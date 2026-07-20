"""Initial schema: every table as of Phase 6 (before Phase 6.5's view-token
hardening and generic rate-limit bucket, which land in revision 0002).

Revision ID: 0001
Revises:
Create Date: 2026-07-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("challenge_id", sa.String(), nullable=False),
        sa.Column("challenge_version", sa.String(), nullable=False),
        sa.Column("agent_type", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=9), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "runtoken",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_runtoken_run_id"), "runtoken", ["run_id"])
    op.create_index(op.f("ix_runtoken_token_hash"), "runtoken", ["token_hash"])

    op.create_table(
        "runviewtoken",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_runviewtoken_run_id"), "runviewtoken", ["run_id"])
    op.create_index(op.f("ix_runviewtoken_token_hash"), "runviewtoken", ["token_hash"])

    op.create_table(
        "runchallengestate",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("run_id"),
    )

    op.create_table(
        "idempotencyrecord",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "key", name="uq_idempotency_run_key"),
    )
    op.create_index(op.f("ix_idempotencyrecord_run_id"), "idempotencyrecord", ["run_id"])
    op.create_index(op.f("ix_idempotencyrecord_key"), "idempotencyrecord", ["key"])

    op.create_table(
        "flakyitemlog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("item_id", sa.String(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "item_id", name="uq_flaky_run_item"),
    )
    op.create_index(op.f("ix_flakyitemlog_run_id"), "flakyitemlog", ["run_id"])
    op.create_index(op.f("ix_flakyitemlog_item_id"), "flakyitemlog", ["item_id"])

    op.create_table(
        "ratelimitcounter",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("bucket", sa.String(), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "bucket", "window_start", name="uq_rate_limit_window"),
    )
    op.create_index(op.f("ix_ratelimitcounter_run_id"), "ratelimitcounter", ["run_id"])
    op.create_index(op.f("ix_ratelimitcounter_bucket"), "ratelimitcounter", ["bucket"])
    op.create_index(
        op.f("ix_ratelimitcounter_window_start"), "ratelimitcounter", ["window_start"]
    )

    op.create_table(
        "runevent",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("endpoint", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=True),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("state_changed", sa.Boolean(), nullable=False),
        sa.Column("request_data", sa.JSON(), nullable=True),
        sa.Column("response_data", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("state_before_hash", sa.String(), nullable=True),
        sa.Column("state_after_hash", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_run_event_sequence"),
    )
    op.create_index(op.f("ix_runevent_run_id"), "runevent", ["run_id"])
    op.create_index(op.f("ix_runevent_sequence"), "runevent", ["sequence"])
    op.create_index(op.f("ix_runevent_event_type"), "runevent", ["event_type"])

    op.create_table(
        "runclaim",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("claim_type", sa.String(), nullable=False),
        sa.Column("claimed_value", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_runclaim_run_id"), "runclaim", ["run_id"])
    op.create_index(op.f("ix_runclaim_claim_type"), "runclaim", ["claim_type"])

    op.create_table(
        "claimverificationrecord",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("claim_type", sa.String(), nullable=False),
        sa.Column("claimed_value", sa.JSON(), nullable=True),
        sa.Column("actual_value", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("evidence_event_sequences", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_claimverificationrecord_run_id"), "claimverificationrecord", ["run_id"]
    )

    op.create_table(
        "runscore",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("task_completion", sa.Float(), nullable=False),
        sa.Column("action_accuracy", sa.Float(), nullable=False),
        sa.Column("claim_accuracy", sa.Float(), nullable=False),
        sa.Column("tool_usage", sa.Float(), nullable=False),
        sa.Column("safety", sa.Float(), nullable=False),
        sa.Column("efficiency", sa.Float(), nullable=False),
        sa.Column("halu_score", sa.Float(), nullable=False),
        sa.Column("technical_verdict", sa.String(), nullable=False),
        sa.Column("shareable_verdict", sa.String(), nullable=False),
        sa.Column("scoring_version", sa.String(), nullable=False),
        sa.Column("objectives", sa.JSON(), nullable=True),
        sa.Column("safety_incidents", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("run_id"),
    )

    op.create_table(
        "finalreport",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("claims", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("run_id"),
    )


def downgrade() -> None:
    op.drop_table("finalreport")
    op.drop_table("runscore")
    op.drop_index(op.f("ix_claimverificationrecord_run_id"), table_name="claimverificationrecord")
    op.drop_table("claimverificationrecord")
    op.drop_index(op.f("ix_runclaim_claim_type"), table_name="runclaim")
    op.drop_index(op.f("ix_runclaim_run_id"), table_name="runclaim")
    op.drop_table("runclaim")
    op.drop_index(op.f("ix_runevent_event_type"), table_name="runevent")
    op.drop_index(op.f("ix_runevent_sequence"), table_name="runevent")
    op.drop_index(op.f("ix_runevent_run_id"), table_name="runevent")
    op.drop_table("runevent")
    op.drop_index(op.f("ix_ratelimitcounter_window_start"), table_name="ratelimitcounter")
    op.drop_index(op.f("ix_ratelimitcounter_bucket"), table_name="ratelimitcounter")
    op.drop_index(op.f("ix_ratelimitcounter_run_id"), table_name="ratelimitcounter")
    op.drop_table("ratelimitcounter")
    op.drop_index(op.f("ix_flakyitemlog_item_id"), table_name="flakyitemlog")
    op.drop_index(op.f("ix_flakyitemlog_run_id"), table_name="flakyitemlog")
    op.drop_table("flakyitemlog")
    op.drop_index(op.f("ix_idempotencyrecord_key"), table_name="idempotencyrecord")
    op.drop_index(op.f("ix_idempotencyrecord_run_id"), table_name="idempotencyrecord")
    op.drop_table("idempotencyrecord")
    op.drop_table("runchallengestate")
    op.drop_index(op.f("ix_runviewtoken_token_hash"), table_name="runviewtoken")
    op.drop_index(op.f("ix_runviewtoken_run_id"), table_name="runviewtoken")
    op.drop_table("runviewtoken")
    op.drop_index(op.f("ix_runtoken_token_hash"), table_name="runtoken")
    op.drop_index(op.f("ix_runtoken_run_id"), table_name="runtoken")
    op.drop_table("runtoken")
    op.drop_table("run")

"""Full-agent foundation: runtime packages, campaigns, and episode metadata.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtimepackage",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("reproducibility", sa.String(), nullable=False),
        sa.Column("config_digest", sa.String(), nullable=False),
        sa.Column("artifact_digest", sa.String(), nullable=True),
        sa.Column("soul_digest", sa.String(), nullable=True),
        sa.Column("memory_config_digest", sa.String(), nullable=True),
        sa.Column("toolset_digest", sa.String(), nullable=True),
        sa.Column("orchestration_digest", sa.String(), nullable=True),
        sa.Column("recovery_digest", sa.String(), nullable=True),
        sa.Column("framework_name", sa.String(), nullable=True),
        sa.Column("framework_version", sa.String(), nullable=True),
        sa.Column("declared_models", sa.JSON(), nullable=True),
        sa.Column("public_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("quarantined_at", sa.DateTime(), nullable=True),
        sa.Column("quarantine_reason", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "name", "version", "config_digest", name="uq_runtime_package_version_config"
        ),
    )
    op.create_index(op.f("ix_runtimepackage_name"), "runtimepackage", ["name"])

    op.create_table(
        "campaign",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("runtime_package_id", sa.String(), nullable=False),
        sa.Column("challenge_id", sa.String(), nullable=False),
        sa.Column("challenge_version", sa.String(), nullable=False),
        sa.Column("agent_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("requested_profiles", sa.JSON(), nullable=True),
        sa.Column("seeds_per_profile", sa.Integer(), nullable=False),
        sa.Column("run_ids", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["runtime_package_id"], ["runtimepackage.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_campaign_challenge_id"), "campaign", ["challenge_id"])
    op.create_index(
        op.f("ix_campaign_runtime_package_id"), "campaign", ["runtime_package_id"]
    )

    with op.batch_alter_table("run") as batch_op:
        batch_op.add_column(sa.Column("runtime_package_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("campaign_id", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "episode_profile",
                sa.String(),
                nullable=False,
                # SQLAlchemy persists Enum member names by default.
                server_default=sa.text("'COLD'"),
            )
        )
        batch_op.add_column(sa.Column("scenario_seed_commitment", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("status_revision", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column(
                "credential_generation", sa.Integer(), nullable=False, server_default=sa.text("1")
            )
        )
        batch_op.add_column(sa.Column("virtual_time", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("wall_clock_budget_ms", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("tool_call_budget", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("tool_calls_used", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(sa.Column("cost_budget_usd", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("cost_used_usd", sa.Float(), nullable=False, server_default=sa.text("0.0"))
        )
        batch_op.create_foreign_key(
            "fk_run_runtime_package", "runtimepackage", ["runtime_package_id"], ["id"]
        )
        batch_op.create_foreign_key("fk_run_campaign", "campaign", ["campaign_id"], ["id"])

    op.create_index(op.f("ix_run_runtime_package_id"), "run", ["runtime_package_id"])
    op.create_index(op.f("ix_run_campaign_id"), "run", ["campaign_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_run_campaign_id"), table_name="run")
    op.drop_index(op.f("ix_run_runtime_package_id"), table_name="run")
    with op.batch_alter_table("run") as batch_op:
        batch_op.drop_constraint("fk_run_campaign", type_="foreignkey")
        batch_op.drop_constraint("fk_run_runtime_package", type_="foreignkey")
        batch_op.drop_column("cost_used_usd")
        batch_op.drop_column("cost_budget_usd")
        batch_op.drop_column("tool_calls_used")
        batch_op.drop_column("tool_call_budget")
        batch_op.drop_column("wall_clock_budget_ms")
        batch_op.drop_column("virtual_time")
        batch_op.drop_column("credential_generation")
        batch_op.drop_column("status_revision")
        batch_op.drop_column("scenario_seed_commitment")
        batch_op.drop_column("episode_profile")
        batch_op.drop_column("campaign_id")
        batch_op.drop_column("runtime_package_id")

    op.drop_index(op.f("ix_campaign_runtime_package_id"), table_name="campaign")
    op.drop_index(op.f("ix_campaign_challenge_id"), table_name="campaign")
    op.drop_table("campaign")
    op.drop_index(op.f("ix_runtimepackage_name"), table_name="runtimepackage")
    op.drop_table("runtimepackage")

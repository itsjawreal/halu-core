"""Interrupted-episode checkpoint and one-time resume protocol.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "episodecheckpoint",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("credential_generation", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(), nullable=False),
        sa.Column("last_acknowledged_sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_episodecheckpoint_run_id"),
        "episodecheckpoint",
        ["run_id"],
    )

    op.create_table(
        "episoderesumetoken",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("credential_generation", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_episoderesumetoken_run_id"),
        "episoderesumetoken",
        ["run_id"],
    )
    op.create_index(
        op.f("ix_episoderesumetoken_token_hash"),
        "episoderesumetoken",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_episoderesumetoken_token_hash"),
        table_name="episoderesumetoken",
    )
    op.drop_index(
        op.f("ix_episoderesumetoken_run_id"),
        table_name="episoderesumetoken",
    )
    op.drop_table("episoderesumetoken")
    op.drop_index(
        op.f("ix_episodecheckpoint_run_id"),
        table_name="episodecheckpoint",
    )
    op.drop_table("episodecheckpoint")

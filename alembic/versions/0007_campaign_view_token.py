"""Read-only campaign result credential.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campaignviewtoken",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("campaign_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_campaignviewtoken_campaign_id"),
        "campaignviewtoken",
        ["campaign_id"],
    )
    op.create_index(
        op.f("ix_campaignviewtoken_token_hash"),
        "campaignviewtoken",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_campaignviewtoken_token_hash"),
        table_name="campaignviewtoken",
    )
    op.drop_index(
        op.f("ix_campaignviewtoken_campaign_id"),
        table_name="campaignviewtoken",
    )
    op.drop_table("campaignviewtoken")

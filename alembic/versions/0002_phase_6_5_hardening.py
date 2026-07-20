"""Phase 6.5 hardening: view token expiry/revocation, and the generic
string-keyed rate-limit bucket table used for website-level limits.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Existing view tokens predate expiry; backfill them far enough in the
# future that they behave as "not yet expired" until whoever holds one
# revokes/rotates it. New rows always set a real value explicitly.
_BACKFILL_EXPIRES_AT = "2099-12-31 00:00:00"


def upgrade() -> None:
    op.add_column(
        "runviewtoken",
        sa.Column(
            "expires_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text(f"'{_BACKFILL_EXPIRES_AT}'"),
        ),
    )
    op.add_column("runviewtoken", sa.Column("revoked_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("runviewtoken") as batch_op:
        batch_op.alter_column("expires_at", server_default=None)

    op.create_table(
        "ratelimitbucket",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("bucket", sa.String(), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", "bucket", "window_start", name="uq_rate_limit_bucket_window"),
    )
    op.create_index(op.f("ix_ratelimitbucket_key"), "ratelimitbucket", ["key"])
    op.create_index(op.f("ix_ratelimitbucket_bucket"), "ratelimitbucket", ["bucket"])
    op.create_index(op.f("ix_ratelimitbucket_window_start"), "ratelimitbucket", ["window_start"])


def downgrade() -> None:
    op.drop_index(op.f("ix_ratelimitbucket_window_start"), table_name="ratelimitbucket")
    op.drop_index(op.f("ix_ratelimitbucket_bucket"), table_name="ratelimitbucket")
    op.drop_index(op.f("ix_ratelimitbucket_key"), table_name="ratelimitbucket")
    op.drop_table("ratelimitbucket")

    with op.batch_alter_table("runviewtoken") as batch_op:
        batch_op.drop_column("revoked_at")
        batch_op.drop_column("expires_at")

"""Phase 8 public alpha readiness: public result sharing, and a hashed
creator IP/fingerprint on Run for abuse protection (max active runs per IP).

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("run", sa.Column("creator_ip_hash", sa.String(), nullable=True))

    op.create_table(
        "runpublicshare",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("slug_hash", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column("rotated_from_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_runpublicshare_run_id"), "runpublicshare", ["run_id"])
    op.create_index(
        op.f("ix_runpublicshare_slug_hash"), "runpublicshare", ["slug_hash"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_runpublicshare_slug_hash"), table_name="runpublicshare")
    op.drop_index(op.f("ix_runpublicshare_run_id"), table_name="runpublicshare")
    op.drop_table("runpublicshare")

    with op.batch_alter_table("run") as batch_op:
        batch_op.drop_column("creator_ip_hash")

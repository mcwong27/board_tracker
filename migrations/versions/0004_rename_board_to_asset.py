"""Rename board/board_type to asset/asset_type so the tracker is generic.

Also drops the lab-specific seed types (Bora Lake, Sophia Lake, Other) when nothing
uses them, so a fresh install starts with no types and admins add their own.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_TYPES = ("Bora Lake", "Sophia Lake", "Other")


def upgrade() -> None:
    op.drop_index("uq_checkout_active_board", table_name="checkout")
    op.drop_index("ix_checkout_user_email", table_name="checkout")
    op.rename_table("board_type", "asset_type")
    op.rename_table("board", "asset")
    with op.batch_alter_table("checkout") as batch:
        batch.alter_column("board_id", new_column_name="asset_id")
    op.create_index(
        "uq_checkout_active_asset",
        "checkout",
        ["asset_id"],
        unique=True,
        sqlite_where=sa.text("returned_at IS NULL"),
    )
    op.create_index("ix_checkout_user_email", "checkout", ["user_email"])
    op.execute(
        sa.text(
            "DELETE FROM asset_type WHERE name IN :names AND id NOT IN (SELECT type_id FROM asset)"
        ).bindparams(sa.bindparam("names", value=SEED_TYPES, expanding=True))
    )


def downgrade() -> None:
    op.drop_index("ix_checkout_user_email", table_name="checkout")
    op.drop_index("uq_checkout_active_asset", table_name="checkout")
    with op.batch_alter_table("checkout") as batch:
        batch.alter_column("asset_id", new_column_name="board_id")
    op.rename_table("asset", "board")
    op.rename_table("asset_type", "board_type")
    op.create_index(
        "uq_checkout_active_board",
        "checkout",
        ["board_id"],
        unique=True,
        sqlite_where=sa.text("returned_at IS NULL"),
    )
    op.create_index("ix_checkout_user_email", "checkout", ["user_email"])

"""Initial schema: board types, boards, checkouts.

Revision ID: 0001
Revises:
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_TYPES = ["Sophia Lake", "Bora Lake", "FPGA", "Other"]


def upgrade() -> None:
    board_type = op.create_table(
        "board_type",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
    )
    op.create_table(
        "board",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("type_id", sa.Integer(), sa.ForeignKey("board_type.id"), nullable=False),
        sa.Column("serial", sa.String(200), nullable=False),
        sa.Column("chip_mounted", sa.String(200), nullable=False),
        sa.Column("location", sa.String(200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("retired", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "checkout",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("board_id", sa.Integer(), sa.ForeignKey("board.id"), nullable=False),
        sa.Column("user_email", sa.String(320), nullable=False),
        sa.Column("user_name", sa.String(200), nullable=False),
        sa.Column("checked_out_at", sa.DateTime(), nullable=False),
        sa.Column("returned_at", sa.DateTime(), nullable=True),
        sa.Column("returned_by", sa.String(320), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
    )
    op.create_index(
        "uq_checkout_active_board",
        "checkout",
        ["board_id"],
        unique=True,
        sqlite_where=sa.text("returned_at IS NULL"),
    )
    op.create_index("ix_checkout_user_email", "checkout", ["user_email"])
    op.bulk_insert(board_type, [{"name": n} for n in DEFAULT_TYPES])


def downgrade() -> None:
    op.drop_index("ix_checkout_user_email", table_name="checkout")
    op.drop_index("uq_checkout_active_board", table_name="checkout")
    op.drop_table("checkout")
    op.drop_table("board")
    op.drop_table("board_type")

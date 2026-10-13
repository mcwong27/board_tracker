"""Add fpga_reservation table for logging local FPGA use.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fpga_reservation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fpga_type", sa.String(100), nullable=False),
        sa.Column("project", sa.String(200), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("contact", sa.String(200), nullable=False),
        sa.Column("special_requests", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("created_by_email", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_fpga_reservation_dates", "fpga_reservation", ["start_date", "end_date"])


def downgrade() -> None:
    op.drop_index("ix_fpga_reservation_dates", table_name="fpga_reservation")
    op.drop_table("fpga_reservation")

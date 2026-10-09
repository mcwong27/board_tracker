"""Order board types (Bora Lake, Sophia Lake, Other) and drop the FPGA type.

Boards that were typed FPGA move to Other.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORDER = {"Bora Lake": 1, "Sophia Lake": 2, "Other": 1000}


def upgrade() -> None:
    with op.batch_alter_table("board_type") as batch:
        batch.add_column(
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100")
        )
    for name, position in ORDER.items():
        op.execute(
            sa.text("UPDATE board_type SET sort_order = :pos WHERE name = :name").bindparams(
                pos=position, name=name
            )
        )
    op.execute(
        "INSERT INTO board_type (name, sort_order) SELECT 'Other', 1000 "
        "WHERE NOT EXISTS (SELECT 1 FROM board_type WHERE name = 'Other')"
    )
    op.execute(
        "UPDATE board SET type_id = (SELECT id FROM board_type WHERE name = 'Other') "
        "WHERE type_id = (SELECT id FROM board_type WHERE name = 'FPGA')"
    )
    op.execute("DELETE FROM board_type WHERE name = 'FPGA'")


def downgrade() -> None:
    op.execute("INSERT INTO board_type (name, sort_order) VALUES ('FPGA', 100)")
    with op.batch_alter_table("board_type") as batch:
        batch.drop_column("sort_order")

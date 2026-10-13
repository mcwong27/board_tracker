"""Admin-managed FPGA types, servers, and per-server counts.

Reservations move from a free-text fpga_type string to a foreign key, and gain an
optional server so people can say which machine they need.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The models the lab has today; admins add more from the FPGA admin page.
SEED_TYPES = ("U250", "XB10", "VCU118", "U200", "U280", "V80", "RHS Research Nitefury II")


def upgrade() -> None:
    fpga_type = op.create_table(
        "fpga_type",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
    )
    op.create_table(
        "fpga_server",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
    )
    op.create_table(
        "fpga_placement",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fpga_type_id", sa.Integer(), sa.ForeignKey("fpga_type.id"), nullable=False),
        sa.Column("server_id", sa.Integer(), sa.ForeignKey("fpga_server.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("fpga_type_id", "server_id", name="uq_fpga_placement_type_server"),
    )
    op.bulk_insert(fpga_type, [{"name": name} for name in SEED_TYPES])

    # Any type already used by a reservation but missing from the seed list.
    op.execute(
        "INSERT INTO fpga_type (name) SELECT DISTINCT fpga_type FROM fpga_reservation "
        "WHERE fpga_type NOT IN (SELECT name FROM fpga_type)"
    )
    with op.batch_alter_table("fpga_reservation") as batch:
        batch.add_column(sa.Column("fpga_type_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("server_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE fpga_reservation SET fpga_type_id = "
        "(SELECT id FROM fpga_type WHERE fpga_type.name = fpga_reservation.fpga_type)"
    )
    # Rebuild without the old string column and with the foreign keys in place.
    with op.batch_alter_table("fpga_reservation") as batch:
        batch.drop_column("fpga_type")
        batch.alter_column("fpga_type_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key("fk_fpga_reservation_type", "fpga_type", ["fpga_type_id"], ["id"])
        batch.create_foreign_key("fk_fpga_reservation_server", "fpga_server", ["server_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("fpga_reservation") as batch:
        batch.add_column(sa.Column("fpga_type", sa.String(100), nullable=True))
    op.execute(
        "UPDATE fpga_reservation SET fpga_type = "
        "(SELECT name FROM fpga_type WHERE fpga_type.id = fpga_reservation.fpga_type_id)"
    )
    with op.batch_alter_table("fpga_reservation") as batch:
        batch.drop_constraint("fk_fpga_reservation_server", type_="foreignkey")
        batch.drop_constraint("fk_fpga_reservation_type", type_="foreignkey")
        batch.drop_column("server_id")
        batch.drop_column("fpga_type_id")
        batch.alter_column("fpga_type", existing_type=sa.String(100), nullable=False)
    op.drop_table("fpga_placement")
    op.drop_table("fpga_server")
    op.drop_table("fpga_type")

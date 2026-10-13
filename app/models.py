"""Database models."""

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite has no timezone support)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class AssetType(Base):
    __tablename__ = "asset_type"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    # Admins can order types by hand; equal values fall back to alphabetical.
    sort_order: Mapped[int] = mapped_column(Integer, default=100, server_default="100")

    assets: Mapped[list["Asset"]] = relationship(back_populates="type")


class Asset(Base):
    __tablename__ = "asset"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    type_id: Mapped[int] = mapped_column(ForeignKey("asset_type.id"))
    serial: Mapped[str] = mapped_column(String(200), default="")
    chip_mounted: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    retired: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    type: Mapped[AssetType] = relationship(back_populates="assets")
    checkouts: Mapped[list["Checkout"]] = relationship(
        back_populates="asset", order_by="Checkout.checked_out_at.desc()"
    )


class Checkout(Base):
    __tablename__ = "checkout"
    __table_args__ = (
        # At most one active (unreturned) checkout per asset, enforced by the database.
        Index(
            "uq_checkout_active_asset",
            "asset_id",
            unique=True,
            sqlite_where=text("returned_at IS NULL"),
        ),
        Index("ix_checkout_user_email", "user_email"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"))
    user_email: Mapped[str] = mapped_column(String(320))
    user_name: Mapped[str] = mapped_column(String(200), default="")
    checked_out_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    returned_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    asset: Mapped[Asset] = relationship(back_populates="checkouts")

    @property
    def active(self) -> bool:
        return self.returned_at is None


class FpgaType(Base):
    """A model of FPGA the lab owns, e.g. U250. Admins manage the list."""

    __tablename__ = "fpga_type"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)

    placements: Mapped[list["FpgaPlacement"]] = relationship(
        back_populates="fpga_type", cascade="all, delete-orphan"
    )


class FpgaServer(Base):
    """A machine FPGAs are installed in, e.g. rack2-srv1."""

    __tablename__ = "fpga_server"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    placements: Mapped[list["FpgaPlacement"]] = relationship(
        back_populates="server", cascade="all, delete-orphan"
    )


class FpgaPlacement(Base):
    """How many FPGAs of one type are installed in one server."""

    __tablename__ = "fpga_placement"
    __table_args__ = (
        UniqueConstraint("fpga_type_id", "server_id", name="uq_fpga_placement_type_server"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fpga_type_id: Mapped[int] = mapped_column(ForeignKey("fpga_type.id"))
    server_id: Mapped[int] = mapped_column(ForeignKey("fpga_server.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=0)

    fpga_type: Mapped[FpgaType] = relationship(back_populates="placements")
    server: Mapped[FpgaServer] = relationship(back_populates="placements")


class FpgaReservation(Base):
    """A logged stretch of local FPGA use: not tied to a specific named asset."""

    __tablename__ = "fpga_reservation"
    __table_args__ = (Index("ix_fpga_reservation_dates", "start_date", "end_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fpga_type_id: Mapped[int] = mapped_column(ForeignKey("fpga_type.id"))
    # Optional: a reservation can be "any server" until someone decides where it runs.
    server_id: Mapped[int | None] = mapped_column(ForeignKey("fpga_server.id"), nullable=True)
    project: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    contact: Mapped[str] = mapped_column(String(200), default="")
    special_requests: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    created_by_email: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    fpga_type: Mapped[FpgaType] = relationship()
    server: Mapped[FpgaServer | None] = relationship()

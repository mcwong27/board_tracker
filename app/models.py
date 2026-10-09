"""Database models."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite has no timezone support)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class BoardType(Base):
    __tablename__ = "board_type"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)

    boards: Mapped[list["Board"]] = relationship(back_populates="type")


class Board(Base):
    __tablename__ = "board"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    type_id: Mapped[int] = mapped_column(ForeignKey("board_type.id"))
    serial: Mapped[str] = mapped_column(String(200), default="")
    chip_mounted: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    retired: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    type: Mapped[BoardType] = relationship(back_populates="boards")
    checkouts: Mapped[list["Checkout"]] = relationship(
        back_populates="board", order_by="Checkout.checked_out_at.desc()"
    )


class Checkout(Base):
    __tablename__ = "checkout"
    __table_args__ = (
        # At most one active (unreturned) checkout per board, enforced by the database.
        Index(
            "uq_checkout_active_board",
            "board_id",
            unique=True,
            sqlite_where=text("returned_at IS NULL"),
        ),
        Index("ix_checkout_user_email", "user_email"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("board.id"))
    user_email: Mapped[str] = mapped_column(String(320))
    user_name: Mapped[str] = mapped_column(String(200), default="")
    checked_out_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    returned_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    board: Mapped[Board] = relationship(back_populates="checkouts")

    @property
    def active(self) -> bool:
        return self.returned_at is None

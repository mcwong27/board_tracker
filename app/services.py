"""Business rules for boards and checkouts. Routes stay thin and call these."""

from sqlalchemy import and_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth import User
from app.models import Board, BoardType, Checkout, utcnow


class ServiceError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class Conflict(ServiceError):
    status_code = 409


class Forbidden(ServiceError):
    status_code = 403


def board_types(db: Session) -> list[BoardType]:
    return list(db.scalars(select(BoardType).order_by(BoardType.name)))


def boards_with_status(
    db: Session, *, type_id: int | None = None, include_retired: bool = False
) -> list[tuple[Board, Checkout | None]]:
    """Boards paired with their active checkout (None when available)."""
    stmt = (
        select(Board, Checkout)
        .join(Board.type)
        .outerjoin(Checkout, and_(Checkout.board_id == Board.id, Checkout.returned_at.is_(None)))
        .options(joinedload(Board.type))
        .order_by(BoardType.name, Board.name)
    )
    if not include_retired:
        stmt = stmt.where(Board.retired.is_(False))
    if type_id is not None:
        stmt = stmt.where(Board.type_id == type_id)
    return [(board, checkout) for board, checkout in db.execute(stmt)]


def active_checkout(db: Session, board_id: int) -> Checkout | None:
    return db.scalar(
        select(Checkout).where(Checkout.board_id == board_id, Checkout.returned_at.is_(None))
    )


def user_checkouts(db: Session, email: str) -> list[Checkout]:
    return list(
        db.scalars(
            select(Checkout)
            .where(Checkout.user_email == email)
            .options(joinedload(Checkout.board).joinedload(Board.type))
            .order_by(Checkout.checked_out_at.desc())
        )
    )


def checkout_board(db: Session, board: Board, user: User, notes: str = "") -> Checkout:
    if board.retired:
        raise Conflict(f"{board.name} is retired and can't be checked out.")
    checkout = Checkout(
        board_id=board.id, user_email=user.email, user_name=user.name, notes=notes.strip()
    )
    db.add(checkout)
    try:
        db.commit()
    except IntegrityError:
        # The partial unique index rejected a second active checkout (possibly a race).
        db.rollback()
        holder = active_checkout(db, board.id)
        who = f" by {holder.user_name or holder.user_email}" if holder else ""
        raise Conflict(f"{board.name} is already checked out{who}.") from None
    return checkout


def return_board(db: Session, board: Board, user: User) -> Checkout:
    """Return a board. Only the holder or an admin may do this."""
    checkout = active_checkout(db, board.id)
    if checkout is None:
        raise Conflict(f"{board.name} isn't checked out.")
    if checkout.user_email != user.email and not user.is_admin:
        raise Forbidden("Only the person who has this board or an admin can return it.")
    now = utcnow()
    # Conditional update so two simultaneous returns can't both succeed.
    result = db.execute(
        update(Checkout)
        .where(Checkout.id == checkout.id, Checkout.returned_at.is_(None))
        .values(returned_at=now, returned_by=user.email)
    )
    if result.rowcount != 1:
        db.rollback()
        raise Conflict(f"{board.name} was already returned.")
    db.commit()
    db.refresh(checkout)
    return checkout

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Board, BoardType, Checkout, utcnow


def make_board(db, name="SL-01") -> Board:
    board_type = db.scalar(select(BoardType).where(BoardType.name == "Sophia Lake"))
    board = Board(name=name, type=board_type)
    db.add(board)
    db.commit()
    return board


def test_migration_seeds_default_types(db):
    names = set(db.scalars(select(BoardType.name)))
    assert names == {"Sophia Lake", "Bora Lake", "FPGA", "Other"}


def test_db_rejects_second_active_checkout(db):
    """The partial unique index blocks double checkout even if app code is bypassed."""
    board = make_board(db)
    db.add(Checkout(board=board, user_email="a@berkeley.edu"))
    db.commit()
    db.add(Checkout(board=board, user_email="b@berkeley.edu"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_returned_checkouts_do_not_block_new_one(db):
    board = make_board(db)
    db.add(Checkout(board=board, user_email="a@berkeley.edu", returned_at=utcnow()))
    db.add(Checkout(board=board, user_email="b@berkeley.edu", returned_at=utcnow()))
    db.add(Checkout(board=board, user_email="c@berkeley.edu"))
    db.commit()
    assert len(board.checkouts) == 3

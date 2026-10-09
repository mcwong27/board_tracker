import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.db import make_engine
from app.migrate import ALEMBIC_INI
from app.models import Board, BoardType, Checkout, utcnow
from app.services import add_board_type, board_types


def make_board(db, name="SL-01") -> Board:
    board_type = db.scalar(select(BoardType).where(BoardType.name == "Sophia Lake"))
    board = Board(name=name, type=board_type)
    db.add(board)
    db.commit()
    return board


def test_default_types_in_display_order(db):
    assert [t.name for t in board_types(db)] == ["Bora Lake", "Sophia Lake", "Other"]


def test_admin_added_types_sort_before_other(db):
    add_board_type(db, "Zynq")
    add_board_type(db, "Arty")
    names = [t.name for t in board_types(db)]
    assert names == ["Bora Lake", "Sophia Lake", "Arty", "Zynq", "Other"]


def test_fpga_boards_move_to_other(tmp_path):
    """Upgrading a DB that has FPGA boards reassigns them to Other."""
    path = str(tmp_path / "old.db")
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["database_path"] = path
    command.upgrade(cfg, "0001")
    engine = make_engine(path)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO board (name, type_id, serial, chip_mounted, location, notes, "
                "retired, created_at) SELECT 'DE10', id, '', '', '', '', 0, '2026-01-01' "
                "FROM board_type WHERE name = 'FPGA'"
            )
        )
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert (
            conn.scalar(text("SELECT t.name FROM board b JOIN board_type t ON t.id = b.type_id"))
            == "Other"
        )
        assert conn.scalar(text("SELECT count(*) FROM board_type WHERE name='FPGA'")) == 0
    engine.dispose()


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

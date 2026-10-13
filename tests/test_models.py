import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import make_engine
from app.migrate import ALEMBIC_INI
from app.models import Asset, Checkout, utcnow
from app.services import add_asset_type, asset_types
from tests.conftest import make_type


def make_asset(db, name="SL-01") -> Asset:
    asset = Asset(name=name, type=make_type(db, f"type-for-{name}"))
    db.add(asset)
    db.commit()
    return asset


def test_fresh_database_has_no_asset_types(db):
    """The tracker is generic: admins add whatever types they track."""
    assert asset_types(db) == []


def test_types_are_listed_alphabetically(db):
    add_asset_type(db, "Zynq")
    add_asset_type(db, "Arty")
    add_asset_type(db, "Oscilloscope")
    assert [t.name for t in asset_types(db)] == ["Arty", "Oscilloscope", "Zynq"]


def test_upgrade_renames_boards_to_assets_and_keeps_data(tmp_path):
    """An existing deployment's boards, types, and checkouts survive the rename."""
    path = str(tmp_path / "old.db")
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["database_path"] = path
    command.upgrade(cfg, "0001")  # board/board_type era
    engine = make_engine(path)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO board (name, type_id, serial, chip_mounted, location, notes, "
                "retired, created_at) SELECT 'DE10', id, '', '', '', '', 0, '2026-01-01' "
                "FROM board_type WHERE name = 'FPGA'"
            )
        )
        conn.execute(
            text(
                "INSERT INTO checkout (board_id, user_email, user_name, checked_out_at, notes) "
                "SELECT id, 'oski@berkeley.edu', 'Oski', '2026-02-02', 'lab 3' "
                "FROM board WHERE name = 'DE10'"
            )
        )
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        # 0002 moved FPGA-typed boards to Other; 0004 renamed the tables around them.
        assert (
            conn.scalar(text("SELECT t.name FROM asset a JOIN asset_type t ON t.id = a.type_id"))
            == "Other"
        )
        assert conn.scalar(text("SELECT count(*) FROM asset_type WHERE name='FPGA'")) == 0
        assert conn.scalar(text("SELECT user_email FROM checkout")) == "oski@berkeley.edu"
        # Unused seed types are gone; the one an asset still uses stays.
        assert conn.scalars(text("SELECT name FROM asset_type")).all() == ["Other"]
    engine.dispose()


def test_db_rejects_second_active_checkout(db):
    """The partial unique index blocks double checkout even if app code is bypassed."""
    asset = make_asset(db)
    db.add(Checkout(asset=asset, user_email="a@berkeley.edu"))
    db.commit()
    db.add(Checkout(asset=asset, user_email="b@berkeley.edu"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_returned_checkouts_do_not_block_new_one(db):
    asset = make_asset(db)
    db.add(Checkout(asset=asset, user_email="a@berkeley.edu", returned_at=utcnow()))
    db.add(Checkout(asset=asset, user_email="b@berkeley.edu", returned_at=utcnow()))
    db.add(Checkout(asset=asset, user_email="c@berkeley.edu"))
    db.commit()
    assert len(asset.checkouts) == 3

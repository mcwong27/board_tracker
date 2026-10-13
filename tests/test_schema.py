"""Schema-level guarantees, enforced by the database rather than by app code.

The same SQL runs on D1 in production, so these hold there too.
"""

import pytest

from app.db import UniqueViolation
from app.models import SEEDED_FPGA_TYPES
from app.services import add_asset_type, asset_types
from tests.conftest import make_type, query, run, value


def make_asset(db, name="SL-01") -> dict:
    asset_type = make_type(db, f"type-for-{name}")
    run(
        db.execute(
            "INSERT INTO asset (name, type_id, created_at) VALUES (?, ?, '2026-01-01 00:00:00')",
            (name, asset_type["id"]),
        )
    )
    return run(db.query_one("SELECT * FROM asset WHERE name = ?", (name,)))


def check_out(db, asset_id: int, email: str, returned_at: str | None = None):
    run(
        db.execute(
            "INSERT INTO checkout (asset_id, user_email, checked_out_at, returned_at)"
            " VALUES (?, ?, '2026-01-01 00:00:00', ?)",
            (asset_id, email, returned_at),
        )
    )


def test_fresh_database_has_no_asset_types(db):
    """The tracker is generic: admins add whatever types they track."""
    assert run(asset_types(db)) == []


def test_fpga_types_are_seeded_by_the_migration(db):
    names = [row["name"] for row in query(db, "SELECT name FROM fpga_type")]
    assert set(names) == set(SEEDED_FPGA_TYPES)


def test_types_are_listed_alphabetically(db):
    for name in ("Zynq", "Arty", "Oscilloscope"):
        run(add_asset_type(db, name))
    assert [t["name"] for t in run(asset_types(db))] == ["Arty", "Oscilloscope", "Zynq"]


def test_db_rejects_second_active_checkout(db):
    """The partial unique index blocks double checkout even if app code is bypassed."""
    asset = make_asset(db)
    check_out(db, asset["id"], "a@berkeley.edu")
    with pytest.raises(UniqueViolation):
        check_out(db, asset["id"], "b@berkeley.edu")


def test_returned_checkouts_do_not_block_new_one(db):
    asset = make_asset(db)
    check_out(db, asset["id"], "a@berkeley.edu", returned_at="2026-01-02 00:00:00")
    check_out(db, asset["id"], "b@berkeley.edu", returned_at="2026-01-03 00:00:00")
    check_out(db, asset["id"], "c@berkeley.edu")
    assert value(db, "SELECT COUNT(*) FROM checkout WHERE asset_id = ?", (asset["id"],)) == 3


def test_asset_names_are_unique(db):
    asset = make_asset(db, "BL-01")
    with pytest.raises(UniqueViolation):
        run(
            db.execute(
                "INSERT INTO asset (name, type_id, created_at)"
                " VALUES ('BL-01', ?, '2026-01-01 00:00:00')",
                (asset["type_id"],),
            )
        )


def test_one_placement_row_per_type_and_server(db):
    run(db.execute("INSERT INTO fpga_server (name) VALUES ('rack2-srv1')"))
    type_id = value(db, "SELECT id FROM fpga_type WHERE name = 'U250'")
    server_id = value(db, "SELECT id FROM fpga_server")
    run(
        db.execute(
            "INSERT INTO fpga_placement (fpga_type_id, server_id, quantity) VALUES (?, ?, 4)",
            (type_id, server_id),
        )
    )
    with pytest.raises(UniqueViolation):
        run(
            db.execute(
                "INSERT INTO fpga_placement (fpga_type_id, server_id, quantity) VALUES (?, ?, 9)",
                (type_id, server_id),
            )
        )

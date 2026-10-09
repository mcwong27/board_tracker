import csv
import io

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.models import Board, BoardType, Checkout
from app.routes.admin import router as admin_router
from tests.conftest import ADMIN, csrf_from, login, post


def admin_routes():
    for route in admin_router.routes:
        assert isinstance(route, APIRoute) and route.path.startswith("/admin")
        for method in route.methods:
            yield method, route.path.replace("{board_id}", "1")


@pytest.fixture
def board(db) -> Board:
    board_type = db.scalar(select(BoardType).where(BoardType.name == "Sophia Lake"))
    board = Board(name="SL-01", type=board_type, serial="S123")
    db.add(board)
    db.commit()
    return board


def type_id(db, name):
    return db.scalar(select(BoardType.id).where(BoardType.name == name))


def test_admin_routes_require_admin(client, board):
    routes = list(admin_routes())
    assert len(routes) >= 10  # catches routes accidentally moved off the admin router

    for method, url in routes:  # signed out: sent to login
        assert client.request(method, url).status_code == 303, url

    login(client, "oski@berkeley.edu")
    token = csrf_from(client, "/")
    for method, url in routes:
        data = {"csrf_token": token} if method == "POST" else None
        resp = client.request(method, url, data=data)
        assert resp.status_code == 403, f"{method} {url}"
    assert 'href="/admin"' not in client.get("/").text


def test_admin_can_open_every_get_route(client, board):
    login(client, ADMIN)
    for method, url in admin_routes():
        if method == "GET":
            assert client.get(url).status_code == 200, url


def test_add_and_edit_board(client, db):
    login(client, ADMIN)
    fields = {"name": "BL-01", "type_id": type_id(db, "Bora Lake"), "chip_mounted": "Agilex 7"}
    resp = post(client, "/admin/boards/new", fields, page="/admin/boards/new")
    assert resp.status_code == 303
    board = db.scalar(select(Board).where(Board.name == "BL-01"))
    assert board.chip_mounted == "Agilex 7"

    edit = {**fields, "name": "BL-01a", "location": "Cory 125"}
    resp = post(client, f"/admin/boards/{board.id}/edit", edit, page="/admin")
    assert resp.status_code == 303
    db.refresh(board)
    assert (board.name, board.location) == ("BL-01a", "Cory 125")


def test_board_validation(client, db, board):
    login(client, ADMIN)
    dup = {"name": "SL-01", "type_id": type_id(db, "Other")}
    resp = post(client, "/admin/boards/new", dup, page="/admin")
    assert resp.status_code == 409
    assert "already exists" in resp.text
    assert post(client, "/admin/boards/new", {"name": "x", "type_id": "999"}).status_code == 400
    assert post(client, "/admin/boards/new", {"name": " ", "type_id": "1"}).status_code == 400


def test_add_type(client, db):
    login(client, ADMIN)
    assert post(client, "/admin/types", {"name": "Zynq"}).status_code == 303
    assert type_id(db, "Zynq") is not None
    assert post(client, "/admin/types", {"name": "Zynq"}).status_code == 409


def test_retire_blocked_while_checked_out(client, db, board):
    db.add(Checkout(board_id=board.id, user_email="oski@berkeley.edu"))
    db.commit()
    login(client, ADMIN)
    resp = post(client, f"/admin/boards/{board.id}/retire")
    assert resp.status_code == 409
    db.refresh(board)
    assert not board.retired

    # Force-return, then retire and restore.
    assert post(client, f"/boards/{board.id}/return").status_code == 303
    assert post(client, f"/admin/boards/{board.id}/retire").status_code == 303
    db.refresh(board)
    assert board.retired
    assert post(client, f"/admin/boards/{board.id}/unretire").status_code == 303
    db.refresh(board)
    assert not board.retired


def read_csv(resp):
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    return list(csv.DictReader(io.StringIO(resp.text)))


def test_csv_exports(client, db, board):
    login(client, "oski@berkeley.edu", "Oski")
    post(client, f"/boards/{board.id}/checkout", {"notes": '=HYPERLINK("http://x")'})
    login(client, ADMIN)

    [row] = read_csv(client.get("/admin/export/boards.csv"))
    assert row["name"] == "SL-01"
    assert row["status"] == "checked out"
    assert row["holder_email"] == "oski@berkeley.edu"
    assert row["checked_out_at"].endswith("Z")

    [row] = read_csv(client.get("/admin/export/checkouts.csv"))
    assert row["board_name"] == "SL-01"
    assert row["user_name"] == "Oski"
    assert row["returned_at"] == ""
    assert row["notes"].startswith("'=")  # formula injection neutralized

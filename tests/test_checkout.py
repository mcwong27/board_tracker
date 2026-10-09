import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Board, BoardType, Checkout
from tests.conftest import ADMIN, login, post


@pytest.fixture
def board_id(db) -> int:
    board_type = db.scalar(select(BoardType).where(BoardType.name == "Bora Lake"))
    board = Board(name="BL-07", type=board_type, chip_mounted="Agilex 7")
    db.add(board)
    db.commit()
    return board.id


def other_client(app, email):
    c = TestClient(app, follow_redirects=False)
    login(c, email)
    return c


def active_checkouts(db, board_id):
    db.expire_all()
    return list(
        db.scalars(
            select(Checkout).where(Checkout.board_id == board_id, Checkout.returned_at.is_(None))
        )
    )


def test_checkout_and_return(client, db, board_id):
    login(client, "oski@berkeley.edu", "Oski Bear")
    resp = post(client, f"/boards/{board_id}/checkout", {"notes": "lab 3"})
    assert resp.status_code == 303
    [checkout] = active_checkouts(db, board_id)
    assert (checkout.user_email, checkout.user_name, checkout.notes) == (
        "oski@berkeley.edu",
        "Oski Bear",
        "lab 3",
    )
    page = client.get("/").text
    assert "Oski Bear" in page and "Checked out" in page
    assert "BL-07" in client.get("/me").text
    assert ">Return</button>" in client.get(f"/boards/{board_id}").text

    assert post(client, f"/boards/{board_id}/return").status_code == 303
    assert active_checkouts(db, board_id) == []
    assert "Never checked out" not in client.get(f"/boards/{board_id}").text


def test_no_double_checkout(app, client, db, board_id):
    login(client, "oski@berkeley.edu")
    assert post(client, f"/boards/{board_id}/checkout").status_code == 303

    # Same user again, and a different user, both get a conflict.
    resp = post(client, f"/boards/{board_id}/checkout")
    assert resp.status_code == 409
    with other_client(app, "rival@berkeley.edu") as rival:
        resp = post(rival, f"/boards/{board_id}/checkout")
        assert resp.status_code == 409
        assert "already checked out" in resp.text
    assert len(active_checkouts(db, board_id)) == 1


def test_only_holder_or_admin_can_return(app, client, db, board_id):
    login(client, "oski@berkeley.edu")
    post(client, f"/boards/{board_id}/checkout")

    with other_client(app, "rival@berkeley.edu") as rival:
        resp = post(rival, f"/boards/{board_id}/return")
        assert resp.status_code == 403
        assert "Force return" not in rival.get("/").text
    assert len(active_checkouts(db, board_id)) == 1

    with other_client(app, ADMIN) as admin:
        assert "Force return" in admin.get("/").text
        assert post(admin, f"/boards/{board_id}/return").status_code == 303
    assert active_checkouts(db, board_id) == []
    returned = db.scalar(select(Checkout).where(Checkout.board_id == board_id))
    assert returned.returned_by == ADMIN


def test_return_when_not_checked_out(client, board_id):
    login(client, "oski@berkeley.edu")
    assert post(client, f"/boards/{board_id}/return").status_code == 409


def test_retired_board_cannot_be_checked_out(client, db, board_id):
    db.get(Board, board_id).retired = True
    db.commit()
    login(client, "oski@berkeley.edu")
    assert "BL-07" not in client.get("/").text
    assert post(client, f"/boards/{board_id}/checkout").status_code == 409
    assert active_checkouts(db, board_id) == []


def test_dashboard_type_filter(client, db, board_id):
    fpga = db.scalar(select(BoardType).where(BoardType.name == "FPGA"))
    db.add(Board(name="DE10-Nano", type=fpga))
    db.commit()
    login(client, "oski@berkeley.edu")
    page = client.get(f"/?type={fpga.id}").text
    assert "DE10-Nano" in page and "BL-07" not in page
    page = client.get("/").text
    assert "DE10-Nano" in page and "BL-07" in page


def test_unknown_board_404(client):
    login(client, "oski@berkeley.edu")
    assert client.get("/boards/999").status_code == 404


def test_back_redirect_must_be_local(client, board_id):
    login(client, "oski@berkeley.edu")
    resp = post(client, f"/boards/{board_id}/checkout", {"back": "//evil.example"})
    assert resp.headers["location"] == "/"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Asset, Checkout
from tests.conftest import ADMIN, login, make_type, post


@pytest.fixture
def asset_id(db) -> int:
    asset = Asset(name="BL-07", type=make_type(db, "Bora Lake"), chip_mounted="Agilex 7")
    db.add(asset)
    db.commit()
    return asset.id


def other_client(app, email):
    c = TestClient(app, follow_redirects=False)
    login(c, email)
    return c


def active_checkouts(db, asset_id):
    db.expire_all()
    return list(
        db.scalars(
            select(Checkout).where(Checkout.asset_id == asset_id, Checkout.returned_at.is_(None))
        )
    )


def test_checkout_and_return(client, db, asset_id):
    login(client, "oski@berkeley.edu", "Oski Bear")
    resp = post(client, f"/assets/{asset_id}/checkout", {"notes": "lab 3"})
    assert resp.status_code == 303
    [checkout] = active_checkouts(db, asset_id)
    assert (checkout.user_email, checkout.user_name, checkout.notes) == (
        "oski@berkeley.edu",
        "Oski Bear",
        "lab 3",
    )
    page = client.get("/assets").text
    assert "Oski Bear" in page and "Checked out" in page
    assert "BL-07" in client.get("/").text  # the dashboard lists what you hold
    assert ">Return</button>" in client.get(f"/assets/{asset_id}").text

    assert post(client, f"/assets/{asset_id}/return").status_code == 303
    assert active_checkouts(db, asset_id) == []
    assert "Never checked out" not in client.get(f"/assets/{asset_id}").text


def test_no_double_checkout(app, client, db, asset_id):
    login(client, "oski@berkeley.edu")
    assert post(client, f"/assets/{asset_id}/checkout").status_code == 303

    # Same user again, and a different user, both get a conflict.
    resp = post(client, f"/assets/{asset_id}/checkout")
    assert resp.status_code == 409
    with other_client(app, "rival@berkeley.edu") as rival:
        resp = post(rival, f"/assets/{asset_id}/checkout")
        assert resp.status_code == 409
        assert "already checked out" in resp.text
    assert len(active_checkouts(db, asset_id)) == 1


def test_only_holder_or_admin_can_return(app, client, db, asset_id):
    login(client, "oski@berkeley.edu")
    post(client, f"/assets/{asset_id}/checkout")

    with other_client(app, "rival@berkeley.edu") as rival:
        resp = post(rival, f"/assets/{asset_id}/return")
        assert resp.status_code == 403
        assert "Force return" not in rival.get("/assets").text
    assert len(active_checkouts(db, asset_id)) == 1

    with other_client(app, ADMIN) as admin:
        assert "Force return" in admin.get("/assets").text
        assert post(admin, f"/assets/{asset_id}/return").status_code == 303
    assert active_checkouts(db, asset_id) == []
    returned = db.scalar(select(Checkout).where(Checkout.asset_id == asset_id))
    assert returned.returned_by == ADMIN


def test_return_when_not_checked_out(client, asset_id):
    login(client, "oski@berkeley.edu")
    assert post(client, f"/assets/{asset_id}/return").status_code == 409


def test_retired_asset_cannot_be_checked_out(client, db, asset_id):
    db.get(Asset, asset_id).retired = True
    db.commit()
    login(client, "oski@berkeley.edu")
    assert "BL-07" not in client.get("/").text
    assert post(client, f"/assets/{asset_id}/checkout").status_code == 409
    assert active_checkouts(db, asset_id) == []


def test_asset_overview_type_filter(client, db, asset_id):
    other = make_type(db, "Other")
    db.add(Asset(name="DE10-Nano", type=other))
    db.commit()
    login(client, "oski@berkeley.edu")
    page = client.get(f"/assets?type={other.id}").text
    assert "DE10-Nano" in page and "BL-07" not in page
    page = client.get("/assets").text
    assert "DE10-Nano" in page and "BL-07" in page


def test_unknown_asset_404(client):
    login(client, "oski@berkeley.edu")
    assert client.get("/assets/999").status_code == 404


def test_back_redirect_must_be_local(client, asset_id):
    login(client, "oski@berkeley.edu")
    resp = post(client, f"/assets/{asset_id}/checkout", {"back": "//evil.example"})
    assert resp.headers["location"] == "/"

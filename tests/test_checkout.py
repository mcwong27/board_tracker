import pytest
from fastapi.testclient import TestClient

from tests.conftest import ADMIN, login, make_type, post, query, query_one, run


@pytest.fixture
def asset_id(db) -> int:
    asset_type = make_type(db, "Bora Lake")
    run(
        db.execute(
            "INSERT INTO asset (name, type_id, chip_mounted, created_at)"
            " VALUES ('BL-07', ?, 'Agilex 7', '2026-01-01 00:00:00')",
            (asset_type["id"],),
        )
    )
    return query_one(db, "SELECT id FROM asset WHERE name = 'BL-07'")["id"]


def other_client(app, email):
    c = TestClient(app, follow_redirects=False)
    login(c, email)
    return c


def active_checkouts(db, asset_id):
    return query(
        db,
        "SELECT * FROM checkout WHERE asset_id = ? AND returned_at IS NULL",
        (asset_id,),
    )


def test_checkout_and_return(client, db, asset_id):
    login(client, "oski@berkeley.edu", "Oski Bear")
    resp = post(client, f"/assets/{asset_id}/checkout", {"notes": "lab 3"})
    assert resp.status_code == 303
    [checkout] = active_checkouts(db, asset_id)
    assert (checkout["user_email"], checkout["user_name"], checkout["notes"]) == (
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
    returned = query_one(db, "SELECT * FROM checkout WHERE asset_id = ?", (asset_id,))
    assert returned["returned_by"] == ADMIN


def test_return_when_not_checked_out(client, asset_id):
    login(client, "oski@berkeley.edu")
    assert post(client, f"/assets/{asset_id}/return").status_code == 409


def test_retired_asset_cannot_be_checked_out(client, db, asset_id):
    run(db.execute("UPDATE asset SET retired = 1 WHERE id = ?", (asset_id,)))
    login(client, "oski@berkeley.edu")
    assert "BL-07" not in client.get("/").text
    assert post(client, f"/assets/{asset_id}/checkout").status_code == 409
    assert active_checkouts(db, asset_id) == []


def test_asset_overview_type_filter(client, db, asset_id):
    other = make_type(db, "Other")
    run(
        db.execute(
            "INSERT INTO asset (name, type_id, created_at)"
            " VALUES ('DE10-Nano', ?, '2026-01-01 00:00:00')",
            (other["id"],),
        )
    )
    login(client, "oski@berkeley.edu")
    page = client.get(f"/assets?type={other['id']}").text
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

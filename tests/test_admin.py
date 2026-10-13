import csv
import io

import pytest
from fastapi.routing import APIRoute

from app.routes.admin import router as admin_router
from tests.conftest import ADMIN, csrf_from, login, make_type, post, query_one, run, value


def admin_routes():
    for route in admin_router.routes:
        assert isinstance(route, APIRoute) and route.path.startswith("/admin")
        for method in route.methods:
            yield method, route.path.replace("{asset_id}", "1")


@pytest.fixture
def asset(db) -> dict:
    asset_type = make_type(db, "Sophia Lake")
    run(
        db.execute(
            "INSERT INTO asset (name, type_id, serial, created_at)"
            " VALUES ('SL-01', ?, 'S123', '2026-01-01 00:00:00')",
            (asset_type["id"],),
        )
    )
    return query_one(db, "SELECT * FROM asset WHERE name = 'SL-01'")


def reload_asset(db, asset_id: int) -> dict:
    return query_one(db, "SELECT * FROM asset WHERE id = ?", (asset_id,))


def test_admin_routes_require_admin(client, asset):
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


def test_admin_can_open_every_get_route(client, asset):
    login(client, ADMIN)
    for method, url in admin_routes():
        if method == "GET":
            assert client.get(url).status_code == 200, url


def test_add_and_edit_asset(client, db):
    login(client, ADMIN)
    fields = {
        "name": "BL-01",
        "type_id": make_type(db, "Bora Lake")["id"],
        "chip_mounted": "Agilex 7",
    }
    resp = post(client, "/admin/assets/new", fields, page="/admin/assets/new")
    assert resp.status_code == 303
    asset = query_one(db, "SELECT * FROM asset WHERE name = 'BL-01'")
    assert asset["chip_mounted"] == "Agilex 7"

    edit = {**fields, "name": "BL-01a", "location": "Cory 125"}
    resp = post(client, f"/admin/assets/{asset['id']}/edit", edit, page="/admin")
    assert resp.status_code == 303
    asset = reload_asset(db, asset["id"])
    assert (asset["name"], asset["location"]) == ("BL-01a", "Cory 125")


def test_asset_validation(client, db, asset):
    login(client, ADMIN)
    dup = {"name": "SL-01", "type_id": asset["type_id"]}
    resp = post(client, "/admin/assets/new", dup, page="/admin")
    assert resp.status_code == 409
    assert "already exists" in resp.text
    assert post(client, "/admin/assets/new", {"name": "x", "type_id": "999"}).status_code == 400
    assert post(client, "/admin/assets/new", {"name": " ", "type_id": "1"}).status_code == 400


def test_add_type(client, db):
    login(client, ADMIN)
    assert post(client, "/admin/types", {"name": "Zynq"}).status_code == 303
    assert value(db, "SELECT id FROM asset_type WHERE name = 'Zynq'") is not None
    assert post(client, "/admin/types", {"name": "Zynq"}).status_code == 409


def test_retire_blocked_while_checked_out(client, db, asset):
    run(
        db.execute(
            "INSERT INTO checkout (asset_id, user_email, checked_out_at)"
            " VALUES (?, 'oski@berkeley.edu', '2026-01-01 00:00:00')",
            (asset["id"],),
        )
    )
    login(client, ADMIN)
    resp = post(client, f"/admin/assets/{asset['id']}/retire")
    assert resp.status_code == 409
    assert not reload_asset(db, asset["id"])["retired"]

    # Force-return, then retire and restore.
    assert post(client, f"/assets/{asset['id']}/return").status_code == 303
    assert post(client, f"/admin/assets/{asset['id']}/retire").status_code == 303
    assert reload_asset(db, asset["id"])["retired"]
    assert post(client, f"/admin/assets/{asset['id']}/unretire").status_code == 303
    assert not reload_asset(db, asset["id"])["retired"]


def read_csv(resp):
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    return list(csv.DictReader(io.StringIO(resp.text)))


def test_csv_exports(client, db, asset):
    login(client, "oski@berkeley.edu", "Oski")
    post(client, f"/assets/{asset['id']}/checkout", {"notes": '=HYPERLINK("http://x")'})
    login(client, ADMIN)

    [row] = read_csv(client.get("/admin/export/assets.csv"))
    assert row["name"] == "SL-01"
    assert row["status"] == "checked out"
    assert row["holder_email"] == "oski@berkeley.edu"
    assert row["checked_out_at"].endswith("Z")

    [row] = read_csv(client.get("/admin/export/checkouts.csv"))
    assert row["asset_name"] == "SL-01"
    assert row["user_name"] == "Oski"
    assert row["returned_at"] == ""
    assert row["notes"].startswith("'=")  # formula injection neutralized

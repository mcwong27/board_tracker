import csv
import io

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.models import Asset, AssetType, Checkout
from app.routes.admin import router as admin_router
from tests.conftest import ADMIN, csrf_from, login, make_type, post


def admin_routes():
    for route in admin_router.routes:
        assert isinstance(route, APIRoute) and route.path.startswith("/admin")
        for method in route.methods:
            yield method, route.path.replace("{asset_id}", "1")


@pytest.fixture
def asset(db) -> Asset:
    asset = Asset(name="SL-01", type=make_type(db, "Sophia Lake"), serial="S123")
    db.add(asset)
    db.commit()
    return asset


def type_id(db, name):
    return db.scalar(select(AssetType.id).where(AssetType.name == name))


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
    fields = {"name": "BL-01", "type_id": make_type(db, "Bora Lake").id, "chip_mounted": "Agilex 7"}
    resp = post(client, "/admin/assets/new", fields, page="/admin/assets/new")
    assert resp.status_code == 303
    asset = db.scalar(select(Asset).where(Asset.name == "BL-01"))
    assert asset.chip_mounted == "Agilex 7"

    edit = {**fields, "name": "BL-01a", "location": "Cory 125"}
    resp = post(client, f"/admin/assets/{asset.id}/edit", edit, page="/admin")
    assert resp.status_code == 303
    db.refresh(asset)
    assert (asset.name, asset.location) == ("BL-01a", "Cory 125")


def test_asset_validation(client, db, asset):
    login(client, ADMIN)
    dup = {"name": "SL-01", "type_id": asset.type_id}
    resp = post(client, "/admin/assets/new", dup, page="/admin")
    assert resp.status_code == 409
    assert "already exists" in resp.text
    assert post(client, "/admin/assets/new", {"name": "x", "type_id": "999"}).status_code == 400
    assert post(client, "/admin/assets/new", {"name": " ", "type_id": "1"}).status_code == 400


def test_add_type(client, db):
    login(client, ADMIN)
    assert post(client, "/admin/types", {"name": "Zynq"}).status_code == 303
    assert type_id(db, "Zynq") is not None
    assert post(client, "/admin/types", {"name": "Zynq"}).status_code == 409


def test_retire_blocked_while_checked_out(client, db, asset):
    db.add(Checkout(asset_id=asset.id, user_email="oski@berkeley.edu"))
    db.commit()
    login(client, ADMIN)
    resp = post(client, f"/admin/assets/{asset.id}/retire")
    assert resp.status_code == 409
    db.refresh(asset)
    assert not asset.retired

    # Force-return, then retire and restore.
    assert post(client, f"/assets/{asset.id}/return").status_code == 303
    assert post(client, f"/admin/assets/{asset.id}/retire").status_code == 303
    db.refresh(asset)
    assert asset.retired
    assert post(client, f"/admin/assets/{asset.id}/unretire").status_code == 303
    db.refresh(asset)
    assert not asset.retired


def read_csv(resp):
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    return list(csv.DictReader(io.StringIO(resp.text)))


def test_csv_exports(client, db, asset):
    login(client, "oski@berkeley.edu", "Oski")
    post(client, f"/assets/{asset.id}/checkout", {"notes": '=HYPERLINK("http://x")'})
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

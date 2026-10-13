"""Admin management of asset types and the FPGA types/servers/counts grid."""

from tests.conftest import ADMIN, csrf_from, login, make_type, post, query, query_one, run, value


def ids(db, table: str, name: str):
    return value(db, f"SELECT id FROM {table} WHERE name = ?", (name,))


def placements(db) -> dict:
    rows = query(db, "SELECT fpga_type_id, server_id, quantity FROM fpga_placement")
    return {(r["fpga_type_id"], r["server_id"]): r["quantity"] for r in rows}


# --- asset types ---------------------------------------------------------------


def test_rename_and_delete_asset_type(client, db):
    login(client, ADMIN)
    asset_type = make_type(db, "Oscilloscope")

    tid = asset_type["id"]
    resp = post(client, f"/admin/types/{tid}/rename", {"name": "Scope"}, page="/admin")
    assert resp.status_code == 303
    assert query_one(db, "SELECT * FROM asset_type WHERE id = ?", (tid,))["name"] == "Scope"

    resp = post(client, f"/admin/types/{tid}/delete", page="/admin")
    assert resp.status_code == 303
    assert query_one(db, "SELECT * FROM asset_type WHERE id = ?", (tid,)) is None


def test_type_in_use_cannot_be_deleted(client, db):
    login(client, ADMIN)
    asset_type = make_type(db, "Cable")
    run(
        db.execute(
            "INSERT INTO asset (name, type_id, created_at)"
            " VALUES ('HDMI-1', ?, '2026-01-01 00:00:00')",
            (asset_type["id"],),
        )
    )

    resp = post(client, f"/admin/types/{asset_type['id']}/delete", page="/admin")
    assert resp.status_code == 409
    assert "used by 1 asset" in resp.text
    assert query_one(db, "SELECT * FROM asset_type WHERE id = ?", (asset_type["id"],)) is not None


def test_rename_to_an_existing_name_is_rejected(client, db):
    login(client, ADMIN)
    make_type(db, "Alpha")
    beta = make_type(db, "Beta")
    resp = post(client, f"/admin/types/{beta['id']}/rename", {"name": "Alpha"}, page="/admin")
    assert resp.status_code == 409


# --- FPGA inventory ------------------------------------------------------------


def test_admin_can_add_fpga_type_and_server(client, db):
    login(client, ADMIN)
    assert post(client, "/admin/fpga/types", {"name": "Versal"}, page="/admin").status_code == 303
    assert ids(db, "fpga_type", "Versal") is not None
    assert post(client, "/admin/fpga/types", {"name": "Versal"}, page="/admin").status_code == 409

    srv = {"name": "rack2-srv1", "notes": "PCIe gen4"}
    assert post(client, "/admin/fpga/servers", srv, page="/admin").status_code == 303
    assert ids(db, "fpga_server", "rack2-srv1") is not None


def test_counts_grid_saves_and_clears_placements(client, db):
    login(client, ADMIN)
    post(client, "/admin/fpga/servers", {"name": "srv-a"}, page="/admin")
    post(client, "/admin/fpga/servers", {"name": "srv-b"}, page="/admin")
    u250 = ids(db, "fpga_type", "U250")
    a, b = ids(db, "fpga_server", "srv-a"), ids(db, "fpga_server", "srv-b")

    grid = {f"qty-{u250}-{a}": "4", f"qty-{u250}-{b}": "0"}
    assert post(client, "/admin/fpga/counts", grid, page="/admin").status_code == 303
    assert placements(db) == {(u250, a): 4}  # a zero stores nothing

    # Updating an existing cell, and zeroing it again removes the row.
    assert (
        post(client, "/admin/fpga/counts", {f"qty-{u250}-{a}": "2"}, page="/admin").status_code
        == 303
    )
    assert value(db, "SELECT quantity FROM fpga_placement") == 2
    assert (
        post(client, "/admin/fpga/counts", {f"qty-{u250}-{a}": "0"}, page="/admin").status_code
        == 303
    )
    assert placements(db) == {}


def test_counts_grid_rejects_junk(client, db):
    login(client, ADMIN)
    post(client, "/admin/fpga/servers", {"name": "srv-a"}, page="/admin")
    u250, a = ids(db, "fpga_type", "U250"), ids(db, "fpga_server", "srv-a")
    resp = post(client, "/admin/fpga/counts", {f"qty-{u250}-{a}": "lots"}, page="/admin")
    assert resp.status_code == 400
    assert placements(db) == {}


def test_fpga_type_in_use_cannot_be_deleted(client, db):
    login(client, ADMIN)
    post(client, "/admin/fpga/servers", {"name": "srv-a"}, page="/admin")
    u250, srv = ids(db, "fpga_type", "U250"), ids(db, "fpga_server", "srv-a")
    post(
        client,
        "/fpga/new",
        {
            "fpga_type_id": u250,
            "server_id": srv,
            "project": "P",
            "quantity": "1",
            "contact": "oski",
            "start_date": "2026-06-01",
            "end_date": "2026-06-02",
        },
        page="/fpga/new",
    )
    resp = post(client, f"/admin/fpga/types/{u250}/delete", page="/admin")
    assert resp.status_code == 409
    assert "used by 1 reservation" in resp.text


def test_deleting_a_server_removes_its_placements(client, db):
    login(client, ADMIN)
    post(client, "/admin/fpga/servers", {"name": "srv-a"}, page="/admin")
    u250, a = ids(db, "fpga_type", "U250"), ids(db, "fpga_server", "srv-a")
    post(client, "/admin/fpga/counts", {f"qty-{u250}-{a}": "3"}, page="/admin")

    assert post(client, f"/admin/fpga/servers/{a}/delete", page="/admin").status_code == 303
    assert placements(db) == {}


def test_non_admin_cannot_reach_fpga_admin(client):
    login(client, "oski@berkeley.edu")
    assert client.get("/admin").status_code == 403
    assert post(client, "/admin/fpga/types", {"name": "Nope"}, page="/fpga").status_code == 403


# --- asset CSV import ----------------------------------------------------------


def upload(client, csv_text: str, page: str = "/admin"):
    return client.post(
        "/admin/assets/import",
        data={"csrf_token": csrf_from(client, page)},
        files={"file": ("assets.csv", csv_text.encode(), "text/csv")},
    )


HEADER = "name,type,serial,chip_mounted,location,notes,retired\n"


def test_import_creates_assets_and_missing_types(client, db):
    login(client, ADMIN)
    resp = upload(client, HEADER + "BL-01,Bora Lake,S1,Agilex 7,Cory 125,spare,no\n")
    assert resp.status_code == 303

    asset = query_one(
        db,
        "SELECT a.*, t.name AS type_name FROM asset a JOIN asset_type t ON t.id = a.type_id"
        " WHERE a.name = 'BL-01'",
    )
    assert asset["type_name"] == "Bora Lake"
    assert (asset["serial"], asset["chip_mounted"], asset["location"]) == (
        "S1",
        "Agilex 7",
        "Cory 125",
    )
    assert asset["retired"] == 0


def test_import_updates_existing_assets_by_name(client, db):
    login(client, ADMIN)
    upload(client, HEADER + "BL-01,Bora Lake,S1,,,,no\n")
    upload(client, HEADER + "BL-01,Bora Lake,S2,,Soda 410,moved,yes\n")

    assets = query(db, "SELECT * FROM asset WHERE name = 'BL-01'")
    assert len(assets) == 1  # matched, not duplicated
    asset = assets[0]
    assert (asset["serial"], asset["location"], asset["retired"]) == ("S2", "Soda 410", 1)


def test_import_round_trips_the_export(client, db):
    """Download the assets CSV, upload it back, and nothing should change."""
    login(client, ADMIN)
    upload(client, HEADER + "BL-01,Bora Lake,S1,Agilex 7,Cory 125,=SUM(A1),no\n")
    exported = client.get("/admin/export/assets.csv").text

    resp = upload(client, exported)
    assert resp.status_code == 303
    [asset] = query(db, "SELECT * FROM asset")
    assert asset["name"] == "BL-01"
    assert asset["notes"] == "=SUM(A1)"  # the export's anti-formula quote is undone
    assert asset["location"] == "Cory 125"


def test_import_rejects_the_whole_file_on_a_bad_row(client, db):
    login(client, ADMIN)
    bad = HEADER + "Good-1,Bora Lake,,,,,no\n,Bora Lake,,,,,no\nGood-2,,,,,,no\n"
    resp = upload(client, bad)
    assert resp.status_code == 400
    assert "Row 3: name is required" in resp.text
    assert "Row 4: type is required" in resp.text
    assert query(db, "SELECT * FROM asset") == []  # nothing half-applied


def test_import_rejects_duplicate_names_within_the_file(client, db):
    login(client, ADMIN)
    resp = upload(client, HEADER + "BL-01,Bora Lake,,,,,no\nBL-01,Bora Lake,,,,,no\n")
    assert resp.status_code == 400
    assert "appears more than once" in resp.text
    assert query(db, "SELECT * FROM asset") == []


def test_import_rejects_a_bad_retired_value(client, db):
    login(client, ADMIN)
    resp = upload(client, HEADER + "BL-01,Bora Lake,,,,,maybe\n")
    assert resp.status_code == 400
    assert "retired should be yes or no" in resp.text


def test_import_rejects_a_file_without_the_required_columns(client, db):
    login(client, ADMIN)
    resp = upload(client, "nickname,colour\nBL-01,blue\n")
    assert resp.status_code == 400
    assert "missing the name, type column" in resp.text


def test_import_rejects_junk_and_empty_files(client, db):
    login(client, ADMIN)
    assert upload(client, "").status_code == 400
    assert upload(client, HEADER).status_code == 400  # header only
    resp = client.post(
        "/admin/assets/import",
        data={"csrf_token": csrf_from(client, "/admin")},
        files={"file": ("assets.csv", b"\xff\xfe\x00binary", "text/csv")},
    )
    assert resp.status_code == 400
    assert "UTF-8" in resp.text


def test_import_requires_admin(client):
    login(client, "oski@berkeley.edu")
    assert upload(client, HEADER + "X,Y,,,,,no\n", page="/").status_code == 403

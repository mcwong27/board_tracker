import re
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import FpgaPlacement, FpgaReservation, FpgaServer, FpgaType
from app.services import fpga_placements, oversubscribed
from tests.conftest import ADMIN, login, post

OSKI = "oski@berkeley.edu"


@pytest.fixture
def u250(db) -> FpgaType:
    return db.scalar(select(FpgaType).where(FpgaType.name == "U250"))


def a_server(db, name="rack2-srv1") -> FpgaServer:
    """Get or create a server, so fixtures and `fields()` can both ask for one."""
    srv = db.scalar(select(FpgaServer).where(FpgaServer.name == name))
    if srv is None:
        srv = FpgaServer(name=name)
        db.add(srv)
        db.commit()
    return srv


@pytest.fixture
def server(db) -> FpgaServer:
    return a_server(db)


def place(db, fpga_type, server, quantity):
    db.add(FpgaPlacement(fpga_type_id=fpga_type.id, server_id=server.id, quantity=quantity))
    db.commit()


def fields(db, **overrides) -> dict:
    fpga_type = db.scalar(select(FpgaType).where(FpgaType.name == "U250"))
    values = {
        "fpga_type_id": fpga_type.id,
        "server_id": a_server(db).id,
        "project": "Lab 4 demo",
        "quantity": "2",
        "contact": "oski",
        "special_requests": "requires QSFP between two FPGAs",
        "start_date": date.today().isoformat(),
        "end_date": (date.today() + timedelta(days=3)).isoformat(),
    }
    values.update(overrides)
    return values


def other_client(app, email):
    c = TestClient(app, follow_redirects=False)
    login(c, email)
    return c


def test_seeded_fpga_types_are_available(db):
    names = [t.name for t in db.scalars(select(FpgaType))]
    assert "U250" in names and "RHS Research Nitefury II" in names


def test_add_and_list_reservation(client, db, server):
    login(client, OSKI, "Oski")
    resp = post(client, "/fpga/new", fields(db, server_id=server.id), page="/fpga/new")
    assert resp.status_code == 303, resp.text

    reservation = db.scalar(select(FpgaReservation).where(FpgaReservation.project == "Lab 4 demo"))
    assert reservation.fpga_type.name == "U250"
    assert reservation.server.name == "rack2-srv1"
    assert reservation.quantity == 2
    assert reservation.created_by_email == OSKI

    page = client.get("/fpga").text
    assert "Lab 4 demo" in page and "U250" in page and "rack2-srv1" in page


def test_server_is_required(client, db):
    login(client, OSKI)
    resp = post(client, "/fpga/new", fields(db, server_id=""), page="/fpga/new")
    assert resp.status_code == 400
    assert "Pick a server" in resp.text
    assert db.scalars(select(FpgaReservation)).all() == []


def test_no_server_option_is_offered(client, db, server):
    login(client, OSKI)
    page = client.get("/fpga/new").text
    assert "No preference" not in page and "not decided" not in page
    assert 'name="server_id" required' in page


def test_validation_errors(client, db):
    login(client, OSKI)
    assert post(client, "/fpga/new", fields(db, fpga_type_id="999")).status_code == 400
    assert post(client, "/fpga/new", fields(db, fpga_type_id="")).status_code == 400
    assert post(client, "/fpga/new", fields(db, server_id="999")).status_code == 400
    assert post(client, "/fpga/new", fields(db, server_id="")).status_code == 400
    assert post(client, "/fpga/new", fields(db, project="")).status_code == 400
    assert post(client, "/fpga/new", fields(db, contact="")).status_code == 400
    assert post(client, "/fpga/new", fields(db, quantity="0")).status_code == 400
    assert post(client, "/fpga/new", fields(db, quantity="abc")).status_code == 400
    backwards = fields(db, start_date="2026-05-10", end_date="2026-05-01")
    assert post(client, "/fpga/new", backwards).status_code == 400


def test_only_creator_or_admin_can_edit_or_delete(app, client, db):
    login(client, OSKI)
    post(client, "/fpga/new", fields(db), page="/fpga/new")
    reservation_id = db.scalar(select(FpgaReservation)).id

    def still_exists() -> bool:
        db.expire_all()
        return (
            db.scalar(select(FpgaReservation).where(FpgaReservation.id == reservation_id))
            is not None
        )

    with other_client(app, "rival@berkeley.edu") as rival:
        assert rival.get(f"/fpga/{reservation_id}/edit").status_code == 403
        assert post(rival, f"/fpga/{reservation_id}/delete", page="/fpga").status_code == 403
        assert still_exists()

    with other_client(app, ADMIN) as admin:
        assert admin.get(f"/fpga/{reservation_id}/edit").status_code == 200
        assert post(admin, f"/fpga/{reservation_id}/delete", page="/fpga").status_code == 303

    assert not still_exists()


def test_creator_can_edit_own_reservation(client, db):
    login(client, OSKI)
    post(client, "/fpga/new", fields(db), page="/fpga/new")
    reservation = db.scalar(select(FpgaReservation))

    edit = fields(db, project="Lab 4 demo v2")
    resp = post(client, f"/fpga/{reservation.id}/edit", edit, page=f"/fpga/{reservation.id}/edit")
    assert resp.status_code == 303
    db.refresh(reservation)
    assert reservation.project == "Lab 4 demo v2"


def test_overlapping_bookings_land_on_different_boards(client, db, u250, server):
    place(db, u250, server, 2)
    login(client, OSKI)
    today = date.today()
    for project, offset in (("Alpha", 0), ("Bravo", 1)):  # overlap -> one board each
        post(
            client,
            "/fpga/new",
            fields(
                db,
                project=project,
                server_id=server.id,
                quantity="1",
                start_date=(today + timedelta(days=offset)).isoformat(),
                end_date=(today + timedelta(days=offset + 5)).isoformat(),
            ),
            page="/fpga/new",
        )
    page = client.get("/fpga").text
    assert "rack2-srv1 #1" in page and "rack2-srv1 #2" in page
    assert "Alpha" in page and "Bravo" in page
    assert "Over-subscribed" not in page  # two boards, two bookings: fits
    assert "XB10" in page  # types with nothing booked still get a row


def test_each_board_gets_its_own_hue(client, db, u250, server):
    place(db, u250, server, 3)
    login(client, OSKI)
    page = client.get("/fpga").text
    hues = re.findall(r"--hue: (\d+)", page)
    assert len(set(hues)) == 3, f"expected one hue per board, got {hues}"


def test_timeline_collapses_to_one_muxed_line_per_type(client, db, u250, server):
    place(db, u250, server, 2)
    login(client, OSKI)
    today = date.today()
    post(
        client,
        "/fpga/new",
        fields(
            db,
            server_id=server.id,
            quantity="2",
            start_date=today.isoformat(),
            end_date=(today + timedelta(days=2)).isoformat(),
        ),
        page="/fpga/new",
    )
    page = client.get("/fpga").text
    # Collapsed by default: a <details> per type, with a thin band per board.
    assert "<details" in page and "open" not in page.split("<details")[1][:40]
    assert page.count('class="mux-band"') >= 2
    assert page.count("timeline-bar thin") == 2  # the ×2 booking fills both boards


def test_a_booking_that_does_not_fit_goes_to_the_overflow_row(client, db, u250, server):
    place(db, u250, server, 1)
    login(client, OSKI)
    today = date.today()
    for project in ("Alpha", "Bravo"):
        post(
            client,
            "/fpga/new",
            fields(
                db,
                project=project,
                server_id=server.id,
                quantity="1",
                start_date=today.isoformat(),
                end_date=(today + timedelta(days=2)).isoformat(),
            ),
            page="/fpga/new",
        )
    page = client.get("/fpga").text
    assert "Over capacity" in page
    assert "Over-subscribed" in page


def test_overbooking_a_server_is_allowed_but_flagged(client, db, u250, server):
    place(db, u250, server, 2)
    login(client, OSKI)
    today = date.today()
    for project in ("Alpha", "Bravo"):  # 2 + 2 = 4 on a server that holds 2
        resp = post(
            client,
            "/fpga/new",
            fields(
                db,
                project=project,
                server_id=server.id,
                quantity="2",
                start_date=today.isoformat(),
                end_date=(today + timedelta(days=2)).isoformat(),
            ),
            page="/fpga/new",
        )
        assert resp.status_code == 303  # soft limit: saved anyway

    page = client.get("/fpga").text
    assert "Over-subscribed" in page
    assert "4 booked of 2 installed" in page
    assert "timeline-bar over" in page


def test_within_capacity_is_not_flagged(client, db, u250, server):
    place(db, u250, server, 4)
    login(client, OSKI)
    today = date.today()
    post(
        client,
        "/fpga/new",
        fields(
            db,
            server_id=server.id,
            quantity="2",
            start_date=today.isoformat(),
            end_date=(today + timedelta(days=2)).isoformat(),
        ),
        page="/fpga/new",
    )
    page = client.get("/fpga").text
    assert "Over-subscribed" not in page
    assert "timeline-bar over" not in page


def test_oversubscription_ignores_non_overlapping_dates(db, u250, server):
    place(db, u250, server, 1)
    day = date(2026, 6, 1)
    first = FpgaReservation(
        fpga_type_id=u250.id,
        server_id=server.id,
        project="A",
        quantity=1,
        start_date=day,
        end_date=day,
        created_by_email=OSKI,
    )
    second = FpgaReservation(
        fpga_type_id=u250.id,
        server_id=server.id,
        project="B",
        quantity=1,
        start_date=day + timedelta(days=1),
        end_date=day + timedelta(days=1),
        created_by_email=OSKI,
    )
    db.add_all([first, second])
    db.commit()
    flagged, warnings = oversubscribed([first, second], fpga_placements(db))
    assert flagged == set() and warnings == []


def test_legacy_reservation_without_a_server_is_never_flagged(db, u250):
    """New reservations must name a server, but rows predating servers may not have one."""
    r = FpgaReservation(
        fpga_type_id=u250.id,
        server_id=None,
        project="A",
        quantity=99,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        created_by_email=OSKI,
    )
    db.add(r)
    db.commit()
    flagged, warnings = oversubscribed([r], fpga_placements(db))
    assert flagged == set() and warnings == []


def test_booking_a_server_with_none_installed_is_flagged(db, u250, server):
    r = FpgaReservation(
        fpga_type_id=u250.id,
        server_id=server.id,
        project="A",
        quantity=1,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        created_by_email=OSKI,
    )
    db.add(r)
    db.commit()
    flagged, warnings = oversubscribed([r], fpga_placements(db))
    assert flagged == {r.id}
    assert "1 booked of 0 installed" in warnings[0]

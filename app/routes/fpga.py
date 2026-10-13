"""FPGA reservations: a timeline log of local FPGA use, open to any signed-in user."""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import services
from app.auth import CurrentUser
from app.csrf import verify_csrf
from app.db import get_db
from app.models import FpgaReservation
from app.templating import flash, render
from app.urls import redirect

router = APIRouter(prefix="/fpga")
DB = Annotated[Session, Depends(get_db)]

WINDOW_DAYS = 70  # ~10 weeks visible at once
PAGE_DAYS = 28  # how far Earlier/Later shift the window
DEFAULT_LOOKBACK = 7  # show a bit of recent history by default


def get_reservation(db: Session, reservation_id: int) -> FpgaReservation:
    reservation = db.get(FpgaReservation, reservation_id)
    if reservation is None:
        raise HTTPException(status_code=404)
    return reservation


def default_window_start() -> date:
    return date.today() - timedelta(days=DEFAULT_LOOKBACK)


def render_timeline(
    request: Request, db: Session, window_start: date, status_code: int = 200, error=None
):
    window_end = window_start + timedelta(days=WINDOW_DAYS - 1)
    data = services.fpga_timeline(db, window_start, window_end)
    return render(
        request,
        "fpga.html",
        status_code=status_code,
        error=error,
        groups=data["groups"],
        ticks=data["ticks"],
        today_pct=data["today_pct"],
        warnings=data["warnings"],
        window_start=window_start,
        window_end=window_end,
        prev_start=(window_start - timedelta(days=PAGE_DAYS)).isoformat(),
        next_start=(window_start + timedelta(days=PAGE_DAYS)).isoformat(),
        today_start=default_window_start().isoformat(),
        reservations=services.fpga_reservations(db),
    )


@router.get("", name="fpga_timeline")
def timeline(request: Request, user: CurrentUser, db: DB, start: str | None = None):
    try:
        window_start = date.fromisoformat(start) if start else default_window_start()
    except ValueError:
        window_start = default_window_start()
    return render_timeline(request, db, window_start)


def render_form(request: Request, db: Session, reservation, values, status_code=200, error=None):
    return render(
        request,
        "fpga_form.html",
        status_code=status_code,
        reservation=reservation,
        values=values,
        types=services.fpga_types(db),
        servers=services.fpga_servers(db),
        inventory=services.fpga_inventory_by_type(db),
        error=error,
    )


@router.get("/new", name="fpga_new")
def new_form(request: Request, user: CurrentUser, db: DB):
    today = date.today().isoformat()
    return render_form(request, db, None, {"start_date": today, "end_date": today, "quantity": "1"})


@router.post("/new", dependencies=[Depends(verify_csrf)])
async def create(request: Request, user: CurrentUser, db: DB):
    values = {f: str((await request.form()).get(f, "")) for f in services.FPGA_FIELDS}
    try:
        services.save_fpga_reservation(db, None, user, values)
    except services.ServiceError as exc:
        return render_form(request, db, None, values, exc.status_code, exc.message)
    flash(request, "Added FPGA reservation.")
    return redirect(request, "/fpga")


@router.get("/{reservation_id}/edit", name="fpga_edit")
def edit_form(request: Request, reservation_id: int, user: CurrentUser, db: DB):
    reservation = get_reservation(db, reservation_id)
    if reservation.created_by_email != user.email and not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Only the person who made this reservation or an admin can edit it.",
        )
    # server_id is optional, so None has to render as an empty select, not "None".
    values = {f: str(getattr(reservation, f) or "") for f in services.FPGA_FIELDS}
    return render_form(request, db, reservation, values)


@router.post("/{reservation_id}/edit", dependencies=[Depends(verify_csrf)])
async def update(request: Request, reservation_id: int, user: CurrentUser, db: DB):
    reservation = get_reservation(db, reservation_id)
    values = {f: str((await request.form()).get(f, "")) for f in services.FPGA_FIELDS}
    try:
        services.save_fpga_reservation(db, reservation, user, values)
    except services.ServiceError as exc:
        return render_form(request, db, reservation, values, exc.status_code, exc.message)
    flash(request, "Saved FPGA reservation.")
    return redirect(request, "/fpga")


@router.post("/{reservation_id}/delete", dependencies=[Depends(verify_csrf)])
def delete(request: Request, reservation_id: int, user: CurrentUser, db: DB):
    reservation = get_reservation(db, reservation_id)
    try:
        services.delete_fpga_reservation(db, reservation, user)
    except services.ServiceError as exc:
        return render_timeline(request, db, default_window_start(), exc.status_code, exc.message)
    flash(request, "Deleted FPGA reservation.")
    return redirect(request, "/fpga")

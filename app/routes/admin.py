"""Admin: manage boards and types, export CSV. Every route requires an admin."""

import csv
import io
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import services
from app.auth import require_admin
from app.csrf import verify_csrf
from app.db import get_db
from app.models import Board, utcnow
from app.templating import flash, render
from app.urls import redirect

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
DB = Annotated[Session, Depends(get_db)]


def get_board(db: Session, board_id: int) -> Board:
    board = db.get(Board, board_id)
    if board is None:
        raise HTTPException(status_code=404)
    return board


def render_index(request: Request, db: Session, status_code=200, error=None):
    return render(
        request,
        "admin/index.html",
        status_code=status_code,
        rows=services.boards_with_status(db, include_retired=True),
        types=services.board_types(db),
        error=error,
    )


def render_form(request: Request, db: Session, board, values, status_code=200, error=None):
    return render(
        request,
        "admin/board_form.html",
        status_code=status_code,
        board=board,
        values=values,
        types=services.board_types(db),
        error=error,
    )


def board_values(board: Board) -> dict[str, str]:
    return {f: str(getattr(board, f) or "") for f in services.BOARD_FIELDS}


@router.get("", name="admin")
def index(request: Request, db: DB):
    return render_index(request, db)


@router.get("/boards/new", name="admin_new_board")
def new_board_form(request: Request, db: DB):
    return render_form(request, db, None, {})


@router.post("/boards/new", dependencies=[Depends(verify_csrf)])
async def create_board(request: Request, db: DB):
    values = {f: str((await request.form()).get(f, "")) for f in services.BOARD_FIELDS}
    try:
        board = services.save_board(db, None, values)
    except services.ServiceError as exc:
        return render_form(request, db, None, values, exc.status_code, exc.message)
    flash(request, f"Added {board.name}.")
    return redirect(request, "/admin")


@router.get("/boards/{board_id}/edit", name="admin_edit_board")
def edit_board_form(request: Request, board_id: int, db: DB):
    board = get_board(db, board_id)
    return render_form(request, db, board, board_values(board))


@router.post("/boards/{board_id}/edit", dependencies=[Depends(verify_csrf)])
async def update_board(request: Request, board_id: int, db: DB):
    board = get_board(db, board_id)
    values = {f: str((await request.form()).get(f, "")) for f in services.BOARD_FIELDS}
    try:
        services.save_board(db, board, values)
    except services.ServiceError as exc:
        return render_form(request, db, board, values, exc.status_code, exc.message)
    flash(request, f"Saved {board.name}.")
    return redirect(request, f"/boards/{board.id}")


@router.post("/boards/{board_id}/retire", dependencies=[Depends(verify_csrf)])
def retire_board(request: Request, board_id: int, db: DB):
    return _set_retired(request, db, get_board(db, board_id), True)


@router.post("/boards/{board_id}/unretire", dependencies=[Depends(verify_csrf)])
def unretire_board(request: Request, board_id: int, db: DB):
    return _set_retired(request, db, get_board(db, board_id), False)


def _set_retired(request: Request, db: Session, board: Board, retired: bool):
    try:
        services.set_retired(db, board, retired)
    except services.ServiceError as exc:
        return render_index(request, db, exc.status_code, exc.message)
    flash(request, f"{'Retired' if retired else 'Restored'} {board.name}.")
    return redirect(request, "/admin")


@router.post("/types", dependencies=[Depends(verify_csrf)])
def add_type(request: Request, db: DB, name: Annotated[str, Form()] = ""):
    try:
        board_type = services.add_board_type(db, name)
    except services.ServiceError as exc:
        return render_index(request, db, exc.status_code, exc.message)
    flash(request, f"Added type {board_type.name}.")
    return redirect(request, "/admin")


# --- CSV export ---------------------------------------------------------------


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds") + "Z"
    text = str(value)
    # Neutralize spreadsheet formula injection from user-entered text.
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        text = "'" + text
    return text


def _csv(filename: str, header: list[str], rows) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows([_cell(v) for v in row] for row in rows)
    stamp = utcnow().strftime("%Y%m%d")
    return Response(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}-{stamp}.csv"'},
    )


@router.get("/export/boards.csv", name="export_boards")
def export_boards(db: DB):
    header = [
        "id", "name", "type", "serial", "chip_mounted", "location", "notes", "retired",
        "status", "holder_email", "holder_name", "checked_out_at", "created_at",
    ]  # fmt: skip
    rows = (
        [
            b.id,
            b.name,
            b.type.name,
            b.serial,
            b.chip_mounted,
            b.location,
            b.notes,
            "yes" if b.retired else "no",
            "retired" if b.retired else ("checked out" if c else "available"),
            c.user_email if c else None,
            c.user_name if c else None,
            c.checked_out_at if c else None,
            b.created_at,
        ]  # fmt: skip
        for b, c in services.boards_with_status(db, include_retired=True)
    )
    return _csv("boards", header, rows)


@router.get("/export/checkouts.csv", name="export_checkouts")
def export_checkouts(db: DB):
    header = [
        "id", "board_id", "board_name", "user_email", "user_name",
        "checked_out_at", "returned_at", "returned_by", "notes",
    ]  # fmt: skip
    rows = (
        [
            c.id,
            c.board_id,
            c.board.name,
            c.user_email,
            c.user_name,
            c.checked_out_at,
            c.returned_at,
            c.returned_by,
            c.notes,
        ]  # fmt: skip
        for c in services.all_checkouts(db)
    )
    return _csv("checkouts", header, rows)

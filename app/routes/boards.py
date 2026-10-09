"""Dashboard, board pages, checkout and return."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from app import services
from app.auth import CurrentUser
from app.csrf import verify_csrf
from app.db import get_db
from app.models import Board
from app.templating import flash, render
from app.urls import redirect

router = APIRouter()
DB = Annotated[Session, Depends(get_db)]


def get_board(db: Session, board_id: int) -> Board:
    board = db.get(Board, board_id)
    if board is None:
        raise HTTPException(status_code=404)
    return board


def render_board(request: Request, db: Session, board: Board, status_code=200, error=None):
    return render(
        request,
        "board.html",
        status_code=status_code,
        board=board,
        active=services.active_checkout(db, board.id),
        history=board.checkouts,
        error=error,
    )


@router.get("/", name="dashboard")
def dashboard(request: Request, user: CurrentUser, db: DB, type: int | None = None):
    rows = services.boards_with_status(db, type_id=type)
    return render(
        request,
        "dashboard.html",
        rows=rows,
        types=services.board_types(db),
        selected_type=type,
        available=sum(1 for _, c in rows if c is None),
    )


@router.get("/me", name="my_boards")
def my_boards(request: Request, user: CurrentUser, db: DB):
    checkouts = services.user_checkouts(db, user.email)
    return render(
        request,
        "my_boards.html",
        current=[c for c in checkouts if c.active],
        past=[c for c in checkouts if not c.active],
    )


@router.get("/boards/{board_id}", name="board")
def board_page(request: Request, board_id: int, user: CurrentUser, db: DB):
    return render_board(request, db, get_board(db, board_id))


@router.post("/boards/{board_id}/checkout", dependencies=[Depends(verify_csrf)])
def checkout(
    request: Request,
    board_id: int,
    user: CurrentUser,
    db: DB,
    notes: Annotated[str, Form()] = "",
    back: Annotated[str, Form()] = "",
):
    board = get_board(db, board_id)
    try:
        services.checkout_board(db, board, user, notes)
    except services.ServiceError as exc:
        return render_board(request, db, board, status_code=exc.status_code, error=exc.message)
    flash(request, f"You checked out {board.name}.")
    return redirect(request, back or f"/boards/{board.id}")


@router.post("/boards/{board_id}/return", dependencies=[Depends(verify_csrf)])
def return_(
    request: Request,
    board_id: int,
    user: CurrentUser,
    db: DB,
    back: Annotated[str, Form()] = "",
):
    board = get_board(db, board_id)
    try:
        checkout = services.return_board(db, board, user)
    except services.ServiceError as exc:
        return render_board(request, db, board, status_code=exc.status_code, error=exc.message)
    if checkout.user_email == user.email:
        flash(request, f"You returned {board.name}.")
    else:
        flash(request, f"Returned {board.name} on behalf of {checkout.user_email}.")
    return redirect(request, back or f"/boards/{board.id}")

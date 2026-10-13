"""Dashboard, asset pages, checkout and return."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from app import services
from app.auth import CurrentUser
from app.csrf import verify_csrf
from app.db import get_db
from app.models import Asset
from app.templating import flash, render
from app.urls import redirect

router = APIRouter()
DB = Annotated[Session, Depends(get_db)]


def get_asset(db: Session, asset_id: int) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404)
    return asset


def render_asset(request: Request, db: Session, asset: Asset, status_code=200, error=None):
    return render(
        request,
        "asset.html",
        status_code=status_code,
        asset=asset,
        active=services.active_checkout(db, asset.id),
        history=asset.checkouts,
        error=error,
    )


@router.get("/", name="dashboard")
def dashboard(request: Request, user: CurrentUser, db: DB):
    """What you land on after signing in: the assets you personally hold."""
    checkouts = services.user_checkouts(db, user.email)
    return render(
        request,
        "dashboard.html",
        current=[c for c in checkouts if c.active],
        past=[c for c in checkouts if not c.active],
    )


@router.get("/assets", name="asset_overview")
def asset_overview(request: Request, user: CurrentUser, db: DB, type: int | None = None):
    rows = services.assets_with_status(db, type_id=type)
    return render(
        request,
        "asset_overview.html",
        rows=rows,
        types=services.asset_types(db),
        selected_type=type,
        available=sum(1 for _, c in rows if c is None),
    )


@router.get("/assets/{asset_id}", name="asset")
def asset_page(request: Request, asset_id: int, user: CurrentUser, db: DB):
    return render_asset(request, db, get_asset(db, asset_id))


@router.post("/assets/{asset_id}/checkout", dependencies=[Depends(verify_csrf)])
def checkout(
    request: Request,
    asset_id: int,
    user: CurrentUser,
    db: DB,
    notes: Annotated[str, Form()] = "",
    back: Annotated[str, Form()] = "",
):
    asset = get_asset(db, asset_id)
    try:
        services.checkout_asset(db, asset, user, notes)
    except services.ServiceError as exc:
        return render_asset(request, db, asset, status_code=exc.status_code, error=exc.message)
    flash(request, f"You checked out {asset.name}.")
    return redirect(request, back or f"/assets/{asset.id}")


@router.post("/assets/{asset_id}/return", dependencies=[Depends(verify_csrf)])
def return_(
    request: Request,
    asset_id: int,
    user: CurrentUser,
    db: DB,
    back: Annotated[str, Form()] = "",
):
    asset = get_asset(db, asset_id)
    try:
        checkout = services.return_asset(db, asset, user)
    except services.ServiceError as exc:
        return render_asset(request, db, asset, status_code=exc.status_code, error=exc.message)
    if checkout.user_email == user.email:
        flash(request, f"You returned {asset.name}.")
    else:
        flash(request, f"Returned {asset.name} on behalf of {checkout.user_email}.")
    return redirect(request, back or f"/assets/{asset.id}")

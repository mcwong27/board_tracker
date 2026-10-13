"""Dashboard, asset pages, checkout and return."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from app import services
from app.auth import CurrentUser
from app.csrf import verify_csrf
from app.db import Database, get_db
from app.templating import flash, render
from app.urls import redirect

router = APIRouter()
DB = Annotated[Database, Depends(get_db)]


async def load_asset(db: Database, asset_id: int) -> dict:
    asset = await services.get_asset(db, asset_id)
    if asset is None:
        raise HTTPException(status_code=404)
    return asset


async def render_asset(request: Request, db: Database, asset: dict, status_code=200, error=None):
    return render(
        request,
        "asset.html",
        status_code=status_code,
        asset=asset,
        active=await services.active_checkout(db, asset["id"]),
        history=await services.asset_history(db, asset["id"]),
        error=error,
    )


@router.get("/", name="dashboard")
async def dashboard(request: Request, user: CurrentUser, db: DB):
    """What you land on after signing in: the assets you personally hold."""
    checkouts = await services.user_checkouts(db, user.email)
    return render(
        request,
        "dashboard.html",
        current=[c for c in checkouts if c["active"]],
        past=[c for c in checkouts if not c["active"]],
    )


@router.get("/assets", name="asset_overview")
async def asset_overview(request: Request, user: CurrentUser, db: DB, type: int | None = None):
    rows = await services.assets_with_status(db, type_id=type)
    return render(
        request,
        "asset_overview.html",
        rows=rows,
        types=await services.asset_types(db),
        selected_type=type,
        available=sum(1 for _, c in rows if c is None),
    )


@router.get("/assets/{asset_id}", name="asset")
async def asset_page(request: Request, asset_id: int, user: CurrentUser, db: DB):
    return await render_asset(request, db, await load_asset(db, asset_id))


@router.post("/assets/{asset_id}/checkout", dependencies=[Depends(verify_csrf)])
async def checkout(
    request: Request,
    asset_id: int,
    user: CurrentUser,
    db: DB,
    notes: Annotated[str, Form()] = "",
    back: Annotated[str, Form()] = "",
):
    asset = await load_asset(db, asset_id)
    try:
        await services.checkout_asset(db, asset, user, notes)
    except services.ServiceError as exc:
        return await render_asset(request, db, asset, exc.status_code, exc.message)
    flash(request, f"You checked out {asset['name']}.")
    return redirect(request, back or f"/assets/{asset['id']}")


@router.post("/assets/{asset_id}/return", dependencies=[Depends(verify_csrf)])
async def return_(
    request: Request,
    asset_id: int,
    user: CurrentUser,
    db: DB,
    back: Annotated[str, Form()] = "",
):
    asset = await load_asset(db, asset_id)
    try:
        checkout = await services.return_asset(db, asset, user)
    except services.ServiceError as exc:
        return await render_asset(request, db, asset, exc.status_code, exc.message)
    if checkout["user_email"] == user.email:
        flash(request, f"You returned {asset['name']}.")
    else:
        flash(request, f"Returned {asset['name']} on behalf of {checkout['user_email']}.")
    return redirect(request, back or f"/assets/{asset['id']}")

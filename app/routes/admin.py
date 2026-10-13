"""Admin: manage assets and types, export CSV. Every route requires an admin."""

import csv
import io
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import services
from app.auth import require_admin
from app.csrf import verify_csrf
from app.db import get_db
from app.models import Asset, AssetType, FpgaServer, FpgaType, utcnow
from app.templating import flash, render
from app.urls import redirect

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
DB = Annotated[Session, Depends(get_db)]


def get_asset(db: Session, asset_id: int) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404)
    return asset


def render_index(request: Request, db: Session, status_code=200, error=None):
    """The single admin page: assets and their types, plus the FPGA inventory."""
    return render(
        request,
        "admin/index.html",
        status_code=status_code,
        rows=services.assets_with_status(db, include_retired=True),
        types=services.asset_types(db),
        type_counts=services.asset_counts_by_type(db),
        fpga_types=services.fpga_types(db),
        fpga_servers=services.fpga_servers(db),
        placements=services.fpga_placements(db),
        error=error,
    )


def render_form(request: Request, db: Session, asset, values, status_code=200, error=None):
    return render(
        request,
        "admin/asset_form.html",
        status_code=status_code,
        asset=asset,
        values=values,
        types=services.asset_types(db),
        error=error,
    )


def asset_values(asset: Asset) -> dict[str, str]:
    return {f: str(getattr(asset, f) or "") for f in services.ASSET_FIELDS}


@router.get("", name="admin")
def index(request: Request, db: DB):
    return render_index(request, db)


@router.get("/assets/new", name="admin_new_asset")
def new_asset_form(request: Request, db: DB):
    return render_form(request, db, None, {})


@router.post("/assets/new", dependencies=[Depends(verify_csrf)])
async def create_asset(request: Request, db: DB):
    values = {f: str((await request.form()).get(f, "")) for f in services.ASSET_FIELDS}
    try:
        asset = services.save_asset(db, None, values)
    except services.ServiceError as exc:
        return render_form(request, db, None, values, exc.status_code, exc.message)
    flash(request, f"Added {asset.name}.")
    return redirect(request, "/admin")


MAX_IMPORT_BYTES = 2_000_000


@router.post("/assets/import", dependencies=[Depends(verify_csrf)])
async def import_assets(request: Request, db: DB, file: Annotated[UploadFile, File()]):
    raw = await file.read()
    if not raw:
        return render_index(request, db, 400, "Choose a CSV file to import.")
    if len(raw) > MAX_IMPORT_BYTES:
        return render_index(request, db, 400, "That file is too big (limit 2 MB).")
    try:
        content = raw.decode("utf-8-sig")  # tolerate the BOM Excel writes
    except UnicodeDecodeError:
        return render_index(request, db, 400, "That file isn't UTF-8 text. Save it as CSV.")
    try:
        summary = services.import_assets(db, content)
    except services.ServiceError as exc:
        return render_index(request, db, exc.status_code, exc.message)
    message = f"Imported {summary['created']} new and updated {summary['updated']} assets."
    if summary["new_types"]:
        message += f" Added types: {', '.join(summary['new_types'])}."
    flash(request, message)
    return redirect(request, "/admin")


@router.get("/assets/{asset_id}/edit", name="admin_edit_asset")
def edit_asset_form(request: Request, asset_id: int, db: DB):
    asset = get_asset(db, asset_id)
    return render_form(request, db, asset, asset_values(asset))


@router.post("/assets/{asset_id}/edit", dependencies=[Depends(verify_csrf)])
async def update_asset(request: Request, asset_id: int, db: DB):
    asset = get_asset(db, asset_id)
    values = {f: str((await request.form()).get(f, "")) for f in services.ASSET_FIELDS}
    try:
        services.save_asset(db, asset, values)
    except services.ServiceError as exc:
        return render_form(request, db, asset, values, exc.status_code, exc.message)
    flash(request, f"Saved {asset.name}.")
    return redirect(request, f"/assets/{asset.id}")


@router.post("/assets/{asset_id}/retire", dependencies=[Depends(verify_csrf)])
def retire_asset(request: Request, asset_id: int, db: DB):
    return _set_retired(request, db, get_asset(db, asset_id), True)


@router.post("/assets/{asset_id}/unretire", dependencies=[Depends(verify_csrf)])
def unretire_asset(request: Request, asset_id: int, db: DB):
    return _set_retired(request, db, get_asset(db, asset_id), False)


def _set_retired(request: Request, db: Session, asset: Asset, retired: bool):
    try:
        services.set_retired(db, asset, retired)
    except services.ServiceError as exc:
        return render_index(request, db, exc.status_code, exc.message)
    flash(request, f"{'Retired' if retired else 'Restored'} {asset.name}.")
    return redirect(request, "/admin")


@router.post("/types", dependencies=[Depends(verify_csrf)])
def add_type(request: Request, db: DB, name: Annotated[str, Form()] = ""):
    try:
        asset_type = services.add_asset_type(db, name)
    except services.ServiceError as exc:
        return render_index(request, db, exc.status_code, exc.message)
    flash(request, f"Added type {asset_type.name}.")
    return redirect(request, "/admin")


def get_type(db: Session, type_id: int) -> AssetType:
    asset_type = db.get(AssetType, type_id)
    if asset_type is None:
        raise HTTPException(status_code=404)
    return asset_type


@router.post("/types/{type_id}/rename", dependencies=[Depends(verify_csrf)])
def rename_type(request: Request, type_id: int, db: DB, name: Annotated[str, Form()] = ""):
    asset_type = get_type(db, type_id)
    was = asset_type.name
    try:
        services.rename_asset_type(db, asset_type, name)
    except services.ServiceError as exc:
        return render_index(request, db, exc.status_code, exc.message)
    flash(request, f"Renamed {was} to {asset_type.name}.")
    return redirect(request, "/admin")


@router.post("/types/{type_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_type(request: Request, type_id: int, db: DB):
    asset_type = get_type(db, type_id)
    try:
        services.delete_asset_type(db, asset_type)
    except services.ServiceError as exc:
        return render_index(request, db, exc.status_code, exc.message)
    flash(request, f"Deleted type {asset_type.name}.")
    return redirect(request, "/admin")


# --- FPGA inventory -----------------------------------------------------------
# Separate from assets for users, but managed from the same admin page.


def get_fpga_type(db: Session, type_id: int) -> FpgaType:
    fpga_type = db.get(FpgaType, type_id)
    if fpga_type is None:
        raise HTTPException(status_code=404)
    return fpga_type


def get_fpga_server(db: Session, server_id: int) -> FpgaServer:
    server = db.get(FpgaServer, server_id)
    if server is None:
        raise HTTPException(status_code=404)
    return server


@router.post("/fpga/types", dependencies=[Depends(verify_csrf)])
def add_fpga_type(request: Request, db: DB, name: Annotated[str, Form()] = ""):
    try:
        fpga_type = services.add_fpga_type(db, name)
    except services.ServiceError as exc:
        return render_index(request, db, exc.status_code, exc.message)
    flash(request, f"Added FPGA type {fpga_type.name}.")
    return redirect(request, "/admin")


@router.post("/fpga/types/{type_id}/rename", dependencies=[Depends(verify_csrf)])
def rename_fpga_type(request: Request, type_id: int, db: DB, name: Annotated[str, Form()] = ""):
    fpga_type = get_fpga_type(db, type_id)
    was = fpga_type.name
    try:
        services.rename_fpga_type(db, fpga_type, name)
    except services.ServiceError as exc:
        return render_index(request, db, exc.status_code, exc.message)
    flash(request, f"Renamed {was} to {fpga_type.name}.")
    return redirect(request, "/admin")


@router.post("/fpga/types/{type_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_fpga_type(request: Request, type_id: int, db: DB):
    fpga_type = get_fpga_type(db, type_id)
    try:
        services.delete_fpga_type(db, fpga_type)
    except services.ServiceError as exc:
        return render_index(request, db, exc.status_code, exc.message)
    flash(request, f"Deleted FPGA type {fpga_type.name}.")
    return redirect(request, "/admin")


@router.post("/fpga/servers", dependencies=[Depends(verify_csrf)])
def add_fpga_server(
    request: Request,
    db: DB,
    name: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    try:
        server = services.add_fpga_server(db, name, notes)
    except services.ServiceError as exc:
        return render_index(request, db, exc.status_code, exc.message)
    flash(request, f"Added server {server.name}.")
    return redirect(request, "/admin")


@router.post("/fpga/servers/{server_id}/rename", dependencies=[Depends(verify_csrf)])
def rename_fpga_server(request: Request, server_id: int, db: DB, name: Annotated[str, Form()] = ""):
    server = get_fpga_server(db, server_id)
    was = server.name
    try:
        services.rename_fpga_server(db, server, name)
    except services.ServiceError as exc:
        return render_index(request, db, exc.status_code, exc.message)
    flash(request, f"Renamed {was} to {server.name}.")
    return redirect(request, "/admin")


@router.post("/fpga/servers/{server_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_fpga_server(request: Request, server_id: int, db: DB):
    server = get_fpga_server(db, server_id)
    try:
        services.delete_fpga_server(db, server)
    except services.ServiceError as exc:
        return render_index(request, db, exc.status_code, exc.message)
    flash(request, f"Deleted server {server.name}.")
    return redirect(request, "/admin")


@router.post("/fpga/counts", dependencies=[Depends(verify_csrf)])
async def save_fpga_counts(request: Request, db: DB):
    """The how-many-where grid posts one `qty-<type_id>-<server_id>` field per cell."""
    counts: dict[tuple[int, int], int] = {}
    for key, value in (await request.form()).items():
        if not key.startswith("qty-"):
            continue
        try:
            _, type_id, server_id = key.split("-")
            counts[(int(type_id), int(server_id))] = int(str(value) or 0)
        except ValueError:
            return render_index(request, db, 400, "Counts must be whole numbers.")
    try:
        services.set_fpga_placements(db, counts)
    except services.ServiceError as exc:
        return render_index(request, db, exc.status_code, exc.message)
    flash(request, "Saved FPGA counts.")
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


@router.get("/export/assets.csv", name="export_assets")
def export_assets(db: DB):
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
        for b, c in services.assets_with_status(db, include_retired=True)
    )
    return _csv("assets", header, rows)


@router.get("/export/checkouts.csv", name="export_checkouts")
def export_checkouts(db: DB):
    header = [
        "id", "asset_id", "asset_name", "user_email", "user_name",
        "checked_out_at", "returned_at", "returned_by", "notes",
    ]  # fmt: skip
    rows = (
        [
            c.id,
            c.asset_id,
            c.asset.name,
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

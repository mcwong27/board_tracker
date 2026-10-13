"""Business rules for assets and checkouts. Routes stay thin and call these."""

import csv
import io
from datetime import date, timedelta

from sqlalchemy import and_, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth import User
from app.models import (
    Asset,
    AssetType,
    Checkout,
    FpgaPlacement,
    FpgaReservation,
    FpgaServer,
    FpgaType,
    utcnow,
)


class ServiceError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class Conflict(ServiceError):
    status_code = 409


class Forbidden(ServiceError):
    status_code = 403


def asset_types(db: Session) -> list[AssetType]:
    return list(db.scalars(select(AssetType).order_by(AssetType.sort_order, AssetType.name)))


def assets_with_status(
    db: Session, *, type_id: int | None = None, include_retired: bool = False
) -> list[tuple[Asset, Checkout | None]]:
    """Assets paired with their active checkout (None when available)."""
    stmt = (
        select(Asset, Checkout)
        .join(Asset.type)
        .outerjoin(Checkout, and_(Checkout.asset_id == Asset.id, Checkout.returned_at.is_(None)))
        .options(joinedload(Asset.type))
        .order_by(AssetType.sort_order, AssetType.name, Asset.name)
    )
    if not include_retired:
        stmt = stmt.where(Asset.retired.is_(False))
    if type_id is not None:
        stmt = stmt.where(Asset.type_id == type_id)
    return [(asset, checkout) for asset, checkout in db.execute(stmt)]


def active_checkout(db: Session, asset_id: int) -> Checkout | None:
    return db.scalar(
        select(Checkout).where(Checkout.asset_id == asset_id, Checkout.returned_at.is_(None))
    )


def user_checkouts(db: Session, email: str) -> list[Checkout]:
    return list(
        db.scalars(
            select(Checkout)
            .where(Checkout.user_email == email)
            .options(joinedload(Checkout.asset).joinedload(Asset.type))
            .order_by(Checkout.checked_out_at.desc())
        )
    )


def checkout_asset(db: Session, asset: Asset, user: User, notes: str = "") -> Checkout:
    if asset.retired:
        raise Conflict(f"{asset.name} is retired and can't be checked out.")
    checkout = Checkout(
        asset_id=asset.id, user_email=user.email, user_name=user.name, notes=notes.strip()
    )
    db.add(checkout)
    try:
        db.commit()
    except IntegrityError:
        # The partial unique index rejected a second active checkout (possibly a race).
        db.rollback()
        holder = active_checkout(db, asset.id)
        who = f" by {holder.user_name or holder.user_email}" if holder else ""
        raise Conflict(f"{asset.name} is already checked out{who}.") from None
    return checkout


def return_asset(db: Session, asset: Asset, user: User) -> Checkout:
    """Return an asset. Only the holder or an admin may do this."""
    checkout = active_checkout(db, asset.id)
    if checkout is None:
        raise Conflict(f"{asset.name} isn't checked out.")
    if checkout.user_email != user.email and not user.is_admin:
        raise Forbidden("Only the person who has this asset or an admin can return it.")
    now = utcnow()
    # Conditional update so two simultaneous returns can't both succeed.
    result = db.execute(
        update(Checkout)
        .where(Checkout.id == checkout.id, Checkout.returned_at.is_(None))
        .values(returned_at=now, returned_by=user.email)
    )
    if result.rowcount != 1:
        db.rollback()
        raise Conflict(f"{asset.name} was already returned.")
    db.commit()
    db.refresh(checkout)
    return checkout


ASSET_FIELDS = ("name", "type_id", "serial", "chip_mounted", "location", "notes")


def save_asset(db: Session, asset: Asset | None, form: dict[str, str]) -> Asset:
    """Create (asset=None) or update an asset from submitted form values."""
    name = form.get("name", "").strip()
    if not name:
        raise ServiceError("Name is required.")
    try:
        type_id = int(form.get("type_id", ""))
    except ValueError:
        raise ServiceError("Pick an asset type.") from None
    if db.get(AssetType, type_id) is None:
        raise ServiceError("Pick an asset type.")

    if asset is None:
        asset = Asset()
        db.add(asset)
    asset.name = name
    asset.type_id = type_id
    for field in ("serial", "chip_mounted", "location", "notes"):
        setattr(asset, field, form.get(field, "").strip())
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict(f"An asset named {name!r} already exists.") from None
    return asset


def set_retired(db: Session, asset: Asset, retired: bool) -> None:
    if retired and active_checkout(db, asset.id) is not None:
        raise Conflict(f"{asset.name} is checked out. Return it before retiring it.")
    asset.retired = retired
    db.commit()


def add_asset_type(db: Session, name: str) -> AssetType:
    name = name.strip()
    if not name:
        raise ServiceError("Type name is required.")
    asset_type = AssetType(name=name)
    db.add(asset_type)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict(f"Type {name!r} already exists.") from None
    return asset_type


def asset_counts_by_type(db: Session) -> dict[int, int]:
    return dict(db.execute(select(Asset.type_id, func.count()).group_by(Asset.type_id)).all())


def rename_asset_type(db: Session, asset_type: AssetType, name: str) -> AssetType:
    name = name.strip()
    if not name:
        raise ServiceError("Type name is required.")
    asset_type.name = name
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict(f"Type {name!r} already exists.") from None
    return asset_type


def delete_asset_type(db: Session, asset_type: AssetType) -> None:
    in_use = db.scalar(
        select(func.count()).select_from(Asset).where(Asset.type_id == asset_type.id)
    )
    if in_use:
        raise Conflict(
            f"{asset_type.name} is used by {in_use} asset{'s' if in_use > 1 else ''}. "
            "Move or delete them first."
        )
    db.delete(asset_type)
    db.commit()


# Columns the importer reads; everything else in an exported file (id, status,
# holder_*, checked_out_at, created_at) is derived and ignored on the way back in.
IMPORT_COLUMNS = ("name", "type", "serial", "chip_mounted", "location", "notes", "retired")
TRUTHY = {"yes", "true", "1", "y"}
FALSEY = {"no", "false", "0", "n", ""}


def _uncell(value: str | None) -> str:
    """Undo the leading apostrophe the exporter adds to spreadsheet-formula text."""
    text = (value or "").strip()
    return text[1:] if text[:1] == "'" else text


def import_assets(db: Session, content: str) -> dict:
    """Create or update assets from a CSV in the same shape the exporter writes.

    Matches rows to existing assets by name, so a downloaded file can be edited and
    uploaded back. Never deletes anything. Missing asset types are created. The whole
    file is rejected if any row is bad, so a typo can't half-apply.
    """
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise ServiceError("That file is empty.")
    columns = {(name or "").strip().lower() for name in reader.fieldnames}
    missing = {"name", "type"} - columns
    if missing:
        raise ServiceError(
            f"The CSV is missing the {', '.join(sorted(missing))} column"
            f"{'s' if len(missing) > 1 else ''}. Export the assets CSV to see the expected format."
        )

    parsed: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for line, row in enumerate(reader, start=2):  # line 1 is the header
        values = {column: _uncell(row.get(column)) for column in IMPORT_COLUMNS}
        if not any(values.values()):
            continue  # blank line
        if not values["name"]:
            errors.append(f"Row {line}: name is required.")
            continue
        if values["name"].lower() in seen:
            errors.append(f"Row {line}: {values['name']} appears more than once in the file.")
            continue
        seen.add(values["name"].lower())
        if not values["type"]:
            errors.append(f"Row {line}: type is required.")
            continue
        retired = values["retired"].lower()
        if retired not in TRUTHY and retired not in FALSEY:
            errors.append(f"Row {line}: retired should be yes or no, not {values['retired']!r}.")
            continue
        values["retired"] = retired in TRUTHY
        parsed.append(values)

    if errors:
        shown = errors[:10]
        if len(errors) > len(shown):
            shown.append(f"…and {len(errors) - len(shown)} more.")
        raise ServiceError("Nothing was imported:\n" + "\n".join(shown))
    if not parsed:
        raise ServiceError("That file has no asset rows.")

    types = {t.name.lower(): t for t in asset_types(db)}
    assets = {a.name.lower(): a for a in db.scalars(select(Asset))}
    created = updated = 0
    new_types: list[str] = []
    for values in parsed:
        asset_type = types.get(values["type"].lower())
        if asset_type is None:
            asset_type = AssetType(name=values["type"])
            db.add(asset_type)
            db.flush()
            types[values["type"].lower()] = asset_type
            new_types.append(asset_type.name)
        asset = assets.get(values["name"].lower())
        if asset is None:
            asset = Asset(name=values["name"])
            db.add(asset)
            assets[values["name"].lower()] = asset
            created += 1
        else:
            updated += 1
        asset.type_id = asset_type.id
        asset.retired = values["retired"]
        for field in ("serial", "chip_mounted", "location", "notes"):
            setattr(asset, field, values[field])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("The import clashed with existing data and was rolled back.") from None
    return {"created": created, "updated": updated, "new_types": new_types}


def all_checkouts(db: Session) -> list[Checkout]:
    return list(
        db.scalars(
            select(Checkout)
            .options(joinedload(Checkout.asset))
            .order_by(Checkout.checked_out_at, Checkout.id)
        )
    )


# --- FPGA inventory ------------------------------------------------------------
# Admins record which FPGA models exist and how many sit in each server.


def fpga_types(db: Session) -> list[FpgaType]:
    return list(db.scalars(select(FpgaType).order_by(FpgaType.name)))


def fpga_servers(db: Session) -> list[FpgaServer]:
    return list(db.scalars(select(FpgaServer).order_by(FpgaServer.name)))


def fpga_placements(db: Session) -> dict[tuple[int, int], int]:
    """{(fpga_type_id, server_id): quantity} for every placement with a count."""
    rows = db.execute(
        select(FpgaPlacement.fpga_type_id, FpgaPlacement.server_id, FpgaPlacement.quantity)
    ).all()
    return {(type_id, server_id): qty for type_id, server_id, qty in rows}


def fpga_inventory_by_type(db: Session) -> dict[int, list[tuple[FpgaServer, int]]]:
    """{fpga_type_id: [(server, quantity), ...]} for showing where each model lives."""
    rows = db.scalars(
        select(FpgaPlacement)
        .where(FpgaPlacement.quantity > 0)
        .options(joinedload(FpgaPlacement.server))
        .join(FpgaPlacement.server)
        .order_by(FpgaServer.name)
    )
    inventory: dict[int, list[tuple[FpgaServer, int]]] = {}
    for placement in rows:
        inventory.setdefault(placement.fpga_type_id, []).append(
            (placement.server, placement.quantity)
        )
    return inventory


def add_fpga_type(db: Session, name: str) -> FpgaType:
    name = name.strip()
    if not name:
        raise ServiceError("FPGA type name is required.")
    fpga_type = FpgaType(name=name)
    db.add(fpga_type)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict(f"FPGA type {name!r} already exists.") from None
    return fpga_type


def rename_fpga_type(db: Session, fpga_type: FpgaType, name: str) -> FpgaType:
    name = name.strip()
    if not name:
        raise ServiceError("FPGA type name is required.")
    fpga_type.name = name
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict(f"FPGA type {name!r} already exists.") from None
    return fpga_type


def delete_fpga_type(db: Session, fpga_type: FpgaType) -> None:
    booked = db.scalar(
        select(func.count())
        .select_from(FpgaReservation)
        .where(FpgaReservation.fpga_type_id == fpga_type.id)
    )
    if booked:
        raise Conflict(
            f"{fpga_type.name} is used by {booked} reservation{'s' if booked > 1 else ''}. "
            "Delete those first."
        )
    db.delete(fpga_type)  # placements cascade
    db.commit()


def add_fpga_server(db: Session, name: str, notes: str = "") -> FpgaServer:
    name = name.strip()
    if not name:
        raise ServiceError("Server name is required.")
    server = FpgaServer(name=name, notes=notes.strip())
    db.add(server)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict(f"Server {name!r} already exists.") from None
    return server


def rename_fpga_server(db: Session, server: FpgaServer, name: str) -> FpgaServer:
    name = name.strip()
    if not name:
        raise ServiceError("Server name is required.")
    server.name = name
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict(f"Server {name!r} already exists.") from None
    return server


def delete_fpga_server(db: Session, server: FpgaServer) -> None:
    booked = db.scalar(
        select(func.count())
        .select_from(FpgaReservation)
        .where(FpgaReservation.server_id == server.id)
    )
    if booked:
        raise Conflict(
            f"{server.name} is used by {booked} reservation{'s' if booked > 1 else ''}. "
            "Move or delete those first."
        )
    db.delete(server)  # placements cascade
    db.commit()


def set_fpga_placements(db: Session, counts: dict[tuple[int, int], int]) -> None:
    """Replace the how-many-where grid. A count of 0 removes the placement."""
    existing = {(p.fpga_type_id, p.server_id): p for p in db.scalars(select(FpgaPlacement))}
    for (type_id, server_id), quantity in counts.items():
        if quantity < 0:
            raise ServiceError("Counts can't be negative.")
        placement = existing.get((type_id, server_id))
        if quantity == 0:
            if placement is not None:
                db.delete(placement)
        elif placement is not None:
            placement.quantity = quantity
        else:
            db.add(FpgaPlacement(fpga_type_id=type_id, server_id=server_id, quantity=quantity))
    db.commit()


# --- FPGA reservations ---------------------------------------------------------
# A shared calendar, not an allocator: over-booking a server is allowed but flagged,
# because people sort out sharing between themselves.

FPGA_FIELDS = (
    "fpga_type_id",
    "server_id",
    "project",
    "quantity",
    "contact",
    "special_requests",
    "start_date",
    "end_date",
)


def fpga_reservations(db: Session) -> list[FpgaReservation]:
    return list(
        db.scalars(
            select(FpgaReservation)
            .options(joinedload(FpgaReservation.fpga_type), joinedload(FpgaReservation.server))
            .order_by(FpgaReservation.start_date, FpgaReservation.id)
        )
    )


def _parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ServiceError(f"{label} must be a valid date.") from None


def save_fpga_reservation(
    db: Session, reservation: FpgaReservation | None, user: User, form: dict[str, str]
) -> FpgaReservation:
    """Create (reservation=None) or update an FPGA reservation from submitted form values.

    Only the person who created a reservation or an admin may edit it.
    """
    if reservation is not None and reservation.created_by_email != user.email and not user.is_admin:
        raise Forbidden("Only the person who made this reservation or an admin can edit it.")

    try:
        fpga_type_id = int(form.get("fpga_type_id", ""))
    except ValueError:
        raise ServiceError("Pick an FPGA type.") from None
    if db.get(FpgaType, fpga_type_id) is None:
        raise ServiceError("Pick an FPGA type.")

    try:
        server_id = int(form.get("server_id", ""))
    except ValueError:
        raise ServiceError("Pick a server.") from None
    if db.get(FpgaServer, server_id) is None:
        raise ServiceError("Pick a server.")

    project = form.get("project", "").strip()
    if not project:
        raise ServiceError("Project is required.")
    contact = form.get("contact", "").strip()
    if not contact:
        raise ServiceError("Username / point of contact is required.")
    try:
        quantity = int(form.get("quantity", ""))
    except ValueError:
        raise ServiceError("Number of FPGAs must be a whole number.") from None
    if quantity < 1:
        raise ServiceError("Number of FPGAs must be at least 1.")
    start_date = _parse_date(form.get("start_date", ""), "Start date")
    end_date = _parse_date(form.get("end_date", ""), "End date")
    if end_date < start_date:
        raise ServiceError("End date can't be before start date.")

    if reservation is None:
        reservation = FpgaReservation(created_by_email=user.email)
        db.add(reservation)
    reservation.fpga_type_id = fpga_type_id
    reservation.server_id = server_id
    reservation.project = project
    reservation.contact = contact
    reservation.quantity = quantity
    reservation.special_requests = form.get("special_requests", "").strip()
    reservation.start_date = start_date
    reservation.end_date = end_date
    db.commit()
    return reservation


def delete_fpga_reservation(db: Session, reservation: FpgaReservation, user: User) -> None:
    if reservation.created_by_email != user.email and not user.is_admin:
        raise Forbidden("Only the person who made this reservation or an admin can delete it.")
    db.delete(reservation)
    db.commit()


def _slots_for_type(
    fpga_type_id: int, placements: dict[tuple[int, int], int], servers: dict[int, FpgaServer]
) -> list[dict]:
    """One slot per physical FPGA: a count of 4 in a server becomes #1..#4.

    Admins record counts, not serial numbers, so a slot's identity is its position
    in a server. That's enough to give every board its own row and its own hue.
    """
    slots = []
    for (type_id, server_id), quantity in placements.items():
        if type_id != fpga_type_id:
            continue
        server = servers[server_id]
        for index in range(1, quantity + 1):
            slots.append(
                {
                    "server": server,
                    "index": index,
                    "label": f"{server.name} #{index}",
                    "booked": [],  # (start, end) stretches already taken
                    "reservations": [],
                }
            )
    slots.sort(key=lambda s: (s["server"].name, s["index"]))
    # Spread hues around the wheel, starting near Berkeley blue.
    for position, slot in enumerate(slots):
        slot["hue"] = (205 + round(360 * position / max(len(slots), 1))) % 360
    return slots


def assign_to_slots(
    reservations: list[FpgaReservation], slots: list[dict]
) -> list[FpgaReservation]:
    """Place each booking on specific boards; return the ones that didn't fit.

    A booking for 2 FPGAs takes two slots in its server for its whole stretch.
    All-or-nothing: if there aren't enough free boards it goes to the overflow
    row instead of being split across a board it can't actually have.
    """

    def free(slot, r):
        return all(end < r.start_date or start > r.end_date for start, end in slot["booked"])

    overflow = []
    for r in sorted(reservations, key=lambda r: (r.start_date, r.id)):
        candidates = [s for s in slots if s["server"].id == r.server_id and free(s, r)]
        if r.server_id is None or len(candidates) < r.quantity:
            overflow.append(r)
            continue
        for slot in candidates[: r.quantity]:
            slot["booked"].append((r.start_date, r.end_date))
            slot["reservations"].append(r)
    return overflow


def _days(start: date, end: date):
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


def oversubscribed(
    reservations: list[FpgaReservation], placements: dict[tuple[int, int], int]
) -> tuple[set[int], list[str]]:
    """Find reservations that put a server over the number of FPGAs installed in it.

    Returns the ids of the reservations involved plus one readable warning per
    (type, server) stretch. Reservations with no server named are skipped: there's
    nothing to compare them against.
    """
    by_place: dict[tuple[int, int], list[FpgaReservation]] = {}
    for r in reservations:
        if r.server_id is not None:
            by_place.setdefault((r.fpga_type_id, r.server_id), []).append(r)

    flagged: set[int] = set()
    warnings: list[str] = []
    for (type_id, server_id), group in by_place.items():
        capacity = placements.get((type_id, server_id), 0)
        in_use: dict[date, int] = {}
        for r in group:
            for day in _days(r.start_date, r.end_date):
                in_use[day] = in_use.get(day, 0) + r.quantity
        over_days = sorted(day for day, total in in_use.items() if total > capacity)
        if not over_days:
            continue
        peak = max(in_use[day] for day in over_days)
        sample = group[0]
        where = sample.server.name if sample.server else "?"
        what = sample.fpga_type.name if sample.fpga_type else "?"
        span = (
            f"{over_days[0]:%b %-d}"
            if len(over_days) == 1
            else f"{over_days[0]:%b %-d}–{over_days[-1]:%b %-d}"
        )
        warnings.append(f"{what} in {where}: {peak} booked of {capacity} installed, {span}.")
        for r in group:
            if any(
                day in in_use and in_use[day] > capacity for day in _days(r.start_date, r.end_date)
            ):
                flagged.add(r.id)
    return flagged, sorted(warnings)


def fpga_timeline(db: Session, window_start: date, window_end: date) -> dict:
    """Timeline data for [window_start, window_end].

    One group per FPGA type. Inside a group there's a row per physical board, each
    with its own hue; the collapsed view stacks those rows as thin bands so a type
    stays one line until someone opens it.
    """
    total_days = (window_end - window_start).days + 1
    all_reservations = fpga_reservations(db)
    placements = fpga_placements(db)
    # Over-subscription is judged on the whole booking, not just the visible slice.
    flagged, warnings = oversubscribed(all_reservations, placements)
    servers = {s.id: s for s in fpga_servers(db)}

    def bar(r: FpgaReservation, hue: int | None) -> dict | None:
        if r.end_date < window_start or r.start_date > window_end:
            return None
        left_day = max(r.start_date, window_start)
        right_day = min(r.end_date, window_end)
        left_pct = (left_day - window_start).days / total_days * 100
        width_pct = ((right_day - window_start).days + 1) / total_days * 100 - left_pct
        return {
            "reservation": r,
            "left_pct": left_pct,
            "width_pct": width_pct,
            "over": r.id in flagged,
            "hue": hue,
        }

    by_type: dict[int, list[FpgaReservation]] = {}
    for r in all_reservations:
        by_type.setdefault(r.fpga_type_id, []).append(r)

    inventory = fpga_inventory_by_type(db)
    groups = []
    for fpga_type in fpga_types(db):
        slots = _slots_for_type(fpga_type.id, placements, servers)
        overflow = assign_to_slots(by_type.get(fpga_type.id, []), slots)
        rows = [
            {
                "label": slot["label"],
                "hue": slot["hue"],
                "over_row": False,
                "bars": [b for b in (bar(r, slot["hue"]) for r in slot["reservations"]) if b],
            }
            for slot in slots
        ]
        overflow_bars = [b for b in (bar(r, None) for r in overflow) if b]
        if overflow_bars:
            rows.append(
                {"label": "Over capacity", "hue": None, "over_row": True, "bars": overflow_bars}
            )
        installed = inventory.get(fpga_type.id, [])
        groups.append(
            {
                "fpga_type": fpga_type,
                "rows": rows,
                "booked_now": sum(len(row["bars"]) for row in rows),
                "installed": installed,
                "total": sum(qty for _, qty in installed),
            }
        )

    ticks = []
    d = window_start
    while d <= window_end:
        left_pct = (d - window_start).days / total_days * 100
        ticks.append({"label": d.strftime("%b %-d"), "left_pct": left_pct})
        d += timedelta(days=7)

    today = utcnow().date()
    in_window = window_start <= today <= window_end
    today_pct = (today - window_start).days / total_days * 100 if in_window else None
    return {
        "groups": groups,
        "ticks": ticks,
        "today_pct": today_pct,
        "warnings": warnings,
    }

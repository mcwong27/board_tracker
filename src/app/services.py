"""Business rules for assets and checkouts. Routes stay thin and call these.

Everything here talks to `app.db.Database`, which is D1 in production and a local
SQLite file in tests — the SQL is the same either way.
"""

import csv
import io
from datetime import date, timedelta

from app.auth import User
from app.db import Database, UniqueViolation
from app.models import (
    asset_row,
    asset_type_row,
    checkout_row,
    date_to_text,
    dt_to_text,
    fpga_reservation_row,
    fpga_server_row,
    fpga_type_row,
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


ASSET_COLUMNS = """
    a.id, a.name, a.type_id, a.serial, a.chip_mounted, a.location, a.notes,
    a.retired, a.created_at, t.name AS type_name
"""


async def asset_types(db: Database) -> list[dict]:
    rows = await db.query("SELECT * FROM asset_type ORDER BY sort_order, name")
    return [asset_type_row(row) for row in rows]


async def get_asset_type(db: Database, type_id: int) -> dict | None:
    row = await db.query_one("SELECT * FROM asset_type WHERE id = ?", (type_id,))
    return asset_type_row(row) if row else None


async def get_asset(db: Database, asset_id: int) -> dict | None:
    row = await db.query_one(
        f"SELECT {ASSET_COLUMNS} FROM asset a JOIN asset_type t ON t.id = a.type_id WHERE a.id = ?",
        (asset_id,),
    )
    return asset_row(row) if row else None


async def assets_with_status(
    db: Database, *, type_id: int | None = None, include_retired: bool = False
) -> list[tuple[dict, dict | None]]:
    """Assets paired with their active checkout (None when available)."""
    sql = f"""
        SELECT {ASSET_COLUMNS},
               c.id AS c_id, c.asset_id AS c_asset_id, c.user_email AS c_user_email,
               c.user_name AS c_user_name, c.checked_out_at AS c_checked_out_at,
               c.returned_at AS c_returned_at, c.returned_by AS c_returned_by,
               c.notes AS c_notes
        FROM asset a
        JOIN asset_type t ON t.id = a.type_id
        LEFT JOIN checkout c ON c.asset_id = a.id AND c.returned_at IS NULL
    """
    where, params = [], []
    if not include_retired:
        where.append("a.retired = 0")
    if type_id is not None:
        where.append("a.type_id = ?")
        params.append(type_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.sort_order, t.name, a.name"

    pairs = []
    for row in await db.query(sql, tuple(params)):
        checkout = None
        if row.get("c_id") is not None:
            checkout = checkout_row(
                {key[2:]: value for key, value in row.items() if key[:2] == "c_"}
            )
        pairs.append((asset_row(row), checkout))
    return pairs


async def active_checkout(db: Database, asset_id: int) -> dict | None:
    row = await db.query_one(
        "SELECT * FROM checkout WHERE asset_id = ? AND returned_at IS NULL", (asset_id,)
    )
    return checkout_row(row) if row else None


async def user_checkouts(db: Database, email: str) -> list[dict]:
    rows = await db.query(
        f"""
        SELECT c.*, {ASSET_COLUMNS}
        FROM checkout c
        JOIN asset a ON a.id = c.asset_id
        JOIN asset_type t ON t.id = a.type_id
        WHERE c.user_email = ?
        ORDER BY c.checked_out_at DESC
        """,
        (email,),
    )
    # `a.id`/`a.name` would collide with the checkout's own columns, so rebuild the
    # asset from its aliased copies before mapping.
    checkouts = []
    for row in rows:
        asset = asset_row(
            {
                "id": row["asset_id"],
                "name": row["name"],
                "type_id": row["type_id"],
                "type_name": row["type_name"],
                "serial": row["serial"],
                "chip_mounted": row["chip_mounted"],
                "location": row["location"],
                "notes": row["notes"],
                "retired": row["retired"],
                "created_at": row["created_at"],
            }
        )
        checkouts.append(checkout_row(row, asset=asset))
    return checkouts


async def asset_history(db: Database, asset_id: int) -> list[dict]:
    rows = await db.query(
        "SELECT * FROM checkout WHERE asset_id = ? ORDER BY checked_out_at DESC, id DESC",
        (asset_id,),
    )
    return [checkout_row(row) for row in rows]


async def checkout_asset(db: Database, asset: dict, user: User, notes: str = "") -> dict:
    if asset["retired"]:
        raise Conflict(f"{asset['name']} is retired and can't be checked out.")
    try:
        await db.execute(
            "INSERT INTO checkout (asset_id, user_email, user_name, checked_out_at, notes)"
            " VALUES (?, ?, ?, ?, ?)",
            (asset["id"], user.email, user.name, dt_to_text(utcnow()), notes.strip()),
        )
    except UniqueViolation:
        # The partial unique index rejected a second active checkout (possibly a race).
        holder = await active_checkout(db, asset["id"])
        who = f" by {holder['user_name'] or holder['user_email']}" if holder else ""
        raise Conflict(f"{asset['name']} is already checked out{who}.") from None
    return await active_checkout(db, asset["id"])


async def return_asset(db: Database, asset: dict, user: User) -> dict:
    """Return an asset. Only the holder or an admin may do this."""
    checkout = await active_checkout(db, asset["id"])
    if checkout is None:
        raise Conflict(f"{asset['name']} isn't checked out.")
    if checkout["user_email"] != user.email and not user.is_admin:
        raise Forbidden("Only the person who has this asset or an admin can return it.")
    # Conditional update so two simultaneous returns can't both succeed.
    result = await db.execute(
        "UPDATE checkout SET returned_at = ?, returned_by = ? WHERE id = ? AND returned_at IS NULL",
        (dt_to_text(utcnow()), user.email, checkout["id"]),
    )
    if result.rows_affected != 1:
        raise Conflict(f"{asset['name']} was already returned.")
    row = await db.query_one("SELECT * FROM checkout WHERE id = ?", (checkout["id"],))
    return checkout_row(row)


ASSET_FIELDS = ("name", "type_id", "serial", "chip_mounted", "location", "notes")


async def save_asset(db: Database, asset: dict | None, form: dict[str, str]) -> dict:
    """Create (asset=None) or update an asset from submitted form values."""
    name = form.get("name", "").strip()
    if not name:
        raise ServiceError("Name is required.")
    try:
        type_id = int(form.get("type_id", ""))
    except ValueError:
        raise ServiceError("Pick an asset type.") from None
    if await get_asset_type(db, type_id) is None:
        raise ServiceError("Pick an asset type.")

    fields = {field: form.get(field, "").strip() for field in ASSET_FIELDS[2:]}
    try:
        if asset is None:
            result = await db.execute(
                "INSERT INTO asset (name, type_id, serial, chip_mounted, location, notes,"
                " retired, created_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                (
                    name,
                    type_id,
                    fields["serial"],
                    fields["chip_mounted"],
                    fields["location"],
                    fields["notes"],
                    dt_to_text(utcnow()),
                ),
            )
            asset_id = result.last_row_id
        else:
            await db.execute(
                "UPDATE asset SET name = ?, type_id = ?, serial = ?, chip_mounted = ?,"
                " location = ?, notes = ? WHERE id = ?",
                (
                    name,
                    type_id,
                    fields["serial"],
                    fields["chip_mounted"],
                    fields["location"],
                    fields["notes"],
                    asset["id"],
                ),
            )
            asset_id = asset["id"]
    except UniqueViolation:
        raise Conflict(f"An asset named {name!r} already exists.") from None
    return await get_asset(db, asset_id)


async def set_retired(db: Database, asset: dict, retired: bool) -> None:
    if retired and await active_checkout(db, asset["id"]) is not None:
        raise Conflict(f"{asset['name']} is checked out. Return it before retiring it.")
    await db.execute(
        "UPDATE asset SET retired = ? WHERE id = ?", (1 if retired else 0, asset["id"])
    )


async def add_asset_type(db: Database, name: str) -> dict:
    name = name.strip()
    if not name:
        raise ServiceError("Type name is required.")
    try:
        result = await db.execute("INSERT INTO asset_type (name) VALUES (?)", (name,))
    except UniqueViolation:
        raise Conflict(f"Type {name!r} already exists.") from None
    return await get_asset_type(db, result.last_row_id)


async def asset_counts_by_type(db: Database) -> dict[int, int]:
    rows = await db.query("SELECT type_id, COUNT(*) AS n FROM asset GROUP BY type_id")
    return {row["type_id"]: row["n"] for row in rows}


async def rename_asset_type(db: Database, asset_type: dict, name: str) -> dict:
    name = name.strip()
    if not name:
        raise ServiceError("Type name is required.")
    try:
        await db.execute("UPDATE asset_type SET name = ? WHERE id = ?", (name, asset_type["id"]))
    except UniqueViolation:
        raise Conflict(f"Type {name!r} already exists.") from None
    return await get_asset_type(db, asset_type["id"])


async def delete_asset_type(db: Database, asset_type: dict) -> None:
    in_use = await db.value("SELECT COUNT(*) FROM asset WHERE type_id = ?", (asset_type["id"],))
    if in_use:
        raise Conflict(
            f"{asset_type['name']} is used by {in_use} asset{'s' if in_use > 1 else ''}. "
            "Move or delete them first."
        )
    await db.execute("DELETE FROM asset_type WHERE id = ?", (asset_type["id"],))


# Columns the importer reads; everything else in an exported file (id, status,
# holder_*, checked_out_at, created_at) is derived and ignored on the way back in.
IMPORT_COLUMNS = ("name", "type", "serial", "chip_mounted", "location", "notes", "retired")
TRUTHY = {"yes", "true", "1", "y"}
FALSEY = {"no", "false", "0", "n", ""}


def _uncell(value: str | None) -> str:
    """Undo the leading apostrophe the exporter adds to spreadsheet-formula text."""
    text = (value or "").strip()
    return text[1:] if text[:1] == "'" else text


async def import_assets(db: Database, content: str) -> dict:
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

    existing_types = {row["name"].lower() for row in await db.query("SELECT name FROM asset_type")}
    existing_assets = {row["name"].lower() for row in await db.query("SELECT name FROM asset")}

    statements: list[tuple[str, tuple]] = []
    new_types: list[str] = []
    for values in parsed:
        if values["type"].lower() not in existing_types:
            existing_types.add(values["type"].lower())
            new_types.append(values["type"])
            statements.append(
                ("INSERT OR IGNORE INTO asset_type (name) VALUES (?)", (values["type"],))
            )

    created = sum(1 for v in parsed if v["name"].lower() not in existing_assets)
    updated = len(parsed) - created
    now = dt_to_text(utcnow())
    for values in parsed:
        # The type id comes from a subquery so types created in this same batch resolve.
        statements.append(
            (
                "INSERT INTO asset (name, type_id, serial, chip_mounted, location, notes,"
                " retired, created_at)"
                " VALUES (?, (SELECT id FROM asset_type WHERE name = ?), ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET"
                "   type_id = excluded.type_id, serial = excluded.serial,"
                "   chip_mounted = excluded.chip_mounted, location = excluded.location,"
                "   notes = excluded.notes, retired = excluded.retired",
                (
                    values["name"],
                    values["type"],
                    values["serial"],
                    values["chip_mounted"],
                    values["location"],
                    values["notes"],
                    1 if values["retired"] else 0,
                    now,
                ),
            )
        )
    try:
        await db.batch(statements)
    except UniqueViolation:
        raise Conflict("The import clashed with existing data and was rolled back.") from None
    return {"created": created, "updated": updated, "new_types": new_types}


async def all_checkouts(db: Database) -> list[dict]:
    rows = await db.query(
        """
        SELECT c.*, a.name AS asset_name
        FROM checkout c JOIN asset a ON a.id = c.asset_id
        ORDER BY c.checked_out_at, c.id
        """
    )
    return [
        checkout_row(row, asset={"id": row["asset_id"], "name": row["asset_name"]}) for row in rows
    ]


# --- FPGA inventory ------------------------------------------------------------
# Admins record which FPGA models exist and how many sit in each server.


async def fpga_types(db: Database) -> list[dict]:
    rows = await db.query("SELECT * FROM fpga_type ORDER BY name")
    return [fpga_type_row(row) for row in rows]


async def get_fpga_type(db: Database, type_id: int) -> dict | None:
    row = await db.query_one("SELECT * FROM fpga_type WHERE id = ?", (type_id,))
    return fpga_type_row(row) if row else None


async def fpga_servers(db: Database) -> list[dict]:
    rows = await db.query("SELECT * FROM fpga_server ORDER BY name")
    return [fpga_server_row(row) for row in rows]


async def get_fpga_server(db: Database, server_id: int) -> dict | None:
    row = await db.query_one("SELECT * FROM fpga_server WHERE id = ?", (server_id,))
    return fpga_server_row(row) if row else None


async def fpga_placements(db: Database) -> dict[tuple[int, int], int]:
    """{(fpga_type_id, server_id): quantity} for every placement with a count."""
    rows = await db.query("SELECT fpga_type_id, server_id, quantity FROM fpga_placement")
    return {(row["fpga_type_id"], row["server_id"]): row["quantity"] for row in rows}


async def fpga_inventory_by_type(db: Database) -> dict[int, list[tuple[dict, int]]]:
    """{fpga_type_id: [(server, quantity), ...]} for showing where each model lives."""
    rows = await db.query(
        """
        SELECT p.fpga_type_id, p.quantity, s.id AS server_id, s.name AS server_name,
               s.notes AS server_notes
        FROM fpga_placement p JOIN fpga_server s ON s.id = p.server_id
        WHERE p.quantity > 0
        ORDER BY s.name
        """
    )
    inventory: dict[int, list[tuple[dict, int]]] = {}
    for row in rows:
        server = fpga_server_row(
            {"id": row["server_id"], "name": row["server_name"], "notes": row["server_notes"]}
        )
        inventory.setdefault(row["fpga_type_id"], []).append((server, row["quantity"]))
    return inventory


async def add_fpga_type(db: Database, name: str) -> dict:
    name = name.strip()
    if not name:
        raise ServiceError("FPGA type name is required.")
    try:
        result = await db.execute("INSERT INTO fpga_type (name) VALUES (?)", (name,))
    except UniqueViolation:
        raise Conflict(f"FPGA type {name!r} already exists.") from None
    return await get_fpga_type(db, result.last_row_id)


async def rename_fpga_type(db: Database, fpga_type: dict, name: str) -> dict:
    name = name.strip()
    if not name:
        raise ServiceError("FPGA type name is required.")
    try:
        await db.execute("UPDATE fpga_type SET name = ? WHERE id = ?", (name, fpga_type["id"]))
    except UniqueViolation:
        raise Conflict(f"FPGA type {name!r} already exists.") from None
    return await get_fpga_type(db, fpga_type["id"])


async def delete_fpga_type(db: Database, fpga_type: dict) -> None:
    booked = await db.value(
        "SELECT COUNT(*) FROM fpga_reservation WHERE fpga_type_id = ?", (fpga_type["id"],)
    )
    if booked:
        raise Conflict(
            f"{fpga_type['name']} is used by {booked} reservation{'s' if booked > 1 else ''}. "
            "Delete those first."
        )
    await db.batch(
        [
            ("DELETE FROM fpga_placement WHERE fpga_type_id = ?", (fpga_type["id"],)),
            ("DELETE FROM fpga_type WHERE id = ?", (fpga_type["id"],)),
        ]
    )


async def add_fpga_server(db: Database, name: str, notes: str = "") -> dict:
    name = name.strip()
    if not name:
        raise ServiceError("Server name is required.")
    try:
        result = await db.execute(
            "INSERT INTO fpga_server (name, notes) VALUES (?, ?)", (name, notes.strip())
        )
    except UniqueViolation:
        raise Conflict(f"Server {name!r} already exists.") from None
    return await get_fpga_server(db, result.last_row_id)


async def rename_fpga_server(db: Database, server: dict, name: str) -> dict:
    name = name.strip()
    if not name:
        raise ServiceError("Server name is required.")
    try:
        await db.execute("UPDATE fpga_server SET name = ? WHERE id = ?", (name, server["id"]))
    except UniqueViolation:
        raise Conflict(f"Server {name!r} already exists.") from None
    return await get_fpga_server(db, server["id"])


async def delete_fpga_server(db: Database, server: dict) -> None:
    booked = await db.value(
        "SELECT COUNT(*) FROM fpga_reservation WHERE server_id = ?", (server["id"],)
    )
    if booked:
        raise Conflict(
            f"{server['name']} is used by {booked} reservation{'s' if booked > 1 else ''}. "
            "Move or delete those first."
        )
    await db.batch(
        [
            ("DELETE FROM fpga_placement WHERE server_id = ?", (server["id"],)),
            ("DELETE FROM fpga_server WHERE id = ?", (server["id"],)),
        ]
    )


async def set_fpga_placements(db: Database, counts: dict[tuple[int, int], int]) -> None:
    """Replace the how-many-where grid. A count of 0 removes the placement."""
    statements: list[tuple[str, tuple]] = []
    for (type_id, server_id), quantity in counts.items():
        if quantity < 0:
            raise ServiceError("Counts can't be negative.")
        if quantity == 0:
            statements.append(
                (
                    "DELETE FROM fpga_placement WHERE fpga_type_id = ? AND server_id = ?",
                    (type_id, server_id),
                )
            )
        else:
            statements.append(
                (
                    "INSERT INTO fpga_placement (fpga_type_id, server_id, quantity)"
                    " VALUES (?, ?, ?)"
                    " ON CONFLICT(fpga_type_id, server_id) DO UPDATE SET"
                    " quantity = excluded.quantity",
                    (type_id, server_id, quantity),
                )
            )
    await db.batch(statements)


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

RESERVATION_SELECT = """
    SELECT r.*, t.name AS fpga_type_name, s.name AS server_name
    FROM fpga_reservation r
    JOIN fpga_type t ON t.id = r.fpga_type_id
    LEFT JOIN fpga_server s ON s.id = r.server_id
"""


async def fpga_reservations(db: Database) -> list[dict]:
    rows = await db.query(RESERVATION_SELECT + " ORDER BY r.start_date, r.id")
    return [fpga_reservation_row(row) for row in rows]


async def get_fpga_reservation(db: Database, reservation_id: int) -> dict | None:
    row = await db.query_one(RESERVATION_SELECT + " WHERE r.id = ?", (reservation_id,))
    return fpga_reservation_row(row) if row else None


def _parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ServiceError(f"{label} must be a valid date.") from None


async def save_fpga_reservation(
    db: Database, reservation: dict | None, user: User, form: dict[str, str]
) -> dict:
    """Create (reservation=None) or update an FPGA reservation from submitted form values.

    Only the person who created a reservation or an admin may edit it.
    """
    if (
        reservation is not None
        and reservation["created_by_email"] != user.email
        and not user.is_admin
    ):
        raise Forbidden("Only the person who made this reservation or an admin can edit it.")

    try:
        fpga_type_id = int(form.get("fpga_type_id", ""))
    except ValueError:
        raise ServiceError("Pick an FPGA type.") from None
    if await get_fpga_type(db, fpga_type_id) is None:
        raise ServiceError("Pick an FPGA type.")

    try:
        server_id = int(form.get("server_id", ""))
    except ValueError:
        raise ServiceError("Pick a server.") from None
    if await get_fpga_server(db, server_id) is None:
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

    special_requests = form.get("special_requests", "").strip()
    if reservation is None:
        result = await db.execute(
            "INSERT INTO fpga_reservation (fpga_type_id, server_id, project, quantity, contact,"
            " special_requests, start_date, end_date, created_by_email, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fpga_type_id,
                server_id,
                project,
                quantity,
                contact,
                special_requests,
                date_to_text(start_date),
                date_to_text(end_date),
                user.email,
                dt_to_text(utcnow()),
            ),
        )
        reservation_id = result.last_row_id
    else:
        await db.execute(
            "UPDATE fpga_reservation SET fpga_type_id = ?, server_id = ?, project = ?,"
            " quantity = ?, contact = ?, special_requests = ?, start_date = ?, end_date = ?"
            " WHERE id = ?",
            (
                fpga_type_id,
                server_id,
                project,
                quantity,
                contact,
                special_requests,
                date_to_text(start_date),
                date_to_text(end_date),
                reservation["id"],
            ),
        )
        reservation_id = reservation["id"]
    return await get_fpga_reservation(db, reservation_id)


async def delete_fpga_reservation(db: Database, reservation: dict, user: User) -> None:
    if reservation["created_by_email"] != user.email and not user.is_admin:
        raise Forbidden("Only the person who made this reservation or an admin can delete it.")
    await db.execute("DELETE FROM fpga_reservation WHERE id = ?", (reservation["id"],))


def _slots_for_type(
    fpga_type_id: int, placements: dict[tuple[int, int], int], servers: dict[int, dict]
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
                    "label": f"{server['name']} #{index}",
                    "booked": [],  # (start, end) stretches already taken
                    "reservations": [],
                }
            )
    slots.sort(key=lambda s: (s["server"]["name"], s["index"]))
    # Spread hues around the wheel, starting near Berkeley blue.
    for position, slot in enumerate(slots):
        slot["hue"] = (205 + round(360 * position / max(len(slots), 1))) % 360
    return slots


def assign_to_slots(reservations: list[dict], slots: list[dict]) -> list[dict]:
    """Place each booking on specific boards; return the ones that didn't fit.

    A booking for 2 FPGAs takes two slots in its server for its whole stretch.
    All-or-nothing: if there aren't enough free boards it goes to the overflow
    row instead of being split across a board it can't actually have.
    """

    def free(slot, r):
        return all(end < r["start_date"] or start > r["end_date"] for start, end in slot["booked"])

    overflow = []
    for r in sorted(reservations, key=lambda r: (r["start_date"], r["id"])):
        candidates = [s for s in slots if s["server"]["id"] == r["server_id"] and free(s, r)]
        if r["server_id"] is None or len(candidates) < r["quantity"]:
            overflow.append(r)
            continue
        for slot in candidates[: r["quantity"]]:
            slot["booked"].append((r["start_date"], r["end_date"]))
            slot["reservations"].append(r)
    return overflow


def _days(start: date, end: date):
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


def oversubscribed(
    reservations: list[dict], placements: dict[tuple[int, int], int]
) -> tuple[set[int], list[str]]:
    """Find reservations that put a server over the number of FPGAs installed in it.

    Returns the ids of the reservations involved plus one readable warning per
    (type, server) stretch. Reservations with no server named are skipped: there's
    nothing to compare them against.
    """
    by_place: dict[tuple[int, int], list[dict]] = {}
    for r in reservations:
        if r["server_id"] is not None:
            by_place.setdefault((r["fpga_type_id"], r["server_id"]), []).append(r)

    flagged: set[int] = set()
    warnings: list[str] = []
    for (type_id, server_id), group in by_place.items():
        capacity = placements.get((type_id, server_id), 0)
        in_use: dict[date, int] = {}
        for r in group:
            for day in _days(r["start_date"], r["end_date"]):
                in_use[day] = in_use.get(day, 0) + r["quantity"]
        over_days = sorted(day for day, total in in_use.items() if total > capacity)
        if not over_days:
            continue
        peak = max(in_use[day] for day in over_days)
        sample = group[0]
        where = sample["server"]["name"] if sample["server"] else "?"
        what = sample["fpga_type"]["name"] if sample["fpga_type"] else "?"
        span = (
            f"{over_days[0]:%b %-d}"
            if len(over_days) == 1
            else f"{over_days[0]:%b %-d}–{over_days[-1]:%b %-d}"
        )
        warnings.append(f"{what} in {where}: {peak} booked of {capacity} installed, {span}.")
        for r in group:
            if any(
                day in in_use and in_use[day] > capacity
                for day in _days(r["start_date"], r["end_date"])
            ):
                flagged.add(r["id"])
    return flagged, sorted(warnings)


async def fpga_timeline(db: Database, window_start: date, window_end: date) -> dict:
    """Timeline data for [window_start, window_end].

    One group per FPGA type. Inside a group there's a row per physical board, each
    with its own hue; the collapsed view stacks those rows as thin bands so a type
    stays one line until someone opens it.
    """
    total_days = (window_end - window_start).days + 1
    all_reservations = await fpga_reservations(db)
    placements = await fpga_placements(db)
    # Over-subscription is judged on the whole booking, not just the visible slice.
    flagged, warnings = oversubscribed(all_reservations, placements)
    servers = {s["id"]: s for s in await fpga_servers(db)}

    def bar(r: dict, hue: int | None) -> dict | None:
        if r["end_date"] < window_start or r["start_date"] > window_end:
            return None
        left_day = max(r["start_date"], window_start)
        right_day = min(r["end_date"], window_end)
        left_pct = (left_day - window_start).days / total_days * 100
        width_pct = ((right_day - window_start).days + 1) / total_days * 100 - left_pct
        return {
            "reservation": r,
            "left_pct": left_pct,
            "width_pct": width_pct,
            "over": r["id"] in flagged,
            "hue": hue,
        }

    by_type: dict[int, list[dict]] = {}
    for r in all_reservations:
        by_type.setdefault(r["fpga_type_id"], []).append(r)

    inventory = await fpga_inventory_by_type(db)
    groups = []
    for fpga_type in await fpga_types(db):
        slots = _slots_for_type(fpga_type["id"], placements, servers)
        overflow = assign_to_slots(by_type.get(fpga_type["id"], []), slots)
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
        installed = inventory.get(fpga_type["id"], [])
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

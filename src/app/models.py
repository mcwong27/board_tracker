"""Row shapes and the conversions between SQL text and Python values.

There is no ORM: D1 is reached through raw SQL, and these helpers turn flat result
rows into the nested dicts the templates expect (`asset.type.name`, and so on —
Jinja resolves dot access on dicts). SQLite has no date types, so datetimes are
stored as 'YYYY-MM-DD HH:MM:SS' and dates as 'YYYY-MM-DD'.
"""

from datetime import UTC, date, datetime
from typing import Any

DT_FORMAT = "%Y-%m-%d %H:%M:%S"

# The FPGA types seeded by migrations/0001_initial.sql.
SEEDED_FPGA_TYPES = (
    "U250",
    "XB10",
    "VCU118",
    "U200",
    "U280",
    "V80",
    "RHS Research Nitefury II",
)


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite has no timezone support)."""
    return datetime.now(UTC).replace(tzinfo=None)


def dt_to_text(value: datetime) -> str:
    return value.strftime(DT_FORMAT)


def date_to_text(value: date) -> str:
    return value.isoformat()


def text_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    # Tolerate both ' ' and 'T' separators, and a trailing fractional part.
    cleaned = value.replace("T", " ").split(".")[0]
    return datetime.strptime(cleaned, DT_FORMAT)


def text_to_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def asset_type_row(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "name": row["name"], "sort_order": row.get("sort_order", 100)}


def asset_row(row: dict[str, Any]) -> dict[str, Any]:
    """Expects an asset joined to asset_type with the type's name as `type_name`."""
    return {
        "id": row["id"],
        "name": row["name"],
        "type_id": row["type_id"],
        "type": {"id": row["type_id"], "name": row.get("type_name", "")},
        "serial": row.get("serial", ""),
        "chip_mounted": row.get("chip_mounted", ""),
        "location": row.get("location", ""),
        "notes": row.get("notes", ""),
        "retired": bool(row.get("retired", 0)),
        "created_at": text_to_dt(row.get("created_at")),
    }


def checkout_row(row: dict[str, Any], asset: dict[str, Any] | None = None) -> dict[str, Any]:
    returned_at = text_to_dt(row.get("returned_at"))
    checkout = {
        "id": row["id"],
        "asset_id": row["asset_id"],
        "user_email": row["user_email"],
        "user_name": row.get("user_name", ""),
        "checked_out_at": text_to_dt(row.get("checked_out_at")),
        "returned_at": returned_at,
        "returned_by": row.get("returned_by"),
        "notes": row.get("notes", ""),
        "active": returned_at is None,
    }
    if asset is not None:
        checkout["asset"] = asset
    return checkout


def fpga_type_row(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "name": row["name"]}


def fpga_server_row(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "name": row["name"], "notes": row.get("notes", "")}


def fpga_reservation_row(row: dict[str, Any]) -> dict[str, Any]:
    """Expects the reservation joined to its type and (optional) server."""
    server = None
    if row.get("server_id") is not None:
        server = {"id": row["server_id"], "name": row.get("server_name", "")}
    return {
        "id": row["id"],
        "fpga_type_id": row["fpga_type_id"],
        "fpga_type": {"id": row["fpga_type_id"], "name": row.get("fpga_type_name", "")},
        "server_id": row.get("server_id"),
        "server": server,
        "project": row["project"],
        "quantity": row.get("quantity", 1),
        "contact": row.get("contact", ""),
        "special_requests": row.get("special_requests", ""),
        "start_date": text_to_date(row["start_date"]),
        "end_date": text_to_date(row["end_date"]),
        "created_by_email": row["created_by_email"],
        "created_at": text_to_dt(row.get("created_at")),
    }

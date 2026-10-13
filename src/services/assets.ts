/**
 * Assets and checkouts: the business rules, and the SQL that enforces them.
 *
 * Ported from the Python services layer; the SQL is unchanged because D1 is SQLite.
 */

import { Db, UniqueViolation } from "../db";
import { nowText } from "../dates";
import type { Asset, AssetType, Checkout, User } from "../types";
import { Conflict, Forbidden, ServiceError } from "../types";

const ASSET_COLUMNS = `
  a.id, a.name, a.type_id, a.serial, a.chip_mounted, a.location, a.notes,
  a.retired, a.created_at, t.name AS type_name
`;

type AssetRow = {
  id: number;
  name: string;
  type_id: number;
  serial: string;
  chip_mounted: string;
  location: string;
  notes: string;
  retired: number;
  created_at: string;
  type_name: string;
};

function toAsset(row: AssetRow): Asset {
  return {
    id: row.id,
    name: row.name,
    type_id: row.type_id,
    type: { id: row.type_id, name: row.type_name },
    serial: row.serial ?? "",
    chip_mounted: row.chip_mounted ?? "",
    location: row.location ?? "",
    notes: row.notes ?? "",
    retired: Boolean(row.retired),
    created_at: row.created_at,
  };
}

type CheckoutRow = {
  id: number;
  asset_id: number;
  user_email: string;
  user_name: string;
  checked_out_at: string;
  returned_at: string | null;
  returned_by: string | null;
  notes: string;
};

function toCheckout(row: CheckoutRow): Checkout {
  return {
    id: row.id,
    asset_id: row.asset_id,
    user_email: row.user_email,
    user_name: row.user_name ?? "",
    checked_out_at: row.checked_out_at,
    returned_at: row.returned_at,
    returned_by: row.returned_by,
    notes: row.notes ?? "",
    active: row.returned_at === null,
  };
}

export async function assetTypes(db: Db): Promise<AssetType[]> {
  return db.query<AssetType>("SELECT * FROM asset_type ORDER BY sort_order, name");
}

export async function getAssetType(db: Db, id: number): Promise<AssetType | null> {
  return db.queryOne<AssetType>("SELECT * FROM asset_type WHERE id = ?", [id]);
}

export async function getAsset(db: Db, id: number): Promise<Asset | null> {
  const row = await db.queryOne<AssetRow>(
    `SELECT ${ASSET_COLUMNS} FROM asset a JOIN asset_type t ON t.id = a.type_id WHERE a.id = ?`,
    [id],
  );
  return row ? toAsset(row) : null;
}

/** Assets paired with their active checkout (null when available). */
export async function assetsWithStatus(
  db: Db,
  opts: { typeId?: number | null; includeRetired?: boolean } = {},
): Promise<Array<[Asset, Checkout | null]>> {
  const where: string[] = [];
  const params: unknown[] = [];
  if (!opts.includeRetired) where.push("a.retired = 0");
  if (opts.typeId != null) {
    where.push("a.type_id = ?");
    params.push(opts.typeId);
  }
  const sql = `
    SELECT ${ASSET_COLUMNS},
           c.id AS c_id, c.asset_id AS c_asset_id, c.user_email AS c_user_email,
           c.user_name AS c_user_name, c.checked_out_at AS c_checked_out_at,
           c.returned_at AS c_returned_at, c.returned_by AS c_returned_by,
           c.notes AS c_notes
    FROM asset a
    JOIN asset_type t ON t.id = a.type_id
    LEFT JOIN checkout c ON c.asset_id = a.id AND c.returned_at IS NULL
    ${where.length ? `WHERE ${where.join(" AND ")}` : ""}
    ORDER BY t.sort_order, t.name, a.name
  `;
  const rows = await db.query<AssetRow & Record<string, unknown>>(sql, params);
  return rows.map((row) => {
    const checkout =
      row["c_id"] == null
        ? null
        : toCheckout({
            id: row["c_id"] as number,
            asset_id: row["c_asset_id"] as number,
            user_email: row["c_user_email"] as string,
            user_name: row["c_user_name"] as string,
            checked_out_at: row["c_checked_out_at"] as string,
            returned_at: row["c_returned_at"] as string | null,
            returned_by: row["c_returned_by"] as string | null,
            notes: row["c_notes"] as string,
          });
    return [toAsset(row), checkout] as [Asset, Checkout | null];
  });
}

export async function activeCheckout(db: Db, assetId: number): Promise<Checkout | null> {
  const row = await db.queryOne<CheckoutRow>(
    "SELECT * FROM checkout WHERE asset_id = ? AND returned_at IS NULL",
    [assetId],
  );
  return row ? toCheckout(row) : null;
}

export async function userCheckouts(db: Db, email: string): Promise<Checkout[]> {
  const rows = await db.query<CheckoutRow & { asset_name: string; type_name: string; type_id: number }>(
    `SELECT c.*, a.name AS asset_name, a.type_id AS type_id, t.name AS type_name
     FROM checkout c
     JOIN asset a ON a.id = c.asset_id
     JOIN asset_type t ON t.id = a.type_id
     WHERE c.user_email = ?
     ORDER BY c.checked_out_at DESC`,
    [email],
  );
  return rows.map((row) => ({
    ...toCheckout(row),
    asset: {
      id: row.asset_id,
      name: row.asset_name,
      type: { id: row.type_id, name: row.type_name },
    },
  }));
}

export async function assetHistory(db: Db, assetId: number): Promise<Checkout[]> {
  const rows = await db.query<CheckoutRow>(
    "SELECT * FROM checkout WHERE asset_id = ? ORDER BY checked_out_at DESC, id DESC",
    [assetId],
  );
  return rows.map(toCheckout);
}

export async function checkoutAsset(
  db: Db,
  asset: Asset,
  user: User,
  notes = "",
): Promise<Checkout> {
  if (asset.retired) {
    throw new Conflict(`${asset.name} is retired and can't be checked out.`);
  }
  try {
    await db.run(
      `INSERT INTO checkout (asset_id, user_email, user_name, checked_out_at, notes)
       VALUES (?, ?, ?, ?, ?)`,
      [asset.id, user.email, user.name, nowText(), notes.trim()],
    );
  } catch (error) {
    if (!(error instanceof UniqueViolation)) throw error;
    // The partial unique index rejected a second active checkout (possibly a race).
    const holder = await activeCheckout(db, asset.id);
    const who = holder ? ` by ${holder.user_name || holder.user_email}` : "";
    throw new Conflict(`${asset.name} is already checked out${who}.`);
  }
  return (await activeCheckout(db, asset.id))!;
}

/** Return an asset. Only the holder or an admin may do this. */
export async function returnAsset(db: Db, asset: Asset, user: User): Promise<Checkout> {
  const checkout = await activeCheckout(db, asset.id);
  if (!checkout) throw new Conflict(`${asset.name} isn't checked out.`);
  if (checkout.user_email !== user.email && !user.isAdmin) {
    throw new Forbidden("Only the person who has this asset or an admin can return it.");
  }
  // Conditional update so two simultaneous returns can't both succeed.
  const result = await db.run(
    "UPDATE checkout SET returned_at = ?, returned_by = ? WHERE id = ? AND returned_at IS NULL",
    [nowText(), user.email, checkout.id],
  );
  if (result.meta.changes !== 1) throw new Conflict(`${asset.name} was already returned.`);
  const row = await db.queryOne<CheckoutRow>("SELECT * FROM checkout WHERE id = ?", [checkout.id]);
  return toCheckout(row!);
}

export const ASSET_FIELDS = ["name", "type_id", "serial", "chip_mounted", "location", "notes"];

/** Create (asset=null) or update an asset from submitted form values. */
export async function saveAsset(
  db: Db,
  asset: Asset | null,
  form: Record<string, string>,
): Promise<Asset> {
  const name = (form["name"] ?? "").trim();
  if (!name) throw new ServiceError("Name is required.");
  const typeId = Number.parseInt(form["type_id"] ?? "", 10);
  if (!Number.isInteger(typeId) || !(await getAssetType(db, typeId))) {
    throw new ServiceError("Pick an asset type.");
  }
  const text = (key: string) => (form[key] ?? "").trim();
  try {
    if (!asset) {
      const result = await db.run(
        `INSERT INTO asset (name, type_id, serial, chip_mounted, location, notes, retired, created_at)
         VALUES (?, ?, ?, ?, ?, ?, 0, ?)`,
        [name, typeId, text("serial"), text("chip_mounted"), text("location"), text("notes"), nowText()],
      );
      return (await getAsset(db, result.meta.last_row_id as number))!;
    }
    await db.run(
      `UPDATE asset SET name = ?, type_id = ?, serial = ?, chip_mounted = ?, location = ?, notes = ?
       WHERE id = ?`,
      [name, typeId, text("serial"), text("chip_mounted"), text("location"), text("notes"), asset.id],
    );
    return (await getAsset(db, asset.id))!;
  } catch (error) {
    if (error instanceof UniqueViolation) {
      throw new Conflict(`An asset named '${name}' already exists.`);
    }
    throw error;
  }
}

export async function setRetired(db: Db, asset: Asset, retired: boolean): Promise<void> {
  if (retired && (await activeCheckout(db, asset.id))) {
    throw new Conflict(`${asset.name} is checked out. Return it before retiring it.`);
  }
  await db.run("UPDATE asset SET retired = ? WHERE id = ?", [retired ? 1 : 0, asset.id]);
}

export async function addAssetType(db: Db, name: string): Promise<AssetType> {
  const clean = name.trim();
  if (!clean) throw new ServiceError("Type name is required.");
  try {
    const result = await db.run("INSERT INTO asset_type (name) VALUES (?)", [clean]);
    return (await getAssetType(db, result.meta.last_row_id as number))!;
  } catch (error) {
    if (error instanceof UniqueViolation) throw new Conflict(`Type '${clean}' already exists.`);
    throw error;
  }
}

export async function renameAssetType(db: Db, type: AssetType, name: string): Promise<AssetType> {
  const clean = name.trim();
  if (!clean) throw new ServiceError("Type name is required.");
  try {
    await db.run("UPDATE asset_type SET name = ? WHERE id = ?", [clean, type.id]);
    return (await getAssetType(db, type.id))!;
  } catch (error) {
    if (error instanceof UniqueViolation) throw new Conflict(`Type '${clean}' already exists.`);
    throw error;
  }
}

export async function deleteAssetType(db: Db, type: AssetType): Promise<void> {
  const inUse = (await db.value<number>("SELECT COUNT(*) FROM asset WHERE type_id = ?", [type.id])) ?? 0;
  if (inUse) {
    throw new Conflict(
      `${type.name} is used by ${inUse} asset${inUse > 1 ? "s" : ""}. Move or delete them first.`,
    );
  }
  await db.run("DELETE FROM asset_type WHERE id = ?", [type.id]);
}

export async function assetCountsByType(db: Db): Promise<Map<number, number>> {
  const rows = await db.query<{ type_id: number; n: number }>(
    "SELECT type_id, COUNT(*) AS n FROM asset GROUP BY type_id",
  );
  return new Map(rows.map((r) => [r.type_id, r.n]));
}

export async function allCheckouts(db: Db): Promise<Checkout[]> {
  const rows = await db.query<CheckoutRow & { asset_name: string }>(
    `SELECT c.*, a.name AS asset_name FROM checkout c JOIN asset a ON a.id = c.asset_id
     ORDER BY c.checked_out_at, c.id`,
  );
  return rows.map((row) => ({
    ...toCheckout(row),
    asset: { id: row.asset_id, name: row.asset_name },
  }));
}

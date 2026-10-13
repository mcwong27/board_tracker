/**
 * CSV export and import for assets.
 *
 * The importer reads the same columns the exporter writes, so a downloaded file can be
 * edited in a spreadsheet and uploaded back. Rows match existing assets by name:
 * update or create, never delete. The whole file is rejected if any row is bad.
 */

import { Db, UniqueViolation } from "../db";
import { nowText } from "../dates";
import type { Asset, Checkout } from "../types";
import { Conflict, ServiceError } from "../types";

/** Columns the importer reads; everything else in an exported file is derived. */
const IMPORT_COLUMNS = ["name", "type", "serial", "chip_mounted", "location", "notes", "retired"];
const TRUTHY = new Set(["yes", "true", "1", "y"]);
const FALSEY = new Set(["no", "false", "0", "n", ""]);

/** Undo the leading apostrophe the exporter adds to spreadsheet-formula text. */
function uncell(value: string | undefined): string {
  const text = (value ?? "").trim();
  return text.startsWith("'") ? text.slice(1) : text;
}

/** Neutralize spreadsheet formula injection from user-entered text. */
function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  let text = String(value);
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(header: string[], rows: unknown[][]): string {
  return [header.join(","), ...rows.map((row) => row.map(cell).join(","))].join("\r\n");
}

/** A small RFC4180 parser: quoted fields, doubled quotes, CRLF or LF. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else quoted = false;
      } else field += char;
      continue;
    }
    if (char === '"') quoted = true;
    else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else field += char;
  }
  if (field !== "" || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

export type ImportSummary = { created: number; updated: number; newTypes: string[] };

export async function importAssets(db: Db, content: string): Promise<ImportSummary> {
  const rows = parseCsv(content.replace(/^﻿/, ""));
  const header = rows.shift();
  if (!header || header.every((h) => !h.trim())) throw new ServiceError("That file is empty.");

  const columns = header.map((h) => h.trim().toLowerCase());
  const missing = ["name", "type"].filter((c) => !columns.includes(c));
  if (missing.length) {
    throw new ServiceError(
      `The CSV is missing the ${missing.sort().join(", ")} column${missing.length > 1 ? "s" : ""}. ` +
        "Export the assets CSV to see the expected format.",
    );
  }

  const parsed: Array<Record<string, string> & { retiredFlag: boolean }> = [];
  const errors: string[] = [];
  const seen = new Set<string>();
  rows.forEach((cells, index) => {
    const line = index + 2; // line 1 is the header
    const values: Record<string, string> = {};
    for (const column of IMPORT_COLUMNS) {
      const at = columns.indexOf(column);
      values[column] = at === -1 ? "" : uncell(cells[at]);
    }
    if (Object.values(values).every((v) => !v)) return; // blank line
    const name = values["name"] ?? "";
    if (!name) {
      errors.push(`Row ${line}: name is required.`);
      return;
    }
    if (seen.has(name.toLowerCase())) {
      errors.push(`Row ${line}: ${name} appears more than once in the file.`);
      return;
    }
    seen.add(name.toLowerCase());
    if (!values["type"]) {
      errors.push(`Row ${line}: type is required.`);
      return;
    }
    const retired = (values["retired"] ?? "").toLowerCase();
    if (!TRUTHY.has(retired) && !FALSEY.has(retired)) {
      errors.push(`Row ${line}: retired should be yes or no, not '${values["retired"]}'.`);
      return;
    }
    parsed.push({ ...values, retiredFlag: TRUTHY.has(retired) } as never);
  });

  if (errors.length) {
    const shown = errors.slice(0, 10);
    if (errors.length > shown.length) shown.push(`…and ${errors.length - shown.length} more.`);
    throw new ServiceError(`Nothing was imported:\n${shown.join("\n")}`);
  }
  if (!parsed.length) throw new ServiceError("That file has no asset rows.");

  const existingTypes = new Set(
    (await db.query<{ name: string }>("SELECT name FROM asset_type")).map((r) => r.name.toLowerCase()),
  );
  const existingAssets = new Set(
    (await db.query<{ name: string }>("SELECT name FROM asset")).map((r) => r.name.toLowerCase()),
  );

  const statements: Array<[string, unknown[]]> = [];
  const newTypes: string[] = [];
  for (const values of parsed) {
    const type = values["type"]!;
    if (!existingTypes.has(type.toLowerCase())) {
      existingTypes.add(type.toLowerCase());
      newTypes.push(type);
      statements.push(["INSERT OR IGNORE INTO asset_type (name) VALUES (?)", [type]]);
    }
  }
  const created = parsed.filter((v) => !existingAssets.has(v["name"]!.toLowerCase())).length;
  const now = nowText();
  for (const values of parsed) {
    // The type id comes from a subquery so types created in this same batch resolve.
    statements.push([
      `INSERT INTO asset (name, type_id, serial, chip_mounted, location, notes, retired, created_at)
       VALUES (?, (SELECT id FROM asset_type WHERE name = ?), ?, ?, ?, ?, ?, ?)
       ON CONFLICT(name) DO UPDATE SET
         type_id = excluded.type_id, serial = excluded.serial,
         chip_mounted = excluded.chip_mounted, location = excluded.location,
         notes = excluded.notes, retired = excluded.retired`,
      [
        values["name"],
        values["type"],
        values["serial"] ?? "",
        values["chip_mounted"] ?? "",
        values["location"] ?? "",
        values["notes"] ?? "",
        values.retiredFlag ? 1 : 0,
        now,
      ],
    ]);
  }
  try {
    await db.batch(statements);
  } catch (error) {
    if (error instanceof UniqueViolation) {
      throw new Conflict("The import clashed with existing data and was rolled back.");
    }
    throw error;
  }
  return { created, updated: parsed.length - created, newTypes };
}

export function assetsCsv(rows: Array<[Asset, Checkout | null]>): string {
  const header = [
    "id", "name", "type", "serial", "chip_mounted", "location", "notes", "retired",
    "status", "holder_email", "holder_name", "checked_out_at", "created_at",
  ];
  return toCsv(
    header,
    rows.map(([a, c]) => [
      a.id, a.name, a.type.name, a.serial, a.chip_mounted, a.location, a.notes,
      a.retired ? "yes" : "no",
      a.retired ? "retired" : c ? "checked out" : "available",
      c?.user_email ?? null, c?.user_name ?? null, c?.checked_out_at ?? null, a.created_at,
    ]),
  );
}

export function checkoutsCsv(checkouts: Checkout[]): string {
  const header = [
    "id", "asset_id", "asset_name", "user_email", "user_name",
    "checked_out_at", "returned_at", "returned_by", "notes",
  ];
  return toCsv(
    header,
    checkouts.map((c) => [
      c.id, c.asset_id, c.asset?.name ?? "", c.user_email, c.user_name,
      c.checked_out_at, c.returned_at, c.returned_by, c.notes,
    ]),
  );
}

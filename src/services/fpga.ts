/**
 * FPGA inventory and reservations.
 *
 * Admins record which models exist and how many sit in each server. Reservations are
 * a shared calendar, not an allocator: booking more than a server holds is allowed
 * but flagged. Each physical board gets its own timeline row and its own hue; boards
 * are derived from the counts, so 4 U250s in a server become "#1".."#4".
 */

import { Db, UniqueViolation } from "../db";
import { addDays, daysBetween, eachDay, isValidDate, nowText, shortDate, todayIso } from "../dates";
import type {
  Bar,
  Capacity,
  FpgaReservation,
  FpgaServer,
  FpgaType,
  FpgaUnit,
  Timeline,
  TimelineGroup,
  TimelineRow,
  User,
} from "../types";
import { Conflict, Forbidden, ServiceError } from "../types";

export const capacityKey = (typeId: number, serverId: number) => `${typeId}:${serverId}`;

export async function fpgaTypes(db: Db): Promise<FpgaType[]> {
  return db.query<FpgaType>("SELECT * FROM fpga_type ORDER BY name");
}

export async function getFpgaType(db: Db, id: number): Promise<FpgaType | null> {
  return db.queryOne<FpgaType>("SELECT * FROM fpga_type WHERE id = ?", [id]);
}

export async function fpgaServers(db: Db): Promise<FpgaServer[]> {
  return db.query<FpgaServer>("SELECT * FROM fpga_server ORDER BY name");
}

export async function getFpgaServer(db: Db, id: number): Promise<FpgaServer | null> {
  return db.queryOne<FpgaServer>("SELECT * FROM fpga_server WHERE id = ?", [id]);
}

type UnitRow = {
  id: number;
  fpga_type_id: number;
  server_id: number;
  serial: string | null;
  created_at: string;
  server_name: string;
};

function toUnit(row: UnitRow): FpgaUnit {
  return {
    id: row.id,
    fpga_type_id: row.fpga_type_id,
    server_id: row.server_id,
    server: { id: row.server_id, name: row.server_name },
    serial: row.serial,
    created_at: row.created_at,
  };
}

/** Every board, ordered the way the admin page and the timeline show them. */
export async function fpgaUnits(db: Db): Promise<FpgaUnit[]> {
  const rows = await db.query<UnitRow>(
    `SELECT u.*, s.name AS server_name
     FROM fpga_unit u JOIN fpga_server s ON s.id = u.server_id
     ORDER BY s.name, u.id`,
  );
  return rows.map(toUnit);
}

export async function getFpgaUnit(db: Db, id: number): Promise<FpgaUnit | null> {
  const row = await db.queryOne<UnitRow>(
    `SELECT u.*, s.name AS server_name
     FROM fpga_unit u JOIN fpga_server s ON s.id = u.server_id WHERE u.id = ?`,
    [id],
  );
  return row ? toUnit(row) : null;
}

/** How many boards of each model are in each server — derived from the boards. */
export async function fpgaCapacity(db: Db): Promise<Capacity> {
  const rows = await db.query<{ fpga_type_id: number; server_id: number; n: number }>(
    "SELECT fpga_type_id, server_id, COUNT(*) AS n FROM fpga_unit GROUP BY fpga_type_id, server_id",
  );
  return new Map(rows.map((r) => [capacityKey(r.fpga_type_id, r.server_id), r.n]));
}

/** A blank serial is stored as NULL so the unique index ignores it. */
function normalizeSerial(serial: string | undefined | null): string | null {
  const clean = (serial ?? "").trim();
  return clean ? clean : null;
}

export async function addFpgaUnit(
  db: Db,
  typeId: number,
  serverId: number,
  serial?: string,
): Promise<FpgaUnit> {
  if (!(await getFpgaType(db, typeId))) throw new ServiceError("Pick an FPGA type.");
  if (!(await getFpgaServer(db, serverId))) throw new ServiceError("Pick a server.");
  try {
    const result = await db.run(
      "INSERT INTO fpga_unit (fpga_type_id, server_id, serial, created_at) VALUES (?, ?, ?, ?)",
      [typeId, serverId, normalizeSerial(serial), nowText()],
    );
    return (await getFpgaUnit(db, result.meta.last_row_id as number))!;
  } catch (error) {
    if (error instanceof UniqueViolation) {
      throw new Conflict(`Serial '${serial?.trim()}' is already on another board.`);
    }
    throw error;
  }
}

export async function setFpgaUnitSerial(db: Db, unit: FpgaUnit, serial: string): Promise<FpgaUnit> {
  try {
    await db.run("UPDATE fpga_unit SET serial = ? WHERE id = ?", [normalizeSerial(serial), unit.id]);
  } catch (error) {
    if (error instanceof UniqueViolation) {
      throw new Conflict(`Serial '${serial.trim()}' is already on another board.`);
    }
    throw error;
  }
  return (await getFpgaUnit(db, unit.id))!;
}

export async function deleteFpgaUnit(db: Db, unit: FpgaUnit): Promise<void> {
  await db.run("DELETE FROM fpga_unit WHERE id = ?", [unit.id]);
}

/** fpgaTypeId -> [(server, quantity)], for showing where each model lives. */
export async function fpgaInventoryByType(db: Db): Promise<Map<number, Array<[FpgaServer, number]>>> {
  const rows = await db.query<{
    fpga_type_id: number;
    quantity: number;
    server_id: number;
    server_name: string;
    server_notes: string;
  }>(
    `SELECT u.fpga_type_id, COUNT(*) AS quantity, s.id AS server_id, s.name AS server_name,
            s.notes AS server_notes
     FROM fpga_unit u JOIN fpga_server s ON s.id = u.server_id
     GROUP BY u.fpga_type_id, s.id
     ORDER BY s.name`,
  );
  const inventory = new Map<number, Array<[FpgaServer, number]>>();
  for (const row of rows) {
    const server: FpgaServer = { id: row.server_id, name: row.server_name, notes: row.server_notes ?? "" };
    const list = inventory.get(row.fpga_type_id) ?? [];
    list.push([server, row.quantity]);
    inventory.set(row.fpga_type_id, list);
  }
  return inventory;
}

export async function addFpgaType(db: Db, name: string): Promise<FpgaType> {
  const clean = name.trim();
  if (!clean) throw new ServiceError("FPGA type name is required.");
  try {
    const result = await db.run("INSERT INTO fpga_type (name) VALUES (?)", [clean]);
    return (await getFpgaType(db, result.meta.last_row_id as number))!;
  } catch (error) {
    if (error instanceof UniqueViolation) throw new Conflict(`FPGA type '${clean}' already exists.`);
    throw error;
  }
}

export async function renameFpgaType(db: Db, type: FpgaType, name: string): Promise<FpgaType> {
  const clean = name.trim();
  if (!clean) throw new ServiceError("FPGA type name is required.");
  try {
    await db.run("UPDATE fpga_type SET name = ? WHERE id = ?", [clean, type.id]);
    return (await getFpgaType(db, type.id))!;
  } catch (error) {
    if (error instanceof UniqueViolation) throw new Conflict(`FPGA type '${clean}' already exists.`);
    throw error;
  }
}

export async function deleteFpgaType(db: Db, type: FpgaType): Promise<void> {
  const booked =
    (await db.value<number>("SELECT COUNT(*) FROM fpga_reservation WHERE fpga_type_id = ?", [type.id])) ?? 0;
  if (booked) {
    throw new Conflict(
      `${type.name} is used by ${booked} reservation${booked > 1 ? "s" : ""}. Delete those first.`,
    );
  }
  // No reservations reference it, so its boards go too.
  await db.batch([
    ["DELETE FROM fpga_unit WHERE fpga_type_id = ?", [type.id]],
    ["DELETE FROM fpga_type WHERE id = ?", [type.id]],
  ]);
}

export async function addFpgaServer(db: Db, name: string, notes = ""): Promise<FpgaServer> {
  const clean = name.trim();
  if (!clean) throw new ServiceError("Server name is required.");
  try {
    const result = await db.run("INSERT INTO fpga_server (name, notes) VALUES (?, ?)", [
      clean,
      notes.trim(),
    ]);
    return (await getFpgaServer(db, result.meta.last_row_id as number))!;
  } catch (error) {
    if (error instanceof UniqueViolation) throw new Conflict(`Server '${clean}' already exists.`);
    throw error;
  }
}

export async function renameFpgaServer(db: Db, server: FpgaServer, name: string): Promise<FpgaServer> {
  const clean = name.trim();
  if (!clean) throw new ServiceError("Server name is required.");
  try {
    await db.run("UPDATE fpga_server SET name = ? WHERE id = ?", [clean, server.id]);
    return (await getFpgaServer(db, server.id))!;
  } catch (error) {
    if (error instanceof UniqueViolation) throw new Conflict(`Server '${clean}' already exists.`);
    throw error;
  }
}

export async function deleteFpgaServer(db: Db, server: FpgaServer): Promise<void> {
  const booked =
    (await db.value<number>("SELECT COUNT(*) FROM fpga_reservation WHERE server_id = ?", [server.id])) ?? 0;
  if (booked) {
    throw new Conflict(
      `${server.name} is used by ${booked} reservation${booked > 1 ? "s" : ""}. Move or delete those first.`,
    );
  }
  // No reservations reference it, so its boards go too.
  await db.batch([
    ["DELETE FROM fpga_unit WHERE server_id = ?", [server.id]],
    ["DELETE FROM fpga_server WHERE id = ?", [server.id]],
  ]);
}

export const FPGA_FIELDS = [
  "fpga_type_id",
  "server_id",
  "project",
  "quantity",
  "contact",
  "special_requests",
  "start_date",
  "end_date",
];

const RESERVATION_SELECT = `
  SELECT r.*, t.name AS fpga_type_name, s.name AS server_name
  FROM fpga_reservation r
  JOIN fpga_type t ON t.id = r.fpga_type_id
  LEFT JOIN fpga_server s ON s.id = r.server_id
`;

type ReservationRow = {
  id: number;
  fpga_type_id: number;
  server_id: number | null;
  project: string;
  quantity: number;
  contact: string;
  special_requests: string;
  start_date: string;
  end_date: string;
  created_by_email: string;
  created_at: string;
  fpga_type_name: string;
  server_name: string | null;
};

function toReservation(row: ReservationRow): FpgaReservation {
  return {
    id: row.id,
    fpga_type_id: row.fpga_type_id,
    fpga_type: { id: row.fpga_type_id, name: row.fpga_type_name },
    server_id: row.server_id,
    server: row.server_id == null ? null : { id: row.server_id, name: row.server_name ?? "" },
    project: row.project,
    quantity: row.quantity,
    contact: row.contact ?? "",
    special_requests: row.special_requests ?? "",
    start_date: row.start_date,
    end_date: row.end_date,
    created_by_email: row.created_by_email,
    created_at: row.created_at,
  };
}

export async function fpgaReservations(db: Db): Promise<FpgaReservation[]> {
  const rows = await db.query<ReservationRow>(`${RESERVATION_SELECT} ORDER BY r.start_date, r.id`);
  return rows.map(toReservation);
}

export async function getFpgaReservation(db: Db, id: number): Promise<FpgaReservation | null> {
  const row = await db.queryOne<ReservationRow>(`${RESERVATION_SELECT} WHERE r.id = ?`, [id]);
  return row ? toReservation(row) : null;
}

function parseDate(value: string, label: string): string {
  if (!isValidDate(value)) throw new ServiceError(`${label} must be a valid date.`);
  return value;
}

/** Create (reservation=null) or update. Only the creator or an admin may edit. */
export async function saveFpgaReservation(
  db: Db,
  reservation: FpgaReservation | null,
  user: User,
  form: Record<string, string>,
): Promise<FpgaReservation> {
  if (reservation && reservation.created_by_email !== user.email && !user.isAdmin) {
    throw new Forbidden("Only the person who made this reservation or an admin can edit it.");
  }
  const typeId = Number.parseInt(form["fpga_type_id"] ?? "", 10);
  if (!Number.isInteger(typeId) || !(await getFpgaType(db, typeId))) {
    throw new ServiceError("Pick an FPGA type.");
  }
  const serverId = Number.parseInt(form["server_id"] ?? "", 10);
  if (!Number.isInteger(serverId) || !(await getFpgaServer(db, serverId))) {
    throw new ServiceError("Pick a server.");
  }
  const project = (form["project"] ?? "").trim();
  if (!project) throw new ServiceError("Project is required.");
  const contact = (form["contact"] ?? "").trim();
  if (!contact) throw new ServiceError("Username / point of contact is required.");
  const quantity = Number.parseInt(form["quantity"] ?? "", 10);
  if (!Number.isInteger(quantity)) throw new ServiceError("Number of FPGAs must be a whole number.");
  if (quantity < 1) throw new ServiceError("Number of FPGAs must be at least 1.");
  const startDate = parseDate(form["start_date"] ?? "", "Start date");
  const endDate = parseDate(form["end_date"] ?? "", "End date");
  if (endDate < startDate) throw new ServiceError("End date can't be before start date.");
  const specialRequests = (form["special_requests"] ?? "").trim();

  if (!reservation) {
    const result = await db.run(
      `INSERT INTO fpga_reservation (fpga_type_id, server_id, project, quantity, contact,
         special_requests, start_date, end_date, created_by_email, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [typeId, serverId, project, quantity, contact, specialRequests, startDate, endDate,
       user.email, nowText()],
    );
    return (await getFpgaReservation(db, result.meta.last_row_id as number))!;
  }
  await db.run(
    `UPDATE fpga_reservation SET fpga_type_id = ?, server_id = ?, project = ?, quantity = ?,
       contact = ?, special_requests = ?, start_date = ?, end_date = ? WHERE id = ?`,
    [typeId, serverId, project, quantity, contact, specialRequests, startDate, endDate, reservation.id],
  );
  return (await getFpgaReservation(db, reservation.id))!;
}

export async function deleteFpgaReservation(
  db: Db,
  reservation: FpgaReservation,
  user: User,
): Promise<void> {
  if (reservation.created_by_email !== user.email && !user.isAdmin) {
    throw new Forbidden("Only the person who made this reservation or an admin can delete it.");
  }
  await db.run("DELETE FROM fpga_reservation WHERE id = ?", [reservation.id]);
}

type Slot = {
  unit: FpgaUnit;
  server: { id: number; name: string };
  label: string;
  hue: number;
  booked: Array<[string, string]>;
  reservations: FpgaReservation[];
};

/**
 * One slot per physical board. A board keeps its identity when others are added or
 * removed, so its row and hue stay put. Boards with a serial are labelled by it;
 * the rest fall back to their position within the server.
 */
export function slotsForType(typeId: number, units: FpgaUnit[]): Slot[] {
  const mine = units
    .filter((unit) => unit.fpga_type_id === typeId)
    .sort((a, b) => a.server.name.localeCompare(b.server.name) || a.id - b.id);

  const seenPerServer = new Map<number, number>();
  const slots = mine.map((unit) => {
    const position = (seenPerServer.get(unit.server_id) ?? 0) + 1;
    seenPerServer.set(unit.server_id, position);
    return {
      unit,
      server: unit.server,
      label: unit.serial
        ? `${unit.server.name} · ${unit.serial}`
        : `${unit.server.name} #${position}`,
      hue: 0,
      booked: [] as Array<[string, string]>,
      reservations: [] as FpgaReservation[],
    };
  });
  // Spread hues around the wheel, starting near Berkeley blue.
  slots.forEach((slot, position) => {
    slot.hue = (205 + Math.round((360 * position) / Math.max(slots.length, 1))) % 360;
  });
  return slots;
}

/**
 * Place each booking on specific boards; return the ones that didn't fit. A booking for
 * 2 takes two slots in its server for its whole stretch. All-or-nothing: one that
 * doesn't fit goes to the overflow row rather than onto a board it can't have.
 */
export function assignToSlots(reservations: FpgaReservation[], slots: Slot[]): FpgaReservation[] {
  const free = (slot: Slot, r: FpgaReservation) =>
    slot.booked.every(([start, end]) => end < r.start_date || start > r.end_date);

  const overflow: FpgaReservation[] = [];
  const ordered = [...reservations].sort(
    (a, b) => a.start_date.localeCompare(b.start_date) || a.id - b.id,
  );
  for (const r of ordered) {
    const candidates = slots.filter((s) => s.server.id === r.server_id && free(s, r));
    if (r.server_id == null || candidates.length < r.quantity) {
      overflow.push(r);
      continue;
    }
    for (const slot of candidates.slice(0, r.quantity)) {
      slot.booked.push([r.start_date, r.end_date]);
      slot.reservations.push(r);
    }
  }
  return overflow;
}

/**
 * Find reservations that put a server over the number of FPGAs installed in it.
 * Reservations with no server named are skipped: nothing to compare them against.
 */
export function oversubscribed(
  reservations: FpgaReservation[],
  capacity: Capacity,
): { flagged: Set<number>; warnings: string[] } {
  const byPlace = new Map<string, FpgaReservation[]>();
  for (const r of reservations) {
    if (r.server_id == null) continue;
    const key = capacityKey(r.fpga_type_id, r.server_id);
    byPlace.set(key, [...(byPlace.get(key) ?? []), r]);
  }

  const flagged = new Set<number>();
  const warnings: string[] = [];
  for (const [key, group] of byPlace) {
    const installed = capacity.get(key) ?? 0;
    const inUse = new Map<string, number>();
    for (const r of group) {
      for (const day of eachDay(r.start_date, r.end_date)) {
        inUse.set(day, (inUse.get(day) ?? 0) + r.quantity);
      }
    }
    const overDays = [...inUse.entries()]
      .filter(([, total]) => total > installed)
      .map(([day]) => day)
      .sort();
    if (!overDays.length) continue;
    const peak = Math.max(...overDays.map((day) => inUse.get(day) ?? 0));
    const sample = group[0]!;
    const where = sample.server?.name ?? "?";
    const what = sample.fpga_type?.name ?? "?";
    const first = overDays[0]!;
    const last = overDays[overDays.length - 1]!;
    const span = overDays.length === 1 ? shortDate(first) : `${shortDate(first)}–${shortDate(last)}`;
    warnings.push(`${what} in ${where}: ${peak} booked of ${installed} installed, ${span}.`);
    for (const r of group) {
      if (eachDay(r.start_date, r.end_date).some((day) => (inUse.get(day) ?? 0) > installed)) {
        flagged.add(r.id);
      }
    }
  }
  return { flagged, warnings: warnings.sort() };
}

export async function fpgaTimeline(
  db: Db,
  windowStart: string,
  windowEnd: string,
): Promise<Timeline> {
  const totalDays = daysBetween(windowStart, windowEnd) + 1;
  const all = await fpgaReservations(db);
  // Over-subscription is judged on the whole booking, not just the visible slice.
  const { flagged, warnings } = oversubscribed(all, await fpgaCapacity(db));
  const units = await fpgaUnits(db);

  const bar = (r: FpgaReservation, hue: number | null): Bar | null => {
    if (r.end_date < windowStart || r.start_date > windowEnd) return null;
    const leftDay = r.start_date > windowStart ? r.start_date : windowStart;
    const rightDay = r.end_date < windowEnd ? r.end_date : windowEnd;
    const leftPct = (daysBetween(windowStart, leftDay) / totalDays) * 100;
    const widthPct = ((daysBetween(windowStart, rightDay) + 1) / totalDays) * 100 - leftPct;
    return { reservation: r, left_pct: leftPct, width_pct: widthPct, over: flagged.has(r.id), hue };
  };

  const byType = new Map<number, FpgaReservation[]>();
  for (const r of all) byType.set(r.fpga_type_id, [...(byType.get(r.fpga_type_id) ?? []), r]);

  const inventory = await fpgaInventoryByType(db);
  const groups: TimelineGroup[] = [];
  for (const type of await fpgaTypes(db)) {
    const slots = slotsForType(type.id, units);
    const overflow = assignToSlots(byType.get(type.id) ?? [], slots);
    const rows: TimelineRow[] = slots.map((slot) => ({
      label: slot.label,
      hue: slot.hue,
      over_row: false,
      bars: slot.reservations.map((r) => bar(r, slot.hue)).filter((b): b is Bar => b !== null),
    }));
    const overflowBars = overflow.map((r) => bar(r, null)).filter((b): b is Bar => b !== null);
    if (overflowBars.length) {
      rows.push({ label: "Over capacity", hue: null, over_row: true, bars: overflowBars });
    }
    const installed = inventory.get(type.id) ?? [];
    groups.push({
      fpga_type: type,
      rows,
      installed,
      total: installed.reduce((sum, [, qty]) => sum + qty, 0),
    });
  }

  const ticks: Array<{ label: string; left_pct: number }> = [];
  for (let day = windowStart; day <= windowEnd; day = addDays(day, 7)) {
    ticks.push({ label: shortDate(day), left_pct: (daysBetween(windowStart, day) / totalDays) * 100 });
  }

  const today = todayIso();
  const inWindow = windowStart <= today && today <= windowEnd;
  const todayPct = inWindow ? (daysBetween(windowStart, today) / totalDays) * 100 : null;
  return { groups, ticks, today_pct: todayPct, warnings };
}

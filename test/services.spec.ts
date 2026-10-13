import { env } from "cloudflare:workers";
import { beforeEach, describe, expect, it } from "vitest";
import { Db, UniqueViolation } from "../src/db";
import {
  addAssetType, assetsWithStatus, checkoutAsset, deleteAssetType, getAsset,
  returnAsset, saveAsset, setRetired, userCheckouts,
} from "../src/services/assets";
import { importAssets, parseCsv, assetsCsv } from "../src/services/csv";
import {
  addFpgaServer, addFpgaUnit, assignToSlots, capacityKey, deleteFpgaUnit, fpgaCapacity,
  fpgaTimeline, fpgaTypes, fpgaUnits, oversubscribed, saveFpgaReservation,
  setFpgaUnitSerial, slotsForType,
} from "../src/services/fpga";
import type { FpgaReservation, FpgaServer, FpgaUnit, User } from "../src/types";
import { Conflict, Forbidden, ServiceError } from "../src/types";
import { applySchema } from "./helpers";

const db = new Db(env.DB);
const oski: User = { email: "oski@berkeley.edu", name: "Oski", isAdmin: false };
const admin: User = { email: "admin@berkeley.edu", name: "Admin", isAdmin: true };

beforeEach(async () => {
  await applySchema(env.DB);
});

async function makeAsset(name = "BL-07") {
  const type = await addAssetType(db, "Bora Lake");
  return saveAsset(db, null, { name, type_id: String(type.id), chip_mounted: "Agilex 7" });
}

describe("assets and checkouts", () => {
  it("checks out and returns", async () => {
    const asset = await makeAsset();
    const checkout = await checkoutAsset(db, asset, oski, "lab 3");
    expect(checkout.user_email).toBe("oski@berkeley.edu");
    expect(checkout.notes).toBe("lab 3");

    const mine = await userCheckouts(db, oski.email);
    expect(mine[0]?.asset?.name).toBe("BL-07");

    const returned = await returnAsset(db, asset, oski);
    expect(returned.returned_by).toBe(oski.email);
    expect(await import("../src/services/assets").then((m) => m.activeCheckout(db, asset.id))).toBeNull();
  });

  it("refuses a second active checkout, enforced by the database", async () => {
    const asset = await makeAsset();
    await checkoutAsset(db, asset, oski);
    await expect(checkoutAsset(db, asset, oski)).rejects.toBeInstanceOf(Conflict);
    await expect(checkoutAsset(db, asset, admin)).rejects.toThrow(/already checked out/);
  });

  it("lets only the holder or an admin return", async () => {
    const asset = await makeAsset();
    await checkoutAsset(db, asset, oski);
    const rival: User = { email: "rival@berkeley.edu", name: "R", isAdmin: false };
    await expect(returnAsset(db, asset, rival)).rejects.toBeInstanceOf(Forbidden);
    await expect(returnAsset(db, asset, admin)).resolves.toBeTruthy();
  });

  it("will not retire an asset that is checked out", async () => {
    const asset = await makeAsset();
    await checkoutAsset(db, asset, oski);
    await expect(setRetired(db, asset, true)).rejects.toThrow(/Return it before retiring/);
  });

  it("will not check out a retired asset", async () => {
    const asset = await makeAsset();
    await setRetired(db, asset, true);
    const fresh = (await getAsset(db, asset.id))!;
    await expect(checkoutAsset(db, fresh, oski)).rejects.toThrow(/retired/);
  });

  it("rejects duplicate asset names and missing fields", async () => {
    const asset = await makeAsset();
    await expect(
      saveAsset(db, null, { name: "BL-07", type_id: String(asset.type_id) }),
    ).rejects.toBeInstanceOf(Conflict);
    await expect(saveAsset(db, null, { name: "", type_id: "1" })).rejects.toBeInstanceOf(ServiceError);
    await expect(saveAsset(db, null, { name: "x", type_id: "999" })).rejects.toThrow(/asset type/);
  });

  it("will not delete a type that is in use", async () => {
    const asset = await makeAsset();
    const types = await import("../src/services/assets").then((m) => m.assetTypes(db));
    const type = types.find((t) => t.id === asset.type_id)!;
    await expect(deleteAssetType(db, type)).rejects.toThrow(/used by 1 asset/);
  });

  it("filters the overview by type and hides retired assets", async () => {
    const asset = await makeAsset();
    const other = await addAssetType(db, "Other");
    await saveAsset(db, null, { name: "DE10", type_id: String(other.id) });
    expect((await assetsWithStatus(db, { typeId: other.id })).map(([a]) => a.name)).toEqual(["DE10"]);
    await setRetired(db, asset, true);
    expect((await assetsWithStatus(db)).map(([a]) => a.name)).toEqual(["DE10"]);
    expect((await assetsWithStatus(db, { includeRetired: true })).length).toBe(2);
  });
});

describe("csv", () => {
  const HEADER = "name,type,serial,chip_mounted,location,notes,retired\r\n";

  it("creates assets and missing types", async () => {
    const summary = await importAssets(db, `${HEADER}BL-01,Bora Lake,S1,Agilex 7,Cory 125,spare,no`);
    expect(summary).toMatchObject({ created: 1, updated: 0, newTypes: ["Bora Lake"] });
    const rows = await assetsWithStatus(db, { includeRetired: true });
    expect(rows[0]?.[0].type.name).toBe("Bora Lake");
    expect(rows[0]?.[0].location).toBe("Cory 125");
  });

  it("matches existing assets by name instead of duplicating", async () => {
    await importAssets(db, `${HEADER}BL-01,Bora Lake,S1,,,,no`);
    const summary = await importAssets(db, `${HEADER}BL-01,Bora Lake,S2,,Soda 410,moved,yes`);
    expect(summary).toMatchObject({ created: 0, updated: 1 });
    const rows = await assetsWithStatus(db, { includeRetired: true });
    expect(rows.length).toBe(1);
    expect(rows[0]?.[0].serial).toBe("S2");
    expect(rows[0]?.[0].retired).toBe(true);
  });

  it("round-trips the export, undoing the anti-formula quote", async () => {
    await importAssets(db, `${HEADER}BL-01,Bora Lake,S1,Agilex 7,Cory 125,=SUM(A1),no`);
    const exported = assetsCsv(await assetsWithStatus(db, { includeRetired: true }));
    expect(exported).toContain("'=SUM(A1)");
    const summary = await importAssets(db, exported);
    expect(summary).toMatchObject({ created: 0, updated: 1 });
    const rows = await assetsWithStatus(db, { includeRetired: true });
    expect(rows[0]?.[0].notes).toBe("=SUM(A1)");
  });

  it("rejects the whole file when any row is bad", async () => {
    const bad = `${HEADER}Good,Bora Lake,,,,,no\r\n,Bora Lake,,,,,no\r\nNoType,,,,,,no`;
    await expect(importAssets(db, bad)).rejects.toThrow(/Row 3: name is required/);
    expect((await assetsWithStatus(db, { includeRetired: true })).length).toBe(0);
  });

  it("rejects duplicates within the file and bad retired values", async () => {
    await expect(
      importAssets(db, `${HEADER}A,Bora Lake,,,,,no\r\nA,Bora Lake,,,,,no`),
    ).rejects.toThrow(/appears more than once/);
    await expect(importAssets(db, `${HEADER}A,Bora Lake,,,,,maybe`)).rejects.toThrow(/yes or no/);
    await expect(importAssets(db, "nickname,colour\r\nA,blue")).rejects.toThrow(/missing the name, type/);
    await expect(importAssets(db, HEADER)).rejects.toThrow(/no asset rows/);
  });

  it("parses quoted fields containing commas and quotes", () => {
    expect(parseCsv('a,"b,c","d""e"')).toEqual([["a", "b,c", 'd"e']]);
  });
});

describe("fpga reservations", () => {
  async function setup(boards: number) {
    const [type] = await fpgaTypes(db);
    const server = await addFpgaServer(db, "rack2-srv1");
    for (let i = 0; i < boards; i++) await addFpgaUnit(db, type!.id, server.id);
    return { type: type!, server };
  }

  function form(type: number, server: number, extra: Record<string, string> = {}) {
    return {
      fpga_type_id: String(type), server_id: String(server), project: "Lab 4",
      quantity: "1", contact: "oski", start_date: "2026-06-01", end_date: "2026-06-05",
      ...extra,
    };
  }

  it("requires a server and validates the fields", async () => {
    const { type, server } = await setup(2);
    await expect(saveFpgaReservation(db, null, oski, form(type.id, server.id, { server_id: "" })))
      .rejects.toThrow(/Pick a server/);
    await expect(saveFpgaReservation(db, null, oski, form(type.id, server.id, { project: "" })))
      .rejects.toThrow(/Project is required/);
    await expect(saveFpgaReservation(db, null, oski, form(type.id, server.id, { quantity: "0" })))
      .rejects.toThrow(/at least 1/);
    await expect(
      saveFpgaReservation(db, null, oski, form(type.id, server.id, { end_date: "2026-05-01" })),
    ).rejects.toThrow(/End date can't be before/);
  });

  it("gives each board its own row and hue, and packs overlapping bookings", async () => {
    const { type, server } = await setup(2);
    await saveFpgaReservation(db, null, oski, form(type.id, server.id, { project: "Alpha" }));
    await saveFpgaReservation(db, null, oski, form(type.id, server.id, { project: "Bravo" }));
    const timeline = await fpgaTimeline(db, "2026-06-01", "2026-06-30");
    const group = timeline.groups.find((g) => g.fpga_type.id === type.id)!;
    expect(group.rows.map((r) => r.label)).toEqual(["rack2-srv1 #1", "rack2-srv1 #2"]);
    expect(new Set(group.rows.map((r) => r.hue)).size).toBe(2);
    expect(timeline.warnings).toEqual([]);
  });

  it("flags over-booking but still saves it", async () => {
    const { type, server } = await setup(1);
    await saveFpgaReservation(db, null, oski, form(type.id, server.id, { project: "Alpha" }));
    await saveFpgaReservation(db, null, oski, form(type.id, server.id, { project: "Bravo" }));
    const timeline = await fpgaTimeline(db, "2026-06-01", "2026-06-30");
    const group = timeline.groups.find((g) => g.fpga_type.id === type.id)!;
    expect(group.rows.some((r) => r.over_row && r.label === "Over capacity")).toBe(true);
    expect(timeline.warnings[0]).toMatch(/2 booked of 1 installed/);
  });

  it("only the creator or an admin may edit or delete", async () => {
    const { type, server } = await setup(2);
    const reservation = await saveFpgaReservation(db, null, oski, form(type.id, server.id));
    const rival: User = { email: "rival@berkeley.edu", name: "R", isAdmin: false };
    await expect(saveFpgaReservation(db, reservation, rival, form(type.id, server.id)))
      .rejects.toBeInstanceOf(Forbidden);
    await expect(saveFpgaReservation(db, reservation, admin, form(type.id, server.id, { project: "X" })))
      .resolves.toMatchObject({ project: "X" });
  });

  it("capacity is derived from the boards on record", async () => {
    const { type, server } = await setup(3);
    expect((await fpgaCapacity(db)).get(capacityKey(type.id, server.id))).toBe(3);
    const [first] = await fpgaUnits(db);
    await deleteFpgaUnit(db, first!);
    expect((await fpgaCapacity(db)).get(capacityKey(type.id, server.id))).toBe(2);
  });

  it("labels a board by its serial, and by position when it has none", async () => {
    const { type, server } = await setup(2);
    const [first] = await fpgaUnits(db);
    await setFpgaUnitSerial(db, first!, "SN-12345");
    const timeline = await fpgaTimeline(db, "2026-06-01", "2026-06-30");
    const group = timeline.groups.find((g) => g.fpga_type.id === type.id)!;
    expect(group.rows.map((r) => r.label)).toEqual(["rack2-srv1 · SN-12345", "rack2-srv1 #2"]);
    expect(server.name).toBe("rack2-srv1");
  });

  it("serials are optional but unique", async () => {
    const { type, server } = await setup(0);
    const bare = await addFpgaUnit(db, type.id, server.id);
    expect(bare.serial).toBeNull();
    // Several unlabelled boards are fine: blank serials don't collide.
    await addFpgaUnit(db, type.id, server.id);
    expect((await fpgaUnits(db)).length).toBe(2);

    await addFpgaUnit(db, type.id, server.id, "SN-1");
    await expect(addFpgaUnit(db, type.id, server.id, "SN-1")).rejects.toThrow(/already on another board/);
    await expect(addFpgaUnit(db, type.id, server.id, "  SN-1  ")).rejects.toThrow(/already on another board/);
    await expect(setFpgaUnitSerial(db, bare, "SN-1")).rejects.toThrow(/already on another board/);

    // Clearing a serial frees it for reuse.
    const labelled = (await fpgaUnits(db)).find((u) => u.serial === "SN-1")!;
    await setFpgaUnitSerial(db, labelled, "");
    expect((await fpgaUnits(db)).find((u) => u.id === labelled.id)?.serial).toBeNull();
    await expect(setFpgaUnitSerial(db, bare, "SN-1")).resolves.toMatchObject({ serial: "SN-1" });
  });
});

describe("over-subscription maths", () => {
  const server: FpgaServer = { id: 1, name: "srv", notes: "" };
  const booking = (id: number, start: string, end: string, quantity = 1): FpgaReservation => ({
    id, fpga_type_id: 1, fpga_type: { id: 1, name: "U250" },
    server_id: server.id, server: { id: server.id, name: server.name },
    project: `P${id}`, quantity, contact: "o", special_requests: "",
    start_date: start, end_date: end, created_by_email: "o@berkeley.edu", created_at: "",
  });

  it("ignores bookings that do not overlap", () => {
    const placements = new Map([[capacityKey(1, 1), 1]]);
    const { flagged, warnings } = oversubscribed(
      [booking(1, "2026-06-01", "2026-06-01"), booking(2, "2026-06-02", "2026-06-02")],
      placements,
    );
    expect(flagged.size).toBe(0);
    expect(warnings).toEqual([]);
  });

  it("never flags a booking with no server", () => {
    const loose = { ...booking(1, "2026-06-01", "2026-06-02", 99), server_id: null, server: null };
    const { flagged } = oversubscribed([loose], new Map());
    expect(flagged.size).toBe(0);
  });

  it("flags a server with nothing installed", () => {
    const { flagged, warnings } = oversubscribed([booking(1, "2026-06-01", "2026-06-02")], new Map());
    expect(flagged).toEqual(new Set([1]));
    expect(warnings[0]).toMatch(/1 booked of 0 installed/);
  });

  it("sends an all-or-nothing booking to overflow rather than splitting it", () => {
    const unit = (id: number): FpgaUnit => ({
      id, fpga_type_id: 1, server_id: server.id,
      server: { id: server.id, name: server.name }, serial: null, created_at: "",
    });
    const slots = slotsForType(1, [unit(1), unit(2)]);
    const overflow = assignToSlots([booking(1, "2026-06-01", "2026-06-05", 2), booking(2, "2026-06-02", "2026-06-03", 2)], slots);
    expect(overflow.map((r) => r.id)).toEqual([2]);
    expect(slots.every((s) => s.reservations.length === 1)).toBe(true);
  });
});

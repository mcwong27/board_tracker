/**
 * End-to-end tests through the real Worker: routing, session cookies, CSRF, D1 and
 * rendering, all in workerd. These are the tests that prove the parts are wired up.
 */

import { env, exports } from "cloudflare:workers";
import { beforeEach, describe, expect, it } from "vitest";
import { applySchema } from "./helpers";

const BASE = "http://localhost";

/** A tiny cookie-jar client, so sessions behave as they do in a browser. */
class Client {
  private cookie = "";

  async fetch(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    if (this.cookie) headers.set("Cookie", this.cookie);
    // `redirect: "manual"` matters: a Fetcher follows redirects by default, which
    // would silently swallow the 303s this app relies on (and drop their cookies).
    const response = await exports.default.fetch(
      new Request(`${BASE}${path}`, { ...init, headers, redirect: "manual" }),
    );
    const setCookie = response.headers.get("Set-Cookie");
    if (setCookie) this.cookie = setCookie.split(";")[0] ?? "";
    return response;
  }

  async get(path: string) {
    return this.fetch(path);
  }

  async text(path: string) {
    return (await this.get(path)).text();
  }

  /** POST a form, pulling a fresh CSRF token from `page` first. */
  async post(path: string, data: Record<string, string> = {}, page = "/") {
    const token = await this.csrf(page);
    return this.fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ ...data, csrf_token: token }).toString(),
    });
  }

  async csrf(path: string): Promise<string> {
    const match = /name="csrf_token" value="([^"]+)"/.exec(await this.text(path));
    if (!match?.[1]) throw new Error(`no CSRF token on ${path}`);
    return match[1];
  }

  async login(email: string, { admin = false } = {}) {
    const data: Record<string, string> = { email };
    if (admin) data["admin"] = "on";
    const response = await this.post("/dev-login", data, "/dev-login");
    expect(response.status).toBe(303);
    return response;
  }
}

beforeEach(async () => {
  await applySchema(env.DB);
});

describe("signed-out behaviour", () => {
  it("serves healthz and the login page", async () => {
    const c = new Client();
    expect(await (await c.get("/healthz")).text()).toBe("ok");
    expect((await c.get("/login")).status).toBe(200);
  });

  it("sends anonymous users to sign in and remembers where they were going", async () => {
    const c = new Client();
    const response = await c.get("/fpga");
    expect(response.status).toBe(303);
    expect(response.headers.get("Location")).toBe("/login");
    // The remembered path survives in the session cookie.
    await c.login("oski@berkeley.edu");
    expect((await c.get("/fpga")).status).toBe(200);
  });

  it("rejects a non-berkeley dev login", async () => {
    const c = new Client();
    const response = await c.post("/dev-login", { email: "oski@gmail.com" }, "/dev-login");
    expect(response.status).toBe(403);
    expect((await c.get("/")).status).toBe(303);
  });
});

describe("CSRF", () => {
  it("rejects a POST with no token", async () => {
    const c = new Client();
    await c.login("oski@berkeley.edu");
    const response = await c.fetch("/fpga/new", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: "project=X",
    });
    expect(response.status).toBe(403);
  });

  it("rejects a POST with the wrong token", async () => {
    const c = new Client();
    await c.login("oski@berkeley.edu");
    const response = await c.fetch("/fpga/new", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ csrf_token: "nope", project: "X" }).toString(),
    });
    expect(response.status).toBe(403);
  });
});

describe("admin access", () => {
  it("is refused for ordinary users and granted to admins", async () => {
    const user = new Client();
    await user.login("oski@berkeley.edu");
    expect((await user.get("/admin")).status).toBe(403);
    expect(await user.text("/")).not.toContain('href="/admin"');

    const admin = new Client();
    await admin.login("admin@berkeley.edu", { admin: true });
    expect((await admin.get("/admin")).status).toBe(200);
    expect(await admin.text("/")).toContain('href="/admin"');
  });
});

describe("the asset lifecycle, end to end", () => {
  it("adds a type and an asset, checks it out, and returns it", async () => {
    const admin = new Client();
    await admin.login("admin@berkeley.edu", { admin: true });

    expect((await admin.post("/admin/types", { name: "Bora Lake" }, "/admin")).status).toBe(303);
    const adminPage = await admin.text("/admin");
    const typeId = /name="qty-|value="(\d+)"[^>]*>Bora Lake|<option value="(\d+)"/.exec(adminPage);
    expect(adminPage).toContain("Bora Lake");

    const newForm = await admin.text("/admin/assets/new");
    const optionId = /<option value="(\d+)"/.exec(newForm)?.[1];
    expect(optionId).toBeTruthy();

    const added = await admin.post(
      "/admin/assets/new",
      { name: "BL-07", type_id: optionId!, chip_mounted: "Agilex 7" },
      "/admin/assets/new",
    );
    expect(added.status).toBe(303);

    const overview = await admin.text("/assets");
    expect(overview).toContain("BL-07");
    expect(overview).toContain("Available");

    const assetId = /href="\/assets\/(\d+)"/.exec(overview)?.[1];
    expect(assetId).toBeTruthy();

    const out = await admin.post(`/assets/${assetId}/checkout`, { notes: "lab 3" }, `/assets/${assetId}`);
    expect(out.status).toBe(303);
    expect(await admin.text("/")).toContain("BL-07"); // the dashboard lists what you hold
    expect(await admin.text("/assets")).toContain("Checked out");

    // A second person cannot return it.
    const rival = new Client();
    await rival.login("rival@berkeley.edu");
    expect((await rival.post(`/assets/${assetId}/return`, {}, `/assets/${assetId}`)).status).toBe(403);

    const back = await admin.post(`/assets/${assetId}/return`, {}, `/assets/${assetId}`);
    expect(back.status).toBe(303);
    expect(await admin.text("/assets")).toContain("Available");
  });

  it("round-trips the CSV export through the importer", async () => {
    const admin = new Client();
    await admin.login("admin@berkeley.edu", { admin: true });
    const body = new FormData();
    body.set("csrf_token", await admin.csrf("/admin"));
    body.set("file", new File(["name,type,notes\r\nBL-01,Bora Lake,=SUM(A1)"], "a.csv"));
    const imported = await admin.fetch("/admin/assets/import", { method: "POST", body });
    expect(imported.status).toBe(303);

    const csv = await admin.text("/admin/export/assets.csv");
    expect(csv).toContain("BL-01");
    expect(csv).toContain("'=SUM(A1)"); // formula injection neutralized

    const again = new FormData();
    again.set("csrf_token", await admin.csrf("/admin"));
    again.set("file", new File([csv], "a.csv"));
    expect((await admin.fetch("/admin/assets/import", { method: "POST", body: again })).status).toBe(303);
    expect((await admin.text("/assets")).match(/BL-01/g)?.length).toBe(1); // not duplicated
  });
});

describe("the FPGA timeline, end to end", () => {
  /** Sign in as an admin, create a server, and add `boards` boards of one FPGA type. */
  async function setup(boards = 0, serials: string[] = []) {
    const admin = new Client();
    await admin.login("admin@berkeley.edu", { admin: true });
    await admin.post("/admin/fpga/servers", { name: "rack2-srv1" }, "/admin");
    const page = await admin.text("/admin");
    const typeId = /name="fpga_type_id" value="(\d+)"/.exec(page)?.[1];
    const serverId = /<option value="(\d+)">rack2-srv1<\/option>/.exec(page)?.[1];
    expect(typeId, "the add-board form should render once a type and a server exist").toBeTruthy();
    expect(serverId).toBeTruthy();
    for (let i = 0; i < boards; i++) {
      const response = await admin.post(
        "/admin/fpga/units",
        { fpga_type_id: typeId!, server_id: serverId!, serial: serials[i] ?? "" },
        "/admin",
      );
      expect(response.status).toBe(303);
    }
    return { admin, typeId: typeId!, serverId: serverId! };
  }

  it("gives each board a row and a hue, labelled by serial when it has one", async () => {
    const { admin, typeId, serverId } = await setup(2, ["SN-ALPHA"]);
    const today = new Date().toISOString().slice(0, 10);
    const booked = await admin.post(
      "/fpga/new",
      {
        fpga_type_id: typeId, server_id: serverId, project: "Lab 4",
        quantity: "1", contact: "oski", start_date: today, end_date: today,
      },
      "/fpga/new",
    );
    expect(booked.status).toBe(303);

    const timeline = await admin.text("/fpga");
    expect(timeline).toContain("rack2-srv1 · SN-ALPHA"); // labelled board
    expect(timeline).toContain("rack2-srv1 #2"); // unlabelled falls back to a position
    expect(timeline).toMatch(/--hue:\s*\d+/);
    expect(timeline).toContain("Lab 4");
    expect(timeline).not.toContain("Over-subscribed");
  });

  it("flags over-booking but still saves it", async () => {
    const { admin, typeId, serverId } = await setup(1);
    const today = new Date().toISOString().slice(0, 10);
    for (const project of ["Alpha", "Bravo"]) {
      const response = await admin.post(
        "/fpga/new",
        {
          fpga_type_id: typeId, server_id: serverId, project,
          quantity: "1", contact: "oski", start_date: today, end_date: today,
        },
        "/fpga/new",
      );
      expect(response.status).toBe(303); // soft limit: saved anyway
    }
    const timeline = await admin.text("/fpga");
    expect(timeline).toContain("Over-subscribed");
    expect(timeline).toContain("2 booked of 1 installed");
    expect(timeline).toContain("Over capacity");
  });

  it("keeps serials unique, and allows many unlabelled boards", async () => {
    const { admin, typeId, serverId } = await setup(0);
    const add = (serial: string) =>
      admin.post("/admin/fpga/units", { fpga_type_id: typeId, server_id: serverId, serial }, "/admin");

    expect((await add("SN-1")).status).toBe(303);
    const clash = await add("SN-1");
    expect(clash.status).toBe(409);
    expect(await clash.text()).toContain("already on another board");

    // Blank serials don't collide with each other.
    expect((await add("")).status).toBe(303);
    expect((await add("")).status).toBe(303);
    const page = await admin.text("/admin");
    expect(page).toContain("3 installed");
  });

  it("requires a server and refuses edits by other people", async () => {
    const { admin, typeId, serverId } = await setup(1);
    const today = new Date().toISOString().slice(0, 10);
    const noServer = await admin.post(
      "/fpga/new",
      {
        fpga_type_id: typeId, server_id: "", project: "X",
        quantity: "1", contact: "o", start_date: today, end_date: today,
      },
      "/fpga/new",
    );
    expect(noServer.status).toBe(400);
    expect(await noServer.text()).toContain("Pick a server");

    await admin.post(
      "/fpga/new",
      {
        fpga_type_id: typeId, server_id: serverId, project: "Mine",
        quantity: "1", contact: "o", start_date: today, end_date: today,
      },
      "/fpga/new",
    );
    const id = /href="\/fpga\/(\d+)\/edit"/.exec(await admin.text("/fpga"))?.[1];
    expect(id).toBeTruthy();

    const rival = new Client();
    await rival.login("rival@berkeley.edu");
    expect((await rival.get(`/fpga/${id}/edit`)).status).toBe(403);
    expect((await rival.post(`/fpga/${id}/delete`, {}, "/fpga")).status).toBe(403);
  });
});

describe("escaping", () => {
  it("escapes user text rather than rendering it as markup", async () => {
    const admin = new Client();
    await admin.login("admin@berkeley.edu", { admin: true });
    await admin.post("/admin/types", { name: '<script>alert(1)</script>' }, "/admin");
    const page = await admin.text("/admin");
    expect(page).not.toContain("<script>alert(1)</script>");
    expect(page).toContain("&lt;script&gt;");
  });
});

import { describe, expect, it } from "vitest";
import type { Asset, Bar, Checkout, FpgaReservation, Timeline, User } from "../src/types";
import { adminPage } from "../src/views/admin";
import { assetPage } from "../src/views/asset";
import { assetOverviewPage } from "../src/views/assetOverview";
import { dashboardPage } from "../src/views/dashboard";
import { fpgaPage } from "../src/views/fpga";
import { fpgaFormPage } from "../src/views/fpgaForm";
import type { LayoutContext } from "../src/views/layout";

const alice: User = { email: "alice@berkeley.edu", name: "Alice", isAdmin: false };
const bob: User = { email: "bob@berkeley.edu", name: "Bob", isAdmin: false };
const admin: User = { email: "root@berkeley.edu", name: "Root", isAdmin: true };

const ctxFor = (user: User | null): LayoutContext => ({
  title: "x",
  user,
  devLogin: false,
  csrfToken: "tok123",
  flash: null,
});

const asset = (over: Partial<Asset> = {}): Asset => ({
  id: 1,
  name: "ZCU102 #1",
  type_id: 1,
  type: { id: 1, name: "Board" },
  serial: "SN1",
  chip_mounted: "XCZU9EG",
  location: "Cory 125",
  notes: "",
  retired: false,
  created_at: "2026-01-01 00:00:00",
  ...over,
});

const checkout = (over: Partial<Checkout> = {}): Checkout => ({
  id: 1,
  asset_id: 1,
  user_email: alice.email,
  user_name: "Alice",
  checked_out_at: "2026-10-01 18:00:00",
  returned_at: null,
  returned_by: null,
  notes: "",
  active: true,
  ...over,
});

const reservation = (over: Partial<FpgaReservation> = {}): FpgaReservation => ({
  id: 7,
  fpga_type_id: 1,
  fpga_type: { id: 1, name: "U250" },
  server_id: 2,
  server: { id: 2, name: "rack1-srv1" },
  project: "Routing",
  quantity: 2,
  contact: "alice",
  special_requests: "",
  start_date: "2026-10-05",
  end_date: "2026-10-12",
  created_by_email: alice.email,
  created_at: "2026-10-01 00:00:00",
  ...over,
});

const bar = (r: FpgaReservation, hue: number | null = 120): Bar => ({
  reservation: r,
  left_pct: 12.5,
  width_pct: 30,
  over: false,
  hue,
});

function timelineOf(r: FpgaReservation): Timeline {
  return {
    groups: [
      {
        fpga_type: { id: 1, name: "U250" },
        rows: [
          { label: "rack1-srv1 #1", hue: 120, over_row: false, bars: [bar(r, 120)] },
          { label: "rack1-srv1 #2", hue: 240, over_row: false, bars: [] },
        ],
        installed: [[{ id: 2, name: "rack1-srv1", notes: "" }, 2]],
        total: 2,
      },
      { fpga_type: { id: 2, name: "U280" }, rows: [], installed: [], total: 0 },
    ],
    ticks: [{ label: "Oct 5", left_pct: 0 }],
    today_pct: 25,
    warnings: [],
  };
}

const fpgaProps = (r: FpgaReservation[], timeline: Timeline) => ({
  timeline,
  reservations: r,
  windowStart: "2026-10-05",
  windowEnd: "2026-11-05",
  prevStart: "2026-09-05",
  nextStart: "2026-11-05",
  todayStart: "2026-10-05",
});

const count = (s: string, needle: string) => s.split(needle).length - 1;

describe("escaping", () => {
  it("escapes a hostile reservation project everywhere it appears", () => {
    const r = reservation({ project: `<script>alert("x")</script>` });
    const out = fpgaPage(ctxFor(alice), fpgaProps([r], timelineOf(r))).toString();
    expect(out).not.toContain("<script>alert");
    expect(out).toContain("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;");
  });

  it("escapes asset names in pages and attribute values", () => {
    const a = asset({ name: `"><img src=x onerror=1>` });
    const out = assetPage(ctxFor(alice), { asset: a, active: null, history: [] }).toString();
    expect(out).not.toContain("<img src=x");
    expect(out).toContain("&quot;&gt;&lt;img src=x onerror=1&gt;");
  });

  it("escapes form values", () => {
    const out = fpgaFormPage(ctxFor(alice), {
      reservation: null,
      values: { project: `a" autofocus onfocus="x` },
      types: [],
      servers: [],
      inventory: new Map(),
    }).toString();
    expect(out).toContain('value="a&quot; autofocus onfocus=&quot;x"');
  });
});

describe("timeline", () => {
  const r = reservation();
  const out = fpgaPage(ctxFor(alice), fpgaProps([r], timelineOf(r))).toString();

  it("renders one details per type and one mux-band per board row", () => {
    expect(count(out, '<details class="timeline-group">')).toBe(2);
    // two rows in U250 plus the single empty band for U280
    expect(count(out, 'class="mux-band"')).toBe(3);
  });

  it("passes hues as inline CSS variables", () => {
    expect(out).toContain('<span class="swatch" style="--hue: 120">');
    expect(out).toContain("--hue: 240");
    expect(out).toContain("left: 12.5%; width: 30%; --hue: 120");
  });

  it("renders the tooltip, thin and full bars, and the today marker", () => {
    expect(count(out, 'class="timeline-bar thin"')).toBe(1);
    expect(count(out, 'class="timeline-bar"')).toBe(1);
    expect(count(out, 'class="tooltip"')).toBe(2);
    expect(out).toContain("Oct 5, 2026 &ndash; Oct 12, 2026");
    expect(out).toContain("* 0.2500)");
    expect(out).toContain("2 installed");
    expect(out).toContain("none installed");
  });
});

describe("conditional UI", () => {
  it("shows the Admin link only to admins", () => {
    const page = (u: User | null) =>
      dashboardPage(ctxFor(u), { current: [], past: [] }).toString();
    expect(page(admin)).toContain('<a href="/admin">Admin</a>');
    expect(page(alice)).not.toContain('<a href="/admin">Admin</a>');
    const signedOut = page(null);
    expect(signedOut).not.toContain("Sign out");
    expect(signedOut).toContain("push-right");
  });

  it("shows edit and delete only to the owner or an admin", () => {
    const r = reservation();
    const render = (u: User) => fpgaPage(ctxFor(u), fpgaProps([r], timelineOf(r))).toString();
    expect(render(alice)).toContain('action="/fpga/7/delete"');
    expect(render(admin)).toContain('action="/fpga/7/delete"');
    expect(render(bob)).not.toContain('action="/fpga/7/delete"');
  });

  it("offers Return to the holder, Force return to admins, nothing to others", () => {
    const a = asset();
    const c = checkout();
    const rows: Array<[Asset, Checkout | null]> = [[a, c]];
    const props = { rows, types: [], selectedType: null, available: 0 };
    const view = (u: User) => assetOverviewPage(ctxFor(u), props).toString();
    expect(view(alice)).toContain(">Return</button>");
    expect(view(admin)).toContain(">Force return</button>");
    expect(view(bob)).not.toContain("/assets/1/return");
  });

  it("offers check out for available assets and nothing for retired ones", () => {
    const view = (a: Asset) =>
      assetOverviewPage(ctxFor(alice), {
        rows: [[a, null]],
        types: [],
        selectedType: 3,
        available: 1,
      }).toString();
    expect(view(asset())).toContain('action="/assets/1/checkout"');
    expect(view(asset())).toContain('name="back" value="/assets?type=3"');
    expect(view(asset({ retired: true }))).not.toContain("/checkout");
  });

  it("keeps the csrf token in forms", () => {
    const out = assetPage(ctxFor(alice), { asset: asset(), active: null, history: [] }).toString();
    expect(out).toContain('name="csrf_token" value="tok123"');
  });
});

describe("empty states", () => {
  it("overview with no assets links admins to add one", () => {
    const props = { rows: [], types: [], selectedType: null, available: 0 };
    expect(assetOverviewPage(ctxFor(alice), props).toString()).toContain("No assets yet.");
    expect(assetOverviewPage(ctxFor(alice), props).toString()).not.toContain("/admin/assets/new");
    expect(assetOverviewPage(ctxFor(admin), props).toString()).toContain("/admin/assets/new");
  });

  it("fpga page with no types or reservations", () => {
    const empty: Timeline = { groups: [], ticks: [], today_pct: null, warnings: [] };
    const out = fpgaPage(ctxFor(admin), fpgaProps([], empty)).toString();
    expect(out).toContain("No FPGA types yet.");
    expect(out).toContain("No FPGA reservations yet.");
    expect(out).not.toContain("timeline-today");
  });

  it("admin page with nothing configured", () => {
    const out = adminPage(ctxFor(admin), {
      rows: [],
      types: [],
      typeCounts: new Map(),
      fpgaTypes: [],
      fpgaServers: [],
      placements: new Map(),
    }).toString();
    expect(out).toContain("No assets yet.");
    expect(out).toContain("No types yet. Add one before adding assets.");
    expect(out).toContain("Add at least one FPGA type and one server");
    expect(out).toContain("No servers yet.");
  });

  it("disables deleting an asset type that is in use", () => {
    const out = adminPage(ctxFor(admin), {
      rows: [],
      types: [{ id: 1, name: "Board", sort_order: 0 }],
      typeCounts: new Map([[1, 3]]),
      fpgaTypes: [{ id: 1, name: "U250" }],
      fpgaServers: [{ id: 2, name: "srv", notes: "" }],
      placements: new Map([["1:2", 4]]),
    }).toString();
    expect(out).toContain('title="In use by 3 asset(s)"');
    expect(out).toContain('name="qty-1-2"');
    expect(out).toContain('value="4"');
  });

  it("dashboard with nothing out or returned", () => {
    const out = dashboardPage(ctxFor(alice), { current: [], past: [] }).toString();
    expect(out).toContain("You don't have any assets checked out.");
    expect(out).not.toContain("Past checkouts");
  });

  it("asset page with no history", () => {
    const out = assetPage(ctxFor(alice), { asset: asset(), active: null, history: [] }).toString();
    expect(out).toContain("Never checked out.");
  });
});

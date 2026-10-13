/** Admin: assets, asset types and the FPGA inventory. Every route requires an admin. */

import { Hono } from "hono";
import type { Session } from "../auth/session";
import { db, formValues, layoutContext, page, redirect, type AppContext } from "../context";
import * as assets from "../services/assets";
import { assetsCsv, checkoutsCsv, importAssets } from "../services/csv";
import * as fpga from "../services/fpga";
import { ServiceError } from "../types";
import { adminPage } from "../views/admin";
import { assetFormPage } from "../views/assetForm";
import { assertCsrf, requireAdmin } from "./guards";

export const adminRoutes = new Hono<{ Bindings: Env; Variables: { session: Session } }>();

adminRoutes.use("*", async (c, next) => {
  requireAdmin(c as AppContext);
  await next();
});

const MAX_IMPORT_BYTES = 2_000_000;

async function renderIndex(c: AppContext, status = 200, error?: string) {
  const database = db(c);
  return page(
    c,
    adminPage(layoutContext(c, "Admin"), {
      rows: await assets.assetsWithStatus(database, { includeRetired: true }),
      types: await assets.assetTypes(database),
      typeCounts: await assets.assetCountsByType(database),
      fpgaTypes: await fpga.fpgaTypes(database),
      fpgaServers: await fpga.fpgaServers(database),
      placements: await fpga.fpgaPlacements(database),
      error,
    }),
    status,
  );
}

async function renderAssetForm(
  c: AppContext,
  asset: Awaited<ReturnType<typeof assets.getAsset>>,
  values: Record<string, string>,
  status = 200,
  error?: string,
) {
  return page(
    c,
    assetFormPage(layoutContext(c, asset ? `Edit ${asset.name}` : "Add asset"), {
      asset,
      values,
      types: await assets.assetTypes(db(c)),
      error,
    }),
    status,
  );
}

function notFound(): never {
  throw Object.assign(new Error("Page not found."), { status: 404 });
}

adminRoutes.get("/admin", (c) => renderIndex(c as AppContext));

adminRoutes.get("/admin/assets/new", (c) => renderAssetForm(c as AppContext, null, {}));

adminRoutes.post("/admin/assets/new", async (c) => {
  const values = await formValues(c as AppContext);
  assertCsrf(c as AppContext, values);
  try {
    const asset = await assets.saveAsset(db(c as AppContext), null, values);
    return redirect(c as AppContext, "/admin", `Added ${asset.name}.`);
  } catch (error) {
    if (!(error instanceof ServiceError)) throw error;
    return renderAssetForm(c as AppContext, null, values, error.status, error.message);
  }
});

adminRoutes.post("/admin/assets/import", async (c) => {
  const ctx = c as AppContext;
  const form = await c.req.formData();
  const token = form.get("csrf_token");
  assertCsrf(ctx, { csrf_token: typeof token === "string" ? token : "" });
  const file = form.get("file");
  if (!(file instanceof File) || file.size === 0) {
    return renderIndex(ctx, 400, "Choose a CSV file to import.");
  }
  if (file.size > MAX_IMPORT_BYTES) {
    return renderIndex(ctx, 400, "That file is too big (limit 2 MB).");
  }
  const text = await file.text();
  try {
    const summary = await importAssets(db(ctx), text);
    let message = `Imported ${summary.created} new and updated ${summary.updated} assets.`;
    if (summary.newTypes.length) message += ` Added types: ${summary.newTypes.join(", ")}.`;
    return redirect(ctx, "/admin", message);
  } catch (error) {
    if (!(error instanceof ServiceError)) throw error;
    return renderIndex(ctx, error.status, error.message);
  }
});

adminRoutes.get("/admin/assets/:id{[0-9]+}/edit", async (c) => {
  const ctx = c as AppContext;
  const asset = await assets.getAsset(db(ctx), Number(c.req.param("id")));
  if (!asset) notFound();
  const values: Record<string, string> = {
    name: asset.name,
    type_id: String(asset.type_id),
    serial: asset.serial,
    chip_mounted: asset.chip_mounted,
    location: asset.location,
    notes: asset.notes,
  };
  return renderAssetForm(ctx, asset, values);
});

adminRoutes.post("/admin/assets/:id{[0-9]+}/edit", async (c) => {
  const ctx = c as AppContext;
  const values = await formValues(ctx);
  assertCsrf(ctx, values);
  const asset = await assets.getAsset(db(ctx), Number(c.req.param("id")));
  if (!asset) notFound();
  try {
    await assets.saveAsset(db(ctx), asset, values);
  } catch (error) {
    if (!(error instanceof ServiceError)) throw error;
    return renderAssetForm(ctx, asset, values, error.status, error.message);
  }
  return redirect(ctx, `/assets/${asset.id}`, `Saved ${values["name"]}.`);
});

for (const [path, retired] of [["retire", true], ["unretire", false]] as const) {
  adminRoutes.post(`/admin/assets/:id{[0-9]+}/${path}`, async (c) => {
    const ctx = c as AppContext;
    assertCsrf(ctx, await formValues(ctx));
    const asset = await assets.getAsset(db(ctx), Number(c.req.param("id")));
    if (!asset) notFound();
    try {
      await assets.setRetired(db(ctx), asset, retired);
    } catch (error) {
      if (!(error instanceof ServiceError)) throw error;
      return renderIndex(ctx, error.status, error.message);
    }
    return redirect(ctx, "/admin", `${retired ? "Retired" : "Restored"} ${asset.name}.`);
  });
}

/** Wraps a mutation: parse the form, check CSRF, run it, redirect or re-render. */
async function mutate(
  c: AppContext,
  run: (values: Record<string, string>) => Promise<string>,
): Promise<Response> {
  const values = await formValues(c);
  assertCsrf(c, values);
  try {
    return redirect(c, "/admin", await run(values));
  } catch (error) {
    if (!(error instanceof ServiceError)) throw error;
    return renderIndex(c, error.status, error.message);
  }
}

adminRoutes.post("/admin/types", (c) =>
  mutate(c as AppContext, async (values) => {
    const type = await assets.addAssetType(db(c as AppContext), values["name"] ?? "");
    return `Added type ${type.name}.`;
  }),
);

adminRoutes.post("/admin/types/:id{[0-9]+}/rename", (c) =>
  mutate(c as AppContext, async (values) => {
    const ctx = c as AppContext;
    const type = await assets.getAssetType(db(ctx), Number(c.req.param("id")));
    if (!type) notFound();
    const renamed = await assets.renameAssetType(db(ctx), type, values["name"] ?? "");
    return `Renamed ${type.name} to ${renamed.name}.`;
  }),
);

adminRoutes.post("/admin/types/:id{[0-9]+}/delete", (c) =>
  mutate(c as AppContext, async () => {
    const ctx = c as AppContext;
    const type = await assets.getAssetType(db(ctx), Number(c.req.param("id")));
    if (!type) notFound();
    await assets.deleteAssetType(db(ctx), type);
    return `Deleted type ${type.name}.`;
  }),
);

adminRoutes.post("/admin/fpga/types", (c) =>
  mutate(c as AppContext, async (values) => {
    const type = await fpga.addFpgaType(db(c as AppContext), values["name"] ?? "");
    return `Added FPGA type ${type.name}.`;
  }),
);

adminRoutes.post("/admin/fpga/types/:id{[0-9]+}/rename", (c) =>
  mutate(c as AppContext, async (values) => {
    const ctx = c as AppContext;
    const type = await fpga.getFpgaType(db(ctx), Number(c.req.param("id")));
    if (!type) notFound();
    const renamed = await fpga.renameFpgaType(db(ctx), type, values["name"] ?? "");
    return `Renamed ${type.name} to ${renamed.name}.`;
  }),
);

adminRoutes.post("/admin/fpga/types/:id{[0-9]+}/delete", (c) =>
  mutate(c as AppContext, async () => {
    const ctx = c as AppContext;
    const type = await fpga.getFpgaType(db(ctx), Number(c.req.param("id")));
    if (!type) notFound();
    await fpga.deleteFpgaType(db(ctx), type);
    return `Deleted FPGA type ${type.name}.`;
  }),
);

adminRoutes.post("/admin/fpga/servers", (c) =>
  mutate(c as AppContext, async (values) => {
    const server = await fpga.addFpgaServer(
      db(c as AppContext),
      values["name"] ?? "",
      values["notes"] ?? "",
    );
    return `Added server ${server.name}.`;
  }),
);

adminRoutes.post("/admin/fpga/servers/:id{[0-9]+}/rename", (c) =>
  mutate(c as AppContext, async (values) => {
    const ctx = c as AppContext;
    const server = await fpga.getFpgaServer(db(ctx), Number(c.req.param("id")));
    if (!server) notFound();
    const renamed = await fpga.renameFpgaServer(db(ctx), server, values["name"] ?? "");
    return `Renamed ${server.name} to ${renamed.name}.`;
  }),
);

adminRoutes.post("/admin/fpga/servers/:id{[0-9]+}/delete", (c) =>
  mutate(c as AppContext, async () => {
    const ctx = c as AppContext;
    const server = await fpga.getFpgaServer(db(ctx), Number(c.req.param("id")));
    if (!server) notFound();
    await fpga.deleteFpgaServer(db(ctx), server);
    return `Deleted server ${server.name}.`;
  }),
);

/** The how-many-where grid posts one `qty-<typeId>-<serverId>` field per cell. */
adminRoutes.post("/admin/fpga/counts", async (c) => {
  const ctx = c as AppContext;
  const values = await formValues(ctx);
  assertCsrf(ctx, values);
  const counts = new Map<string, number>();
  for (const [key, value] of Object.entries(values)) {
    if (!key.startsWith("qty-")) continue;
    const [, typeId, serverId] = key.split("-");
    const quantity = Number.parseInt(value || "0", 10);
    if (!typeId || !serverId || !Number.isInteger(quantity)) {
      return renderIndex(ctx, 400, "Counts must be whole numbers.");
    }
    counts.set(`${typeId}:${serverId}`, quantity);
  }
  try {
    await fpga.setFpgaPlacements(db(ctx), counts);
  } catch (error) {
    if (!(error instanceof ServiceError)) throw error;
    return renderIndex(ctx, error.status, error.message);
  }
  return redirect(ctx, "/admin", "Saved FPGA counts.");
});

function csvResponse(c: AppContext, name: string, body: string): Response {
  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  return c.body(body, 200, {
    "Content-Type": "text/csv; charset=utf-8",
    "Content-Disposition": `attachment; filename="${name}-${stamp}.csv"`,
  });
}

adminRoutes.get("/admin/export/assets.csv", async (c) => {
  const ctx = c as AppContext;
  const rows = await assets.assetsWithStatus(db(ctx), { includeRetired: true });
  return csvResponse(ctx, "assets", assetsCsv(rows));
});

adminRoutes.get("/admin/export/checkouts.csv", async (c) => {
  const ctx = c as AppContext;
  return csvResponse(ctx, "checkouts", checkoutsCsv(await assets.allCheckouts(db(ctx))));
});

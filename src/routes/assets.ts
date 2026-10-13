/** Dashboard, asset pages, checkout and return. */

import { Hono } from "hono";
import type { Session } from "../auth/session";
import { db, formValues, layoutContext, page, redirect, type AppContext } from "../context";
import * as svc from "../services/assets";
import { ServiceError } from "../types";
import { assetOverviewPage } from "../views/assetOverview";
import { assetPage } from "../views/asset";
import { dashboardPage } from "../views/dashboard";
import { assertCsrf, requireUser } from "./guards";

export const assetRoutes = new Hono<{ Bindings: Env; Variables: { session: Session } }>();

async function loadAsset(c: AppContext, id: number) {
  const asset = await svc.getAsset(db(c), id);
  if (!asset) throw Object.assign(new Error("Page not found."), { status: 404 });
  return asset;
}

async function renderAsset(c: AppContext, asset: Awaited<ReturnType<typeof loadAsset>>, status = 200, error?: string) {
  const database = db(c);
  return page(
    c,
    assetPage(layoutContext(c, asset.name), {
      asset,
      active: await svc.activeCheckout(database, asset.id),
      history: await svc.assetHistory(database, asset.id),
      error,
    }),
    status,
  );
}

/** What you land on after signing in: the assets you personally hold. */
assetRoutes.get("/", async (c) => {
  const user = requireUser(c);
  const checkouts = await svc.userCheckouts(db(c), user.email);
  return page(
    c,
    dashboardPage(layoutContext(c, "Dashboard"), {
      current: checkouts.filter((checkout) => checkout.active),
      past: checkouts.filter((checkout) => !checkout.active),
    }),
  );
});

assetRoutes.get("/assets", async (c) => {
  requireUser(c);
  const typeParam = c.req.query("type");
  const typeId = typeParam ? Number.parseInt(typeParam, 10) : null;
  const selected = typeId !== null && Number.isInteger(typeId) ? typeId : null;
  const database = db(c);
  const rows = await svc.assetsWithStatus(database, { typeId: selected });
  return page(
    c,
    assetOverviewPage(layoutContext(c, "Asset overview"), {
      rows,
      types: await svc.assetTypes(database),
      selectedType: selected,
      available: rows.filter(([, checkout]) => checkout === null).length,
    }),
  );
});

assetRoutes.get("/assets/:id{[0-9]+}", async (c) => {
  requireUser(c);
  return renderAsset(c, await loadAsset(c, Number(c.req.param("id"))));
});

assetRoutes.post("/assets/:id{[0-9]+}/checkout", async (c) => {
  const user = requireUser(c);
  const values = await formValues(c);
  assertCsrf(c, values);
  const asset = await loadAsset(c, Number(c.req.param("id")));
  try {
    await svc.checkoutAsset(db(c), asset, user, values["notes"] ?? "");
  } catch (error) {
    if (!(error instanceof ServiceError)) throw error;
    return renderAsset(c, asset, error.status, error.message);
  }
  return redirect(c, values["back"] || `/assets/${asset.id}`, `You checked out ${asset.name}.`);
});

assetRoutes.post("/assets/:id{[0-9]+}/return", async (c) => {
  const user = requireUser(c);
  const values = await formValues(c);
  assertCsrf(c, values);
  const asset = await loadAsset(c, Number(c.req.param("id")));
  let checkout;
  try {
    checkout = await svc.returnAsset(db(c), asset, user);
  } catch (error) {
    if (!(error instanceof ServiceError)) throw error;
    return renderAsset(c, asset, error.status, error.message);
  }
  const message =
    checkout.user_email === user.email
      ? `You returned ${asset.name}.`
      : `Returned ${asset.name} on behalf of ${checkout.user_email}.`;
  return redirect(c, values["back"] || `/assets/${asset.id}`, message);
});

/** FPGA reservations: a timeline of local FPGA use, open to any signed-in user. */

import { Hono } from "hono";
import type { Session } from "../auth/session";
import { db, formValues, layoutContext, page, redirect, type AppContext } from "../context";
import { addDays, todayIso } from "../dates";
import * as svc from "../services/fpga";
import { ServiceError } from "../types";
import { fpgaFormPage } from "../views/fpgaForm";
import { fpgaPage } from "../views/fpga";
import { assertCsrf, requireUser } from "./guards";

export const fpgaRoutes = new Hono<{ Bindings: Env; Variables: { session: Session } }>();

const WINDOW_DAYS = 70; // ~10 weeks visible at once
const PAGE_DAYS = 28; // how far Earlier/Later shift the window
const DEFAULT_LOOKBACK = 7; // show a bit of recent history by default

const defaultWindowStart = () => addDays(todayIso(), -DEFAULT_LOOKBACK);

async function renderTimeline(c: AppContext, windowStart: string, status = 200, error?: string) {
  const windowEnd = addDays(windowStart, WINDOW_DAYS - 1);
  const database = db(c);
  return page(
    c,
    fpgaPage(layoutContext(c, "FPGA reservations"), {
      timeline: await svc.fpgaTimeline(database, windowStart, windowEnd),
      reservations: await svc.fpgaReservations(database),
      windowStart,
      windowEnd,
      prevStart: addDays(windowStart, -PAGE_DAYS),
      nextStart: addDays(windowStart, PAGE_DAYS),
      todayStart: defaultWindowStart(),
      error,
    }),
    status,
  );
}

async function renderForm(
  c: AppContext,
  reservation: Awaited<ReturnType<typeof svc.getFpgaReservation>>,
  values: Record<string, string>,
  status = 200,
  error?: string,
) {
  const database = db(c);
  return page(
    c,
    fpgaFormPage(layoutContext(c, reservation ? "Edit reservation" : "Add FPGA reservation"), {
      reservation,
      values,
      types: await svc.fpgaTypes(database),
      servers: await svc.fpgaServers(database),
      inventory: await svc.fpgaInventoryByType(database),
      error,
    }),
    status,
  );
}

async function loadReservation(c: AppContext, id: number) {
  const reservation = await svc.getFpgaReservation(db(c), id);
  if (!reservation) throw Object.assign(new Error("Page not found."), { status: 404 });
  return reservation;
}

fpgaRoutes.get("/fpga", async (c) => {
  requireUser(c);
  const start = c.req.query("start");
  const windowStart = start && /^\d{4}-\d{2}-\d{2}$/.test(start) ? start : defaultWindowStart();
  return renderTimeline(c, windowStart);
});

fpgaRoutes.get("/fpga/new", async (c) => {
  requireUser(c);
  const today = todayIso();
  return renderForm(c, null, { start_date: today, end_date: today, quantity: "1" });
});

fpgaRoutes.post("/fpga/new", async (c) => {
  const user = requireUser(c);
  const values = await formValues(c);
  assertCsrf(c, values);
  try {
    await svc.saveFpgaReservation(db(c), null, user, values);
  } catch (error) {
    if (!(error instanceof ServiceError)) throw error;
    return renderForm(c, null, values, error.status, error.message);
  }
  return redirect(c, "/fpga", "Added FPGA reservation.");
});

fpgaRoutes.get("/fpga/:id{[0-9]+}/edit", async (c) => {
  const user = requireUser(c);
  const reservation = await loadReservation(c, Number(c.req.param("id")));
  if (reservation.created_by_email !== user.email && !user.isAdmin) {
    throw Object.assign(
      new Error("Only the person who made this reservation or an admin can edit it."),
      { status: 403 },
    );
  }
  const values: Record<string, string> = {};
  for (const field of svc.FPGA_FIELDS) {
    const value = (reservation as unknown as Record<string, unknown>)[field];
    values[field] = value == null ? "" : String(value);
  }
  return renderForm(c, reservation, values);
});

fpgaRoutes.post("/fpga/:id{[0-9]+}/edit", async (c) => {
  const user = requireUser(c);
  const values = await formValues(c);
  assertCsrf(c, values);
  const reservation = await loadReservation(c, Number(c.req.param("id")));
  try {
    await svc.saveFpgaReservation(db(c), reservation, user, values);
  } catch (error) {
    if (!(error instanceof ServiceError)) throw error;
    return renderForm(c, reservation, values, error.status, error.message);
  }
  return redirect(c, "/fpga", "Saved FPGA reservation.");
});

fpgaRoutes.post("/fpga/:id{[0-9]+}/delete", async (c) => {
  const user = requireUser(c);
  const values = await formValues(c);
  assertCsrf(c, values);
  const reservation = await loadReservation(c, Number(c.req.param("id")));
  try {
    await svc.deleteFpgaReservation(db(c), reservation, user);
  } catch (error) {
    if (!(error instanceof ServiceError)) throw error;
    return renderTimeline(c, defaultWindowStart(), error.status, error.message);
  }
  return redirect(c, "/fpga", "Deleted FPGA reservation.");
});

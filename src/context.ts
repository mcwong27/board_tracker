/**
 * Per-request plumbing: the session, the signed-in user, and the helpers routes use
 * to render a page or redirect while keeping the session cookie in sync.
 */

import type { Context } from "hono";
import { csrfToken } from "./auth/csrf";
import { cookieOptionsFor, readSession, sealSession, type Session } from "./auth/session";
import { Db } from "./db";
import { html, type Html } from "./html";
import type { LayoutContext } from "./views/layout";
import type { User } from "./types";

export type AppContext = Context<{ Bindings: Env; Variables: { session: Session } }>;

export async function loadSession(c: AppContext): Promise<Session> {
  const session = await readSession(c.req.raw, c.env.SECRET_KEY);
  c.set("session", session);
  return session;
}

export function currentUser(c: AppContext): User | null {
  const user = c.get("session").user;
  return user ? { email: user.email, name: user.name, isAdmin: user.isAdmin } : null;
}

export function devLoginEnabled(env: Env): boolean {
  return ["1", "true", "yes", "on"].includes((env.DEV_LOGIN ?? "").trim().toLowerCase());
}

/** Build the layout context, generating a CSRF token if the session lacks one. */
export function layoutContext(c: AppContext, title: string): LayoutContext {
  const session = c.get("session");
  const flash = session.flash ?? null;
  if (flash) delete session.flash;
  return {
    title,
    user: currentUser(c),
    devLogin: devLoginEnabled(c.env),
    csrfToken: csrfToken(session),
    flash,
  };
}

/** Render HTML, re-sealing the session (the CSRF token or flash may have changed). */
export async function page(c: AppContext, body: Html, status = 200): Promise<Response> {
  const cookie = await sealSession(c.get("session"), c.env.SECRET_KEY, cookieOptionsFor(c.env.BASE_URL));
  return c.html(body.toString(), status as 200, { "Set-Cookie": cookie });
}

/** Redirect after a POST, carrying any flash message and session changes. */
export async function redirect(c: AppContext, to: string, message?: string): Promise<Response> {
  const session = c.get("session");
  if (message) session.flash = { message, kind: "ok" };
  const cookie = await sealSession(session, c.env.SECRET_KEY, cookieOptionsFor(c.env.BASE_URL));
  return c.body(null, 303, { Location: to, "Set-Cookie": cookie });
}

export function db(c: AppContext): Db {
  return new Db(c.env.DB);
}

/** Form values as a plain object, which is what the services expect. */
export async function formValues(c: AppContext): Promise<Record<string, string>> {
  const form = await c.req.formData();
  const values: Record<string, string> = {};
  for (const [key, value] of form.entries()) {
    if (typeof value === "string") values[key] = value;
  }
  return values;
}

export function notFound(): never {
  throw Object.assign(new Error("Page not found."), { status: 404 });
}

export { html };

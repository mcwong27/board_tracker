/**
 * bTrack: a Cloudflare Worker serving the whole app.
 *
 * Server-rendered HTML, data in D1, and no framework beyond Hono. Everything a
 * request needs is on the request: the session comes out of a signed cookie and the
 * database is a binding, so there is no per-isolate setup to pay for.
 */

import { Hono } from "hono";
import { cookieOptionsFor, sealSession, type Session } from "./auth/session";
import { layoutContext, loadSession, page } from "./context";
import { adminRoutes } from "./routes/admin";
import { assetRoutes } from "./routes/assets";
import { authRoutes } from "./routes/auth";
import { fpgaRoutes } from "./routes/fpga";
import { LoginRequired } from "./routes/guards";
import { errorPage } from "./views/error";

type App = { Bindings: Env; Variables: { session: Session } };

const app = new Hono<App>();

// Read the session once per request; routes and views read it from the context.
app.use("*", async (c, next) => {
  await loadSession(c);
  await next();
});

app.get("/healthz", (c) => c.text("ok"));

app.route("/", authRoutes);
app.route("/", assetRoutes);
app.route("/", fpgaRoutes);
app.route("/", adminRoutes);

const MESSAGES: Record<number, string> = {
  403: "You don't have access to that.",
  404: "Page not found.",
};

app.notFound((c) => renderError(c as never, 404, MESSAGES[404]!));

app.onError(async (error, c) => {
  if (error instanceof LoginRequired) {
    // Remember where they were headed, then send them to sign in. The session has to
    // be re-sealed or `next` is lost before the callback can read it.
    const session = c.get("session");
    if (c.req.method === "GET") session.next = new URL(c.req.url).pathname;
    const cookie = await sealSession(session, c.env.SECRET_KEY, cookieOptionsFor(c.env.BASE_URL));
    return c.body(null, 303, { Location: "/login", "Set-Cookie": cookie });
  }
  const status = Number((error as { status?: number }).status ?? 500);
  if (status === 500) console.error("Unhandled error:", error);
  const message =
    status === 500 ? "Something went wrong." : error.message || MESSAGES[status] || "Error";
  return renderError(c as never, status, message);
});

function renderError(c: Parameters<typeof layoutContext>[0], status: number, message: string) {
  return page(c, errorPage(layoutContext(c, "Error"), { message }), status);
}

export default app;

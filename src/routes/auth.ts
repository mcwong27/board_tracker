/** Sign-in, the OAuth callback, dev login, and sign-out. */

import { Hono } from "hono";
import { checkGroupAccess, GroupsError } from "../auth/groups";
import { handleCallback, IdentityError, startLogin, validateEmail } from "../auth/oidc";
import {
  clearSession, cookieOptionsFor, emptySession, safeNextPath, sealSession,
  signedInSession, type Session,
} from "../auth/session";
import { devLoginEnabled, formValues, layoutContext, page, type AppContext } from "../context";
import { devLoginPage, loginPage } from "../views/login";
import { assertCsrf } from "./guards";

export const authRoutes = new Hono<{ Bindings: Env; Variables: { session: Session } }>();

const NOT_ON_ACCESS_LIST =
  "Your @berkeley.edu account isn't on the access list for this app. " +
  "Ask an admin to add you to the access-list Google Group.";
const SIGN_IN_UNAVAILABLE = "Sign-in is temporarily unavailable. Please try again shortly.";

function oidcConfig(env: Env) {
  return {
    clientId: env.GOOGLE_CLIENT_ID,
    clientSecret: env.GOOGLE_CLIENT_SECRET,
    baseUrl: env.BASE_URL,
  };
}

/** Replace the session wholesale on sign-in, dropping any pre-login state. */
async function signIn(c: AppContext, user: { email: string; name: string; isAdmin: boolean }, to: string) {
  const cookie = await sealSession(
    signedInSession(user),
    c.env.SECRET_KEY,
    cookieOptionsFor(c.env.BASE_URL),
  );
  return c.body(null, 303, { Location: safeNextPath(to), "Set-Cookie": cookie });
}

authRoutes.get("/login", async (c) => {
  const ctx = c as AppContext;
  if (ctx.get("session").user) return c.redirect("/", 303);
  return page(ctx, loginPage(layoutContext(ctx, "Sign in"), {}));
});

authRoutes.get("/login/google", async (c) => {
  const ctx = c as AppContext;
  if (devLoginEnabled(c.env)) return c.redirect("/dev-login", 303);
  const session = ctx.get("session");
  const url = startLogin(session, oidcConfig(c.env), session.next);
  const cookie = await sealSession(session, c.env.SECRET_KEY, cookieOptionsFor(c.env.BASE_URL));
  return c.body(null, 302, { Location: url, "Set-Cookie": cookie });
});

authRoutes.get("/auth/callback", async (c) => {
  const ctx = c as AppContext;
  const query = new URL(c.req.url).searchParams;
  let identity;
  try {
    identity = await handleCallback(ctx.get("session"), query, oidcConfig(c.env));
  } catch (error) {
    const message =
      error instanceof IdentityError ? error.message : "Sign-in failed. Try again.";
    if (!(error instanceof IdentityError)) console.error("OAuth error:", error);
    return page(ctx, loginPage(layoutContext(ctx, "Sign in"), { error: message }), 403);
  }

  let access;
  try {
    access = await checkGroupAccess(
      {
        serviceAccountJson: c.env.GOOGLE_SERVICE_ACCOUNT_JSON,
        usersGroup: c.env.GOOGLE_USERS_GROUP,
        adminsGroup: c.env.GOOGLE_ADMINS_GROUP,
      },
      identity.email,
    );
  } catch (error) {
    // Fail closed: we cannot tell whether this person is authorized.
    console.error("Cloud Identity group check failed for", identity.email, error);
    return page(ctx, loginPage(layoutContext(ctx, "Sign in"), { error: SIGN_IN_UNAVAILABLE }), 403);
  }
  if (!access.allowed) {
    return page(ctx, loginPage(layoutContext(ctx, "Sign in"), { error: NOT_ON_ACCESS_LIST }), 403);
  }
  return signIn(ctx, { ...identity, isAdmin: access.isAdmin }, identity.next);
});

authRoutes.get("/dev-login", async (c) => {
  const ctx = c as AppContext;
  if (!devLoginEnabled(c.env)) return c.notFound();
  return page(ctx, devLoginPage(layoutContext(ctx, "Dev login"), {}));
});

authRoutes.post("/dev-login", async (c) => {
  const ctx = c as AppContext;
  if (!devLoginEnabled(c.env)) return c.notFound();
  const values = await formValues(ctx);
  assertCsrf(ctx, values);
  let email;
  try {
    email = validateEmail(values["email"] ?? "");
  } catch (error) {
    const message = error instanceof IdentityError ? error.message : "Invalid email.";
    return page(
      ctx,
      devLoginPage(layoutContext(ctx, "Dev login"), { error: message, email: values["email"] }),
      403,
    );
  }
  // Dev login never calls Google; admin comes from the checkbox.
  const isAdmin = Boolean(values["admin"]);
  const next = ctx.get("session").next ?? "/";
  return signIn(ctx, { email, name: (values["name"] ?? "").trim() || email, isAdmin }, next);
});

authRoutes.post("/logout", async (c) => {
  const ctx = c as AppContext;
  assertCsrf(ctx, await formValues(ctx));
  return c.body(null, 303, {
    Location: "/login",
    "Set-Cookie": clearSession(cookieOptionsFor(c.env.BASE_URL)),
  });
});

export { emptySession, GroupsError };

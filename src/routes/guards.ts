/** Access checks shared by the routes. */

import { verifyCsrf } from "../auth/csrf";
import { currentUser, type AppContext } from "../context";
import type { User } from "../types";

export class LoginRequired extends Error {}

/** The signed-in user, or a redirect to the login page via LoginRequired. */
export function requireUser(c: AppContext): User {
  const user = currentUser(c);
  if (!user) throw new LoginRequired();
  return user;
}

export function requireAdmin(c: AppContext): User {
  const user = requireUser(c);
  if (!user.isAdmin) throw Object.assign(new Error("Admins only."), { status: 403 });
  return user;
}

/** Every POST must echo the session's CSRF token. Returns the parsed form values. */
export function assertCsrf(c: AppContext, values: Record<string, string>): void {
  if (!verifyCsrf(c.get("session"), new URLSearchParams(values))) {
    throw Object.assign(new Error("Invalid form token. Reload and try again."), { status: 403 });
  }
}

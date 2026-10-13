/** CSRF protection: a per-session token that every POST form must echo back as `csrf_token`. */
import { randomToken, timingSafeEqual } from "./encoding";
import type { Session } from "./session";

export const CSRF_FIELD = "csrf_token";

/**
 * The session's CSRF token, generated on first use. NOTE: this mutates `session`;
 * if it generated a token, the route must re-seal the session (Set-Cookie) so the
 * token the form carries is the one the cookie holds.
 */
export function csrfToken(session: Session): string {
  if (!session.csrf) session.csrf = randomToken(32);
  return session.csrf;
}

type FormLike = { get(name: string): unknown };

/** True only if the form's `csrf_token` is a string equal to the session's token. */
export function verifyCsrf(session: Session, form: FormLike | null | undefined): boolean {
  const expected = session.csrf;
  const submitted = form?.get(CSRF_FIELD);
  if (!expected || typeof submitted !== "string" || !submitted) return false;
  return timingSafeEqual(expected, submitted);
}

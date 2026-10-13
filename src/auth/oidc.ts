/**
 * Google OAuth 2.0 authorization-code flow (replaces Authlib) and identity validation.
 */
import { b64urlDecode, fromUtf8, randomToken, timingSafeEqual } from "./encoding";
import { safeNextPath, type Session } from "./session";

export const ALLOWED_DOMAIN = "berkeley.edu";
export const AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth";
export const TOKEN_URL = "https://oauth2.googleapis.com/token";

/** The user may not sign in (shown to them; messages are safe to display). */
export class IdentityError extends Error {}
/** The OAuth exchange itself failed (bad state, Google error). Show a generic message. */
export class OAuthError extends Error {}

export type OidcConfig = { clientId: string; clientSecret: string; baseUrl: string };
export type Identity = { email: string; name: string };

export function redirectUri(baseUrl: string): string {
  return `${baseUrl.replace(/\/+$/, "")}/auth/callback`;
}

/** Normalize an email and require it to be exactly @berkeley.edu (no subdomains). */
export function validateEmail(email: unknown): string {
  const e = (typeof email === "string" ? email : "").trim().toLowerCase();
  const at = e.lastIndexOf("@");
  const local = at < 0 ? "" : e.slice(0, at);
  const domain = at < 0 ? "" : e.slice(at + 1);
  // Stricter than the Python: also reject a second "@" or whitespace in the local part,
  // since this string is later interpolated into API queries.
  if (!local || domain !== ALLOWED_DOMAIN || /[\s@]/.test(local)) {
    throw new IdentityError(`Only @${ALLOWED_DOMAIN} accounts can sign in.`);
  }
  return e;
}

/**
 * Check ID-token claims and return {email, name}, or throw IdentityError.
 *
 * The `hd` parameter on the authorize URL only steers Google's account picker; anyone
 * can strip it, so these returned claims are what we trust.
 * `clientId` is required (no way to forget the audience check); `now` is epoch seconds.
 */
export function validateIdentity(
  claims: Record<string, unknown>,
  opts: { clientId: string; now?: number },
): Identity {
  const now = opts.now ?? Math.floor(Date.now() / 1000);
  if (!opts.clientId || claims.aud !== opts.clientId) {
    throw new IdentityError("Sign-in token was not issued for this app.");
  }
  if (claims.iss !== "accounts.google.com" && claims.iss !== "https://accounts.google.com") {
    throw new IdentityError("Sign-in token has an unexpected issuer.");
  }
  if (typeof claims.exp !== "number" || !Number.isFinite(claims.exp) || claims.exp <= now) {
    throw new IdentityError("Sign-in token has expired.");
  }
  if (claims.email_verified !== true && claims.email_verified !== "true") {
    throw new IdentityError("Your Google account email is not verified.");
  }
  const email = validateEmail(claims.email);
  if (claims.hd !== ALLOWED_DOMAIN) {
    throw new IdentityError(`Sign in with your @${ALLOWED_DOMAIN} Google account.`);
  }
  const name = (typeof claims.name === "string" ? claims.name : "").trim() || email;
  return { email, name };
}

/**
 * Start sign-in: stores a fresh `state` and `nonce` (and the sanitized return path) in
 * `session` and returns the Google URL to redirect to. The route MUST seal the session
 * into the redirect response, or the callback will (correctly) reject the state.
 */
export function startLogin(session: Session, cfg: OidcConfig, next?: string): string {
  session.state = randomToken(32);
  session.nonce = randomToken(32);
  session.next = safeNextPath(next);
  const params = new URLSearchParams({
    client_id: cfg.clientId,
    redirect_uri: redirectUri(cfg.baseUrl),
    response_type: "code",
    scope: "openid email profile",
    state: session.state,
    nonce: session.nonce,
    hd: ALLOWED_DOMAIN, // UI hint only; enforced in validateIdentity
    prompt: "select_account",
  });
  return `${AUTH_URL}?${params}`;
}

/** Decode a JWT payload WITHOUT verifying a signature. See handleCallback for why. */
export function decodeJwtPayload(jwt: string): Record<string, unknown> {
  const parts = jwt.split(".");
  if (parts.length !== 3) throw new OAuthError("Malformed ID token.");
  try {
    const obj: unknown = JSON.parse(fromUtf8(b64urlDecode(parts[1] as string)));
    if (typeof obj !== "object" || obj === null || Array.isArray(obj)) throw new Error("not object");
    return obj as Record<string, unknown>;
  } catch {
    throw new OAuthError("Malformed ID token.");
  }
}

async function exchangeCode(code: string, cfg: OidcConfig): Promise<string> {
  let res: Response;
  try {
    res = await fetch(TOKEN_URL, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" },
      body: new URLSearchParams({
        code,
        client_id: cfg.clientId,
        client_secret: cfg.clientSecret,
        redirect_uri: redirectUri(cfg.baseUrl),
        grant_type: "authorization_code",
      }),
      signal: AbortSignal.timeout(10_000),
    });
  } catch (e) {
    throw new OAuthError(`Token exchange failed: ${String(e)}`);
  }
  if (!res.ok) throw new OAuthError(`Token endpoint returned ${res.status}`);
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    throw new OAuthError("Token endpoint returned invalid JSON.");
  }
  const idToken = (body as { id_token?: unknown } | null)?.id_token;
  if (typeof idToken !== "string" || !idToken) throw new OAuthError("No id_token in response.");
  return idToken;
}

/**
 * Handle GET /auth/callback. Throws OAuthError (state/exchange problems) or IdentityError
 * (this account may not sign in). Group-membership checks are the caller's next step
 * (groups.checkGroupAccess); do not sign anyone in before that succeeds.
 *
 * The one-time `state`/`nonce` are removed from `session` (single use); the route should
 * seal/replace the session either way.
 *
 * ORDER MATTERS: `state` is verified first, before any network call, so a forged
 * callback (login CSRF) never reaches Google's token endpoint.
 *
 * Why the ID token's SIGNATURE is not verified: the token is received by this server
 * directly from Google's token endpoint (https://oauth2.googleapis.com/token) in a
 * response to a request carrying our client_secret, over TLS with the certificate
 * checked by the runtime. Authenticity therefore comes from the TLS channel to Google,
 * not from the JWS; Google's OpenID Connect docs explicitly permit skipping signature
 * validation in exactly this case. We still validate the claims (aud, iss, exp, nonce,
 * email_verified, hd). This reasoning STOPS HOLDING the moment an ID token reaches us
 * by any other route (from the browser, a query/fragment, a header, a different
 * endpoint, a proxy that terminates TLS): such a token would be attacker-controlled and
 * MUST then be verified against Google's JWKS (https://www.googleapis.com/oauth2/v3/certs).
 * Never pass a client-supplied token to decodeJwtPayload / validateIdentity.
 */
export async function handleCallback(
  session: Session,
  query: URLSearchParams,
  cfg: OidcConfig,
): Promise<Identity & { next: string }> {
  const expectedState = session.state;
  const expectedNonce = session.nonce;
  const next = safeNextPath(session.next);
  delete session.state;
  delete session.nonce;
  delete session.next;

  const submitted = query.get("state");
  if (!expectedState || !submitted || !timingSafeEqual(expectedState, submitted)) {
    throw new OAuthError("State mismatch.");
  }
  if (query.get("error")) throw new OAuthError(`Google returned an error: ${query.get("error")}`);
  const code = query.get("code");
  if (!code) throw new OAuthError("Missing authorization code.");

  const claims = decodeJwtPayload(await exchangeCode(code, cfg));
  const identity = validateIdentity(claims, { clientId: cfg.clientId });
  if (
    !expectedNonce ||
    typeof claims.nonce !== "string" ||
    !timingSafeEqual(expectedNonce, claims.nonce)
  ) {
    throw new OAuthError("Nonce mismatch.");
  }
  return { ...identity, next };
}

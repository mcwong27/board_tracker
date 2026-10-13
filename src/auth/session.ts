/**
 * Signed-cookie sessions (replaces Starlette's SessionMiddleware).
 *
 * Cookie value: base64url(JSON payload) "." base64url(HMAC-SHA256(secret, first part)).
 * The payload is signed, NOT encrypted: anyone holding the cookie can read it, nobody
 * can change it. Never put anything secret in it. `exp` lives inside the signed payload,
 * so expiry is enforced server-side and not just by the browser honouring Max-Age.
 *
 * Group membership is decided once at sign-in and stored here as `user.isAdmin`;
 * it is never re-checked per request.
 */
import { b64urlDecode, b64urlEncode, fromUtf8, utf8 } from "./encoding";

export const SESSION_COOKIE = "btrack_session";
export const SESSION_MAX_AGE = 14 * 24 * 60 * 60; // seconds

export type SessionUser = { email: string; name: string; isAdmin: boolean };

export type Session = {
  user?: SessionUser;
  /** Per-session CSRF token (see csrf.ts). */
  csrf?: string;
  /** In-flight OAuth `state` and OIDC `nonce` (see oidc.ts). */
  state?: string;
  nonce?: string;
  /** Local path to return to after sign-in. Always passed through safeNextPath. */
  next?: string;
  /** One-shot message shown on the next rendered page. */
  flash?: { message: string; kind: string };
};

export type CookieOptions = { secure: boolean };

export function emptySession(): Session {
  return {};
}

/** A fresh post-login session: drops pre-login state including the old CSRF token. */
export function signedInSession(user: SessionUser): Session {
  return { user: { email: user.email, name: user.name, isAdmin: user.isAdmin === true } };
}

/** `https:` deployments get the Secure flag. */
export function cookieOptionsFor(baseUrl: string): CookieOptions {
  return { secure: baseUrl.trim().toLowerCase().startsWith("https://") };
}

/** Only same-site absolute paths; anything else (open-redirect bait) becomes "/". */
export function safeNextPath(next: unknown): string {
  if (typeof next !== "string" || next.length > 2048) return "/";
  if (!next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return "/";
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(next)) return "/";
  return next;
}

const keyCache = new Map<string, Promise<CryptoKey>>();

function hmacKey(secret: string): Promise<CryptoKey> {
  let k = keyCache.get(secret);
  if (!k) {
    k = crypto.subtle.importKey("raw", utf8(secret), { name: "HMAC", hash: "SHA-256" }, false, [
      "sign",
      "verify",
    ]);
    keyCache.set(secret, k);
  }
  return k;
}

type Wire = Session & { exp: number };

function str(v: unknown): string | undefined {
  return typeof v === "string" && v.length > 0 ? v : undefined;
}

/** Rebuild a Session from untrusted-shape JSON, dropping anything malformed. */
function parseWire(obj: unknown, now: number): Session | null {
  if (typeof obj !== "object" || obj === null) return null;
  const o = obj as Record<string, unknown>;
  if (typeof o.exp !== "number" || !Number.isFinite(o.exp) || o.exp <= now) return null;
  const s: Session = {};
  const u = o.user;
  if (typeof u === "object" && u !== null) {
    const { email, name, isAdmin } = u as Record<string, unknown>;
    if (typeof email === "string" && email && typeof name === "string") {
      s.user = { email, name, isAdmin: isAdmin === true };
    }
  }
  const csrf = str(o.csrf);
  if (csrf) s.csrf = csrf;
  const state = str(o.state);
  if (state) s.state = state;
  const nonce = str(o.nonce);
  if (nonce) s.nonce = nonce;
  const next = str(o.next);
  if (next) s.next = safeNextPath(next);
  const flash = o.flash;
  if (typeof flash === "object" && flash !== null) {
    const { message, kind } = flash as Record<string, unknown>;
    if (typeof message === "string" && message) {
      s.flash = { message, kind: typeof kind === "string" && kind ? kind : "ok" };
    }
  }
  return s;
}

function getCookie(header: string | null, name: string): string | undefined {
  if (!header) return undefined;
  for (const part of header.split(";")) {
    const i = part.indexOf("=");
    if (i < 0) continue;
    if (part.slice(0, i).trim() === name) return part.slice(i + 1).trim();
  }
  return undefined;
}

/** Verify a raw cookie value. Never throws; any problem yields an empty session. */
export async function openSession(
  value: string,
  secret: string,
  now = Math.floor(Date.now() / 1000),
): Promise<Session> {
  try {
    if (!secret) return emptySession();
    const parts = value.split(".");
    if (parts.length !== 2) return emptySession();
    const [payload, sig] = parts as [string, string];
    // crypto.subtle.verify compares the MAC in constant time.
    const ok = await crypto.subtle.verify(
      "HMAC",
      await hmacKey(secret),
      b64urlDecode(sig),
      utf8(payload),
    );
    if (!ok) return emptySession();
    return parseWire(JSON.parse(fromUtf8(b64urlDecode(payload))), now) ?? emptySession();
  } catch {
    return emptySession();
  }
}

export async function readSession(request: Request, secret: string): Promise<Session> {
  const value = getCookie(request.headers.get("cookie"), SESSION_COOKIE);
  if (!value) return emptySession();
  return openSession(value, secret);
}

function attrs(opts: CookieOptions, maxAge: number): string {
  return `Path=/; Max-Age=${maxAge}; HttpOnly; SameSite=Lax${opts.secure ? "; Secure" : ""}`;
}

/** Returns the full `Set-Cookie` header value for this session. Throws on an empty secret. */
export async function sealSession(
  data: Session,
  secret: string,
  opts: CookieOptions,
  now = Math.floor(Date.now() / 1000),
): Promise<string> {
  if (!secret) throw new Error("SECRET_KEY is required to sign sessions");
  const wire: Wire = { ...data, exp: now + SESSION_MAX_AGE };
  const payload = b64urlEncode(utf8(JSON.stringify(wire)));
  const mac = await crypto.subtle.sign("HMAC", await hmacKey(secret), utf8(payload));
  return `${SESSION_COOKIE}=${payload}.${b64urlEncode(new Uint8Array(mac))}; ${attrs(opts, SESSION_MAX_AGE)}`;
}

/** `Set-Cookie` value that deletes the session cookie. */
export function clearSession(opts: CookieOptions): string {
  return `${SESSION_COOKIE}=; ${attrs(opts, 0)}`;
}

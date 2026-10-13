/**
 * Cloud Identity Groups client: checks *direct* membership of Google Groups.
 *
 * Used to gate sign-in (users group) and admin rights (admins group). Call it ONCE at
 * sign-in and cache the result in the signed session; never per request.
 *
 * Only direct membership is checked, via the non-transitive `memberships:lookup`
 * endpoint. Nested groups are deliberately not followed: the transitive endpoints need a
 * Workspace Enterprise / Cloud Identity Premium licence and 403 without one.
 *
 * Group addresses are NOT domain-checked: Berkeley's groups live on @lists.berkeley.edu.
 *
 * FAIL CLOSED: only a clean 404 means "not a member". Every other outcome that isn't a
 * 200 (and every network/parse error) throws GroupsError.
 */
import { b64urlEncode, utf8 } from "./encoding";

const API_BASE = "https://cloudidentity.googleapis.com/v1";
export const GROUPS_SCOPE = "https://www.googleapis.com/auth/cloud-identity.groups.readonly";
const TIMEOUT_MS = 10_000;
const TOKEN_SKEW_S = 120; // refresh this long before expiry

export class GroupsError extends Error {}

export type GroupsConfig = {
  /** The GOOGLE_SERVICE_ACCOUNT_JSON secret. */
  serviceAccountJson: string;
  usersGroup: string;
  adminsGroup: string;
};

type ServiceAccount = { clientEmail: string; privateKey: string; tokenUri: string };

// Module-scope caches: live for the isolate, which is the point (saves CPU and round trips).
const tokenCache = new Map<string, { token: string; expiresAt: number }>();
const keyCache = new Map<string, Promise<CryptoKey>>();
const groupNameCache = new Map<string, string>();

/** Test hook. */
export function resetGroupsCache(): void {
  tokenCache.clear();
  keyCache.clear();
  groupNameCache.clear();
}

function parseServiceAccount(json: string): ServiceAccount {
  let o: unknown;
  try {
    o = JSON.parse(json);
  } catch {
    throw new GroupsError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON.");
  }
  const r = (typeof o === "object" && o !== null ? o : {}) as Record<string, unknown>;
  const { client_email: e, private_key: k, token_uri: t } = r;
  if (typeof e !== "string" || typeof k !== "string" || typeof t !== "string" || !e || !k || !t) {
    throw new GroupsError("Service-account JSON lacks client_email, private_key or token_uri.");
  }
  if (!t.startsWith("https://")) throw new GroupsError("Service-account token_uri must be https.");
  return { clientEmail: e, privateKey: k, tokenUri: t };
}

export function pemToDer(pem: string): Uint8Array {
  const body = pem.replace(/-----(BEGIN|END)[^-]*-----/g, "").replace(/\s+/g, "");
  const bin = atob(body);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function signingKey(pem: string): Promise<CryptoKey> {
  let k = keyCache.get(pem);
  if (!k) {
    k = crypto.subtle.importKey(
      "pkcs8",
      pemToDer(pem),
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["sign"],
    );
    keyCache.set(pem, k);
    k.catch(() => keyCache.delete(pem)); // don't cache failures
  }
  return k;
}

/** Build the RS256-signed service-account assertion JWT. Exported for testing. */
export async function signServiceAccountJwt(
  sa: { clientEmail: string; privateKey: string; tokenUri: string },
  now = Math.floor(Date.now() / 1000),
): Promise<string> {
  const header = b64urlEncode(utf8(JSON.stringify({ alg: "RS256", typ: "JWT" })));
  const claims = b64urlEncode(
    utf8(
      JSON.stringify({
        iss: sa.clientEmail,
        scope: GROUPS_SCOPE,
        aud: sa.tokenUri,
        exp: now + 3600,
        iat: now,
      }),
    ),
  );
  const input = `${header}.${claims}`;
  const sig = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    await signingKey(sa.privateKey),
    utf8(input),
  );
  return `${input}.${b64urlEncode(new Uint8Array(sig))}`;
}

async function http(url: string, init: RequestInit, what: string): Promise<Response> {
  try {
    return await fetch(url, { ...init, signal: AbortSignal.timeout(TIMEOUT_MS) });
  } catch (e) {
    throw new GroupsError(`Network error ${what}: ${String(e)}`);
  }
}

async function accessToken(sa: ServiceAccount): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const cached = tokenCache.get(sa.clientEmail);
  if (cached && cached.expiresAt - TOKEN_SKEW_S > now) return cached.token;
  try {
    const assertion = await signServiceAccountJwt(sa, now);
    const res = await http(
      sa.tokenUri,
      {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
          assertion,
        }),
      },
      "obtaining a Cloud Identity access token",
    );
    if (!res.ok) throw new GroupsError(`Token endpoint returned ${res.status}`);
    const body = (await res.json()) as { access_token?: unknown; expires_in?: unknown };
    if (typeof body.access_token !== "string" || !body.access_token) {
      throw new GroupsError("Token endpoint returned no access_token.");
    }
    const ttl = typeof body.expires_in === "number" && body.expires_in > 0 ? body.expires_in : 300;
    tokenCache.set(sa.clientEmail, { token: body.access_token, expiresAt: now + ttl });
    return body.access_token;
  } catch (e) {
    if (e instanceof GroupsError) throw e;
    throw new GroupsError(`Failed to obtain a Cloud Identity access token: ${String(e)}`);
  }
}

async function api(sa: ServiceAccount, pathAndQuery: string): Promise<Response> {
  const token = await accessToken(sa);
  const res = await http(
    `${API_BASE}/${pathAndQuery}`,
    { headers: { authorization: `Bearer ${token}` } },
    "calling the Cloud Identity API",
  );
  if (res.status === 401) tokenCache.delete(sa.clientEmail); // revoked/stale: re-mint next time
  return res;
}

async function groupResourceName(sa: ServiceAccount, groupEmail: string): Promise<string> {
  const cached = groupNameCache.get(groupEmail);
  if (cached) return cached;
  const res = await api(sa, `groups:lookup?${new URLSearchParams({ "groupKey.id": groupEmail })}`);
  if (res.status !== 200) {
    throw new GroupsError(`Could not resolve group ${groupEmail}: API returned ${res.status}`);
  }
  let name: unknown;
  try {
    name = ((await res.json()) as { name?: unknown }).name;
  } catch {
    throw new GroupsError(`Group lookup for ${groupEmail} returned invalid JSON.`);
  }
  // Interpolated into a URL path below: accept only the documented shape.
  if (typeof name !== "string" || !/^groups\/[A-Za-z0-9_-]+$/.test(name)) {
    throw new GroupsError(`Group lookup for ${groupEmail} returned no usable group name.`);
  }
  groupNameCache.set(groupEmail, name);
  return name;
}

/**
 * True if `userEmail` is a direct member of `groupEmail`; false on a clean 404.
 * Throws GroupsError on anything else.
 */
export async function isMember(
  serviceAccountJson: string,
  groupEmail: string,
  userEmail: string,
): Promise<boolean> {
  const sa = parseServiceAccount(serviceAccountJson);
  const group = groupEmail.trim().toLowerCase();
  if (!group) throw new GroupsError("Group address is not configured.");
  const name = await groupResourceName(sa, group);
  const res = await api(
    sa,
    `${name}/memberships:lookup?${new URLSearchParams({ "memberKey.id": userEmail })}`,
  );
  if (res.status === 404) return false;
  if (res.status !== 200) {
    throw new GroupsError(`Membership check for ${group} failed: API returned ${res.status}`);
  }
  return true;
}

/**
 * Sign-in gate, as in the Python `_check_group_access`: must be in the users group;
 * admin iff also in the admins group. `allowed:false` means a clean "not on the access
 * list". Throws GroupsError when the check could not be completed: refuse sign-in.
 */
export async function checkGroupAccess(
  cfg: GroupsConfig,
  email: string,
): Promise<{ allowed: boolean; isAdmin: boolean }> {
  if (!(await isMember(cfg.serviceAccountJson, cfg.usersGroup, email))) {
    return { allowed: false, isAdmin: false };
  }
  const isAdmin = await isMember(cfg.serviceAccountJson, cfg.adminsGroup, email);
  return { allowed: true, isAdmin };
}

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { csrfToken, verifyCsrf } from "../src/auth/csrf";
import { b64urlDecode, b64urlEncode, utf8 } from "../src/auth/encoding";
import {
  checkGroupAccess,
  GroupsError,
  isMember,
  pemToDer,
  resetGroupsCache,
} from "../src/auth/groups";
import {
  handleCallback,
  IdentityError,
  OAuthError,
  startLogin,
  validateIdentity,
} from "../src/auth/oidc";
import {
  clearSession,
  openSession,
  readSession,
  sealSession,
  safeNextPath,
  SESSION_COOKIE,
  type Session,
} from "../src/auth/session";

const CLIENT_ID = "client-123.apps.googleusercontent.com";
const NOW = 1_800_000_000;
const good = {
  aud: CLIENT_ID,
  iss: "https://accounts.google.com",
  exp: NOW + 600,
  email: "Oski@Berkeley.edu",
  email_verified: true,
  hd: "berkeley.edu",
  name: " Oski Bear ",
};
const check = (over: Record<string, unknown>) =>
  validateIdentity({ ...good, ...over }, { clientId: CLIENT_ID, now: NOW });

describe("validateIdentity", () => {
  it("accepts good claims and normalizes", () => {
    expect(check({})).toEqual({ email: "oski@berkeley.edu", name: "Oski Bear" });
    expect(check({ iss: "accounts.google.com", email_verified: "true" }).email).toBe(
      "oski@berkeley.edu",
    );
    expect(check({ name: "" }).name).toBe("oski@berkeley.edu");
  });
  it.each([
    ["unverified email", { email_verified: false }],
    ["string false", { email_verified: "false" }],
    ["missing email_verified", { email_verified: undefined }],
    ["gmail", { email: "oski@gmail.com" }],
    ["subdomain", { email: "oski@eecs.berkeley.edu" }],
    ["suffix domain", { email: "oski@berkeley.edu.evil.com" }],
    ["double at", { email: "a@evil.com@berkeley.edu" }],
    ["empty local", { email: "@berkeley.edu" }],
    ["missing hd", { hd: undefined }],
    ["wrong hd", { hd: "gmail.com" }],
    ["wrong aud", { aud: "other" }],
    ["array aud", { aud: [CLIENT_ID] }],
    ["wrong iss", { iss: "https://evil.example" }],
    ["expired", { exp: NOW - 1 }],
    ["missing exp", { exp: undefined }],
    ["string exp", { exp: String(NOW + 600) }],
  ])("rejects %s", (_n, over) => {
    expect(() => check(over)).toThrow(IdentityError);
  });
  it("keeps the Python error messages", () => {
    expect(() => check({ email_verified: false })).toThrow("Your Google account email is not verified.");
    expect(() => check({ email: "x@gmail.com" })).toThrow("Only @berkeley.edu accounts can sign in.");
    expect(() => check({ hd: undefined })).toThrow("Sign in with your @berkeley.edu Google account.");
  });
});

const SECRET = "s3cret-key-for-tests";
const opts = { secure: true };
const cookieValue = (setCookie: string) => setCookie.split(";")[0]!.slice(SESSION_COOKIE.length + 1);
const reqWith = (setCookie: string) =>
  new Request("https://x.test/", { headers: { cookie: `a=b; ${setCookie.split(";")[0]}` } });

describe("session", () => {
  const user = { email: "oski@berkeley.edu", name: "Oski", isAdmin: true };

  it("round-trips, including isAdmin", async () => {
    const sc = await sealSession({ user, csrf: "tok" }, SECRET, opts);
    const s = await readSession(reqWith(sc), SECRET);
    expect(s.user).toEqual(user);
    expect(s.csrf).toBe("tok");
  });
  it("sets the required cookie attributes", async () => {
    const sc = await sealSession({ user }, SECRET, opts);
    expect(sc).toMatch(/^btrack_session=/);
    for (const a of ["Path=/", "Max-Age=1209600", "HttpOnly", "SameSite=Lax", "Secure"]) {
      expect(sc).toContain(a);
    }
    expect(await sealSession({ user }, SECRET, { secure: false })).not.toContain("Secure");
    expect(clearSession(opts)).toContain("Max-Age=0");
  });
  it("rejects a different secret", async () => {
    const sc = await sealSession({ user }, SECRET, opts);
    expect(await readSession(reqWith(sc), "other-secret")).toEqual({});
  });
  it("rejects a tampered payload and cannot forge isAdmin", async () => {
    const sc = await sealSession({ user: { ...user, isAdmin: false } }, SECRET, opts);
    const [payload, sig] = cookieValue(sc).split(".") as [string, string];
    const obj = JSON.parse(new TextDecoder().decode(b64urlDecode(payload)));
    obj.user.isAdmin = true;
    const forged = `${b64urlEncode(utf8(JSON.stringify(obj)))}.${sig}`;
    expect(await openSession(forged, SECRET)).toEqual({});
    // Re-signing with a guessed secret also fails.
    const resigned = await sealSession(obj, "guess", opts);
    expect(await readSession(reqWith(resigned), SECRET)).toEqual({});
  });
  it("rejects truncated and malformed cookies without throwing", async () => {
    const sc = await sealSession({ user }, SECRET, opts);
    const v = cookieValue(sc);
    for (const bad of [v.slice(0, -4), v.split(".")[0]!, "", ".", "a.b.c", "!!.!!", v + "x"]) {
      expect(await openSession(bad, SECRET)).toEqual({});
    }
    expect(await readSession(new Request("https://x.test/"), SECRET)).toEqual({});
  });
  it("rejects an expired cookie", async () => {
    const sc = await sealSession({ user }, SECRET, opts, 1000);
    expect((await openSession(cookieValue(sc), SECRET, 1000 + 100)).user).toEqual(user);
    expect(await openSession(cookieValue(sc), SECRET, 1000 + 14 * 86400 + 1)).toEqual({});
  });
  it("refuses an empty secret", async () => {
    await expect(sealSession({ user }, "", opts)).rejects.toThrow();
    const sc = await sealSession({ user }, SECRET, opts);
    expect(await openSession(cookieValue(sc), "")).toEqual({});
  });
  it("sanitizes next paths", () => {
    expect(safeNextPath("/assets?x=1")).toBe("/assets?x=1");
    for (const bad of ["//evil.com", "https://evil.com", "/\\evil.com", "evil", undefined, "/a\nb"]) {
      expect(safeNextPath(bad)).toBe("/");
    }
  });
});

describe("csrf", () => {
  it("generates once per session and verifies", () => {
    const s: Session = {};
    const t = csrfToken(s);
    expect(t.length).toBeGreaterThan(30);
    expect(csrfToken(s)).toBe(t);
    expect(verifyCsrf(s, new URLSearchParams({ csrf_token: t }))).toBe(true);
    const fd = new FormData();
    fd.set("csrf_token", t);
    expect(verifyCsrf(s, fd)).toBe(true);
  });
  it("fails on wrong, missing, or file values", () => {
    const s: Session = { csrf: "abc" };
    expect(verifyCsrf(s, new URLSearchParams({ csrf_token: "abd" }))).toBe(false);
    expect(verifyCsrf(s, new URLSearchParams({ csrf_token: "" }))).toBe(false);
    expect(verifyCsrf(s, new URLSearchParams())).toBe(false);
    expect(verifyCsrf(s, null)).toBe(false);
    const fd = new FormData();
    fd.set("csrf_token", new File(["abc"], "abc"));
    expect(verifyCsrf(s, fd)).toBe(false);
    expect(verifyCsrf({}, new URLSearchParams({ csrf_token: "" }))).toBe(false);
    expect(verifyCsrf({}, new URLSearchParams({ csrf_token: "abc" }))).toBe(false);
  });
});

const cfg = { clientId: CLIENT_ID, clientSecret: "shh", baseUrl: "https://bt.example.edu" };
const jwt = (claims: object) =>
  `${b64urlEncode(utf8('{"alg":"RS256"}'))}.${b64urlEncode(utf8(JSON.stringify(claims)))}.sig`;

describe("oidc flow", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("builds the authorization URL", () => {
    const s: Session = {};
    const u = new URL(startLogin(s, cfg, "//evil.com"));
    expect(u.origin + u.pathname).toBe("https://accounts.google.com/o/oauth2/v2/auth");
    const p = u.searchParams;
    expect(p.get("client_id")).toBe(CLIENT_ID);
    expect(p.get("redirect_uri")).toBe("https://bt.example.edu/auth/callback");
    expect(p.get("response_type")).toBe("code");
    expect(p.get("scope")).toBe("openid email profile");
    expect(p.get("hd")).toBe("berkeley.edu");
    expect(p.get("prompt")).toBe("select_account");
    expect(p.get("state")).toBe(s.state);
    expect(s.next).toBe("/");
  });

  it("rejects a mismatched, missing or absent-from-session state before any fetch", async () => {
    const s: Session = {};
    startLogin(s, cfg);
    await expect(
      handleCallback(s, new URLSearchParams({ state: "forged", code: "c" }), cfg),
    ).rejects.toThrow(OAuthError);
    const s2: Session = {};
    startLogin(s2, cfg);
    await expect(handleCallback(s2, new URLSearchParams({ code: "c" }), cfg)).rejects.toThrow(OAuthError);
    await expect(
      handleCallback({}, new URLSearchParams({ state: "x", code: "c" }), cfg),
    ).rejects.toThrow(OAuthError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("exchanges the code and returns the identity", async () => {
    const s: Session = {};
    startLogin(s, cfg, "/fpga");
    const nonce = s.nonce!;
    const state = s.state!;
    fetchMock.mockResolvedValue(
      Response.json({ id_token: jwt({ ...good, nonce, exp: Math.floor(Date.now() / 1000) + 600 }) }),
    );
    const r = await handleCallback(s, new URLSearchParams({ state, code: "abc" }), cfg);
    expect(r).toEqual({ email: "oski@berkeley.edu", name: "Oski Bear", next: "/fpga" });
    expect(s.state).toBeUndefined(); // single use
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("https://oauth2.googleapis.com/token");
    const body = new URLSearchParams((init as RequestInit).body as URLSearchParams);
    expect(body.get("code")).toBe("abc");
    expect(body.get("client_secret")).toBe("shh");
    expect(body.get("grant_type")).toBe("authorization_code");
    expect(body.get("redirect_uri")).toBe("https://bt.example.edu/auth/callback");
  });

  it("rejects bad identity, wrong nonce, and token endpoint errors", async () => {
    const exp = Math.floor(Date.now() / 1000) + 600;
    const run = async (claims: object | null, status = 200) => {
      const s: Session = {};
      startLogin(s, cfg);
      fetchMock.mockResolvedValue(
        status === 200 ? Response.json({ id_token: jwt(claims!) }) : new Response("no", { status }),
      );
      return handleCallback(s, new URLSearchParams({ state: s.state!, code: "c" }), cfg).then(
        () => "ok",
        (e) => e,
      );
    };
    const s0: Session = {};
    startLogin(s0, cfg);
    const nonce = s0.nonce!;
    expect(await run({ ...good, exp, hd: "gmail.com", nonce })).toBeInstanceOf(IdentityError);
    expect(await run({ ...good, exp, nonce: "wrong" })).toBeInstanceOf(OAuthError);
    expect(await run({ ...good, exp })).toBeInstanceOf(OAuthError); // no nonce
    expect(await run(null, 400)).toBeInstanceOf(OAuthError);
    fetchMock.mockRejectedValue(new Error("net"));
    const s: Session = {};
    startLogin(s, cfg);
    await expect(
      handleCallback(s, new URLSearchParams({ state: s.state!, code: "c" }), cfg),
    ).rejects.toThrow(OAuthError);
  });
});

async function makeKeyPem(): Promise<{ pem: string; pub: CryptoKey }> {
  const kp = (await crypto.subtle.generateKey(
    {
      name: "RSASSA-PKCS1-v1_5",
      modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: "SHA-256",
    },
    true,
    ["sign", "verify"],
  )) as CryptoKeyPair;
  const der = new Uint8Array((await crypto.subtle.exportKey("pkcs8", kp.privateKey)) as ArrayBuffer);
  let bin = "";
  for (const b of der) bin += String.fromCharCode(b);
  const lines = btoa(bin).match(/.{1,64}/g)!.join("\n");
  return {
    pem: `-----BEGIN PRIVATE KEY-----\n${lines}\n-----END PRIVATE KEY-----\n`,
    pub: kp.publicKey,
  };
}

describe("groups", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let saJson: string;
  let pub: CryptoKey;
  let route: (url: string) => Response | Promise<Response>;
  const TOKEN_URI = "https://oauth2.googleapis.com/token";

  beforeEach(async () => {
    resetGroupsCache();
    const k = await makeKeyPem();
    pub = k.pub;
    saJson = JSON.stringify({
      client_email: "sa@proj.iam.gserviceaccount.com",
      private_key: k.pem,
      token_uri: TOKEN_URI,
    });
    route = (url) => {
      if (url === TOKEN_URI) return Response.json({ access_token: "tok-1", expires_in: 3600 });
      if (url.includes("groups:lookup")) {
        const g = new URL(url).searchParams.get("groupKey.id")!;
        return Response.json({ name: g.startsWith("admins") ? "groups/ADM" : "groups/USR" });
      }
      if (url.includes("memberships:lookup")) return new Response("{}", { status: 200 });
      return new Response("?", { status: 500 });
    };
    fetchMock = vi.fn((input: unknown) => Promise.resolve(route(String(input))));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  const calls = (needle: string) => fetchMock.mock.calls.filter((c) => String(c[0]).includes(needle));

  it("200 means member; uses non-transitive endpoint and non-berkeley.edu group", async () => {
    expect(await isMember(saJson, "Users@lists.berkeley.edu", "oski@berkeley.edu")).toBe(true);
    const lookup = calls("groups:lookup")[0]!;
    expect(new URL(String(lookup[0])).searchParams.get("groupKey.id")).toBe("users@lists.berkeley.edu");
    const m = new URL(String(calls("memberships:lookup")[0]![0]));
    expect(m.pathname).toBe("/v1/groups/USR/memberships:lookup");
    expect(m.searchParams.get("memberKey.id")).toBe("oski@berkeley.edu");
    expect(String(calls("Transitive").length)).toBe("0");
    const hdr = (calls("memberships:lookup")[0]![1] as RequestInit).headers as Record<string, string>;
    expect(hdr.authorization).toBe("Bearer tok-1");
  });

  it("404 means not a member", async () => {
    route = (url) =>
      url.includes("memberships:lookup")
        ? new Response("nf", { status: 404 })
        : url === TOKEN_URI
          ? Response.json({ access_token: "t", expires_in: 3600 })
          : Response.json({ name: "groups/USR" });
    expect(await isMember(saJson, "u@lists.berkeley.edu", "x@berkeley.edu")).toBe(false);
    expect(await checkGroupAccess({ serviceAccountJson: saJson, usersGroup: "u@l.edu", adminsGroup: "a@l.edu" }, "x@berkeley.edu")).toEqual({ allowed: false, isAdmin: false });
  });

  it.each([403, 500, 401, 429])("membership %i throws (fail closed)", async (status) => {
    const inner = route;
    route = (url) => (url.includes("memberships:lookup") ? new Response("e", { status }) : inner(url));
    await expect(isMember(saJson, "u@l.edu", "x@berkeley.edu")).rejects.toThrow(GroupsError);
  });

  it("network error, bad token response, bad group lookup all throw", async () => {
    const inner = route;
    route = (url) => {
      if (url.includes("memberships:lookup")) throw new Error("boom");
      return inner(url);
    };
    await expect(isMember(saJson, "u@l.edu", "x@berkeley.edu")).rejects.toThrow(GroupsError);

    resetGroupsCache();
    route = (url) => (url === TOKEN_URI ? new Response("no", { status: 400 }) : inner(url));
    await expect(isMember(saJson, "u@l.edu", "x@berkeley.edu")).rejects.toThrow(GroupsError);

    resetGroupsCache();
    route = (url) => (url.includes("groups:lookup") ? new Response("no", { status: 403 }) : inner(url));
    await expect(isMember(saJson, "u@l.edu", "x@berkeley.edu")).rejects.toThrow(GroupsError);

    resetGroupsCache();
    route = (url) => (url.includes("groups:lookup") ? Response.json({ name: "../evil" }) : inner(url));
    await expect(isMember(saJson, "u@l.edu", "x@berkeley.edu")).rejects.toThrow(GroupsError);

    await expect(isMember("not json", "u@l.edu", "x@berkeley.edu")).rejects.toThrow(GroupsError);
  });

  it("reuses the access token and group names across calls", async () => {
    const cfg2 = { serviceAccountJson: saJson, usersGroup: "users@l.edu", adminsGroup: "admins@l.edu" };
    expect(await checkGroupAccess(cfg2, "a@berkeley.edu")).toEqual({ allowed: true, isAdmin: true });
    await checkGroupAccess(cfg2, "b@berkeley.edu");
    expect(calls(TOKEN_URI).length).toBe(1);
    expect(calls("groups:lookup").length).toBe(2); // one per group, then cached
  });

  it("re-mints the token after a 401", async () => {
    const inner = route;
    let first = true;
    route = (url) => {
      if (url.includes("memberships:lookup") && first) {
        first = false;
        return new Response("e", { status: 401 });
      }
      return inner(url);
    };
    await expect(isMember(saJson, "u@l.edu", "x@berkeley.edu")).rejects.toThrow(GroupsError);
    expect(await isMember(saJson, "u@l.edu", "x@berkeley.edu")).toBe(true);
    expect(calls(TOKEN_URI).length).toBe(2);
  });

  it("signs the assertion with RS256 in a verifiable way", async () => {
    await isMember(saJson, "u@l.edu", "x@berkeley.edu");
    const init = calls(TOKEN_URI)[0]![1] as RequestInit;
    const body = new URLSearchParams(init.body as URLSearchParams);
    expect(body.get("grant_type")).toBe("urn:ietf:params:oauth:grant-type:jwt-bearer");
    const [h, c, s] = body.get("assertion")!.split(".") as [string, string, string];
    const dec = (x: string) => JSON.parse(new TextDecoder().decode(b64urlDecode(x)));
    expect(dec(h)).toEqual({ alg: "RS256", typ: "JWT" });
    const claims = dec(c);
    expect(claims.iss).toBe("sa@proj.iam.gserviceaccount.com");
    expect(claims.aud).toBe(TOKEN_URI);
    expect(claims.scope).toBe("https://www.googleapis.com/auth/cloud-identity.groups.readonly");
    expect(claims.exp).toBeGreaterThan(claims.iat);
    const ok = await crypto.subtle.verify(
      "RSASSA-PKCS1-v1_5",
      pub,
      b64urlDecode(s),
      utf8(`${h}.${c}`),
    );
    expect(ok).toBe(true);
    const tampered = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", pub, b64urlDecode(s), utf8(`${h}.${c}x`));
    expect(tampered).toBe(false);
  });

  it("pemToDer strips armor", () => {
    expect(Array.from(pemToDer("-----BEGIN PRIVATE KEY-----\nAQID\n-----END PRIVATE KEY-----\n"))).toEqual([1, 2, 3]);
  });
});

# Deploying bTrack on Cloudflare Workers

The app runs as a Python Worker (FastAPI on Pyodide) with its data in D1, Cloudflare's
managed SQLite. There is no server to maintain and no container to build.

You need a Cloudflare account and the `wrangler` CLI (`npx wrangler`, already a dev
dependency). Everything below is run from the project root.

## 1. Sign in to Cloudflare

```sh
npx wrangler login
```

## 2. Create the database

```sh
npx wrangler d1 create btrack
```

It prints a `database_id`. Put it in `wrangler.jsonc`, replacing the placeholder:

```jsonc
"d1_databases": [
  { "binding": "DB", "database_name": "btrack", "database_id": "<the id it printed>",
    "migrations_dir": "migrations" }
]
```

## 3. Create the schema

```sh
npx wrangler d1 migrations apply btrack --remote
```

`migrations/0001_initial.sql` is the single source of truth for the schema: the same
file builds the local SQLite database the tests run against. To change the schema, add
`migrations/0002_*.sql` and apply it the same way.

## 4. Decide the hostname

`BASE_URL` must be the address people actually type. It builds the OAuth redirect URI
(`BASE_URL/auth/callback`) and decides whether cookies are HTTPS-only, so pointing it at
the wrong host breaks sign-in with `redirect_uri_mismatch`.

There are two hostnames available, and it's worth picking one before deploying rather than
changing it later — each change means editing the OAuth client's redirect URIs too.

**Your own domain** (recommended if you have one). The zone must already be on Cloudflare.
You attach it in step 8:

```jsonc
"BASE_URL": "https://stuff.example.edu"
```

**The free workers.dev address.** The shape is strictly
`<worker-name>.<your-account-subdomain>.workers.dev` — the account subdomain is a single
label, so `stuff.my.team.workers.dev` is not a valid hostname. The worker name is the
`"name"` field at the top of `wrangler.jsonc`, and the account subdomain is shown in the
dashboard under **Workers & Pages**:

```jsonc
"name": "stuff",
"BASE_URL": "https://stuff.<your-account-subdomain>.workers.dev"
```

## 5. Set the public config

Edit the rest of the `vars` block in `wrangler.jsonc`:

```jsonc
"vars": {
  "ENV": "production",
  "DEV_LOGIN": "0",
  "BASE_URL": "https://stuff.example.edu",
  "GOOGLE_CLIENT_ID": "<oauth client id>",
  "GOOGLE_USERS_GROUP": "btrack-users@lists.berkeley.edu",
  "GOOGLE_ADMINS_GROUP": "btrack-admins@lists.berkeley.edu"
}
```

## 6. Set the secrets

Secrets never go in `wrangler.jsonc`; they are encrypted by Cloudflare.

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(48))" | npx wrangler secret put SECRET_KEY
npx wrangler secret put GOOGLE_CLIENT_SECRET
npx wrangler secret put GOOGLE_SERVICE_ACCOUNT_JSON   # paste the whole key JSON
```

`GOOGLE_SERVICE_ACCOUNT_JSON` holds the Cloud Identity service-account key as inline
JSON — Workers has no filesystem, so the file-path option isn't available there. See
[Google Groups setup](google-groups.md) for how to create it, and
[Google OAuth setup](google-oauth.md) for the client ID and secret.

## 7. Deploy

```sh
uv run pywrangler deploy
```

## 8. Put it on your own domain

Skip this if you're staying on workers.dev.

1. Make sure the zone (`example.edu`) is on your Cloudflare account — its nameservers must
   point at Cloudflare. A subdomain of a zone you don't control won't work.
2. **Workers & Pages → your worker → Settings → Domains & Routes → Add → Custom Domain**,
   and enter the full hostname, e.g. `stuff.example.edu`.
3. Cloudflare creates the DNS record and issues the certificate itself. There's no CNAME to
   maintain by hand, and it usually takes under a minute.
4. Check `BASE_URL` in `wrangler.jsonc` matches that hostname, then `uv run pywrangler deploy`
   again if you changed it.
5. Once the custom domain serves the app, **disable the workers.dev route** in the same
   Domains & Routes panel. Leaving both live means two hostnames with separate sessions, and
   sign-ins started on the workers.dev one bounce to the custom domain.

## 9. Register the redirect URI and sign in

Add `BASE_URL/auth/callback` (e.g. `https://stuff.example.edu/auth/callback`) to the OAuth
client's **Authorized redirect URIs** — see [Google OAuth setup](google-oauth.md). If you
deployed on workers.dev first and later moved to a custom domain, add the new one; you can
drop the old entry once the workers.dev route is disabled.

Then open the site. The first admin must already be a member of `GOOGLE_ADMINS_GROUP`, and
of `GOOGLE_USERS_GROUP` to get in at all.

## Running locally

Against a local D1 database, with the dev login form instead of Google:

```sh
npx wrangler d1 execute btrack --local --file=migrations/0001_initial.sql   # once
uv run pywrangler dev
```

`.dev.vars` supplies the local settings (`DEV_LOGIN=1`) and is gitignored. Local state
lives in `.wrangler/`.

For a faster loop without the Workers runtime, the same app runs under uvicorn against a
plain SQLite file — see README.md. The tests use that path, so they run in about a second.

## Backups

D1 exports the whole database to a file:

```sh
npx wrangler d1 export btrack --remote --output btrack-$(date +%Y%m%d).sql
```

Keep those somewhere off Cloudflare. To restore into a fresh database:

```sh
npx wrangler d1 execute btrack --remote --file=btrack-20260101.sql
```

Cloudflare also keeps point-in-time restores for D1; `wrangler d1 time-travel` can roll a
database back within the retention window.

## Logs and troubleshooting

```sh
npx wrangler tail            # live logs from the deployed Worker
```

- **`redirect_uri_mismatch` on sign-in** — `BASE_URL` and the hostname you actually visited
  disagree, or that exact callback URL isn't in the OAuth client. They must match down to the
  scheme and host, with no trailing slash.
- **The site loads but sign-in redirects to a different hostname** — `BASE_URL` still points
  at the old address. Update it and redeploy; disable the route you're no longer using.
- **500 on every page** — usually a missing secret. `npx wrangler secret list` shows which
  are set; `Settings.validate()` refuses to start without the Google config unless
  `DEV_LOGIN=1`.
- **"can't start new thread"** — a route or dependency was defined as `def` instead of
  `async def`. Workers has no threads, and FastAPI would otherwise run it in a threadpool.
- **`CpuLimitExceeded` / Error 1101 on cold requests** — something expensive moved out of
  module scope. The free plan gives only 10ms of CPU per request, while global scope gets a
  1s startup budget and is snapshotted at deploy time, so imports, `create_app(defer=True)`,
  template compilation and the middleware stack all have to happen there. Warm requests
  succeeding while cold ones 500 is the signature of this.
- **"Top-level await in module is unsettled"** — a package that can't be imported during
  module evaluation (authlib, google-auth, httpx2) was hoisted to module scope. Import it
  inside the function that uses it.
- **`BASE_URL must not have a path prefix on Workers`** — deploy at a bare hostname; the app
  is constructed before BASE_URL is known, so a prefix can't be applied to routing.
- **Sign-in says you're not on the access list** — the account isn't a direct member of
  `GOOGLE_USERS_GROUP`. Nested groups are not followed; see
  [Google Groups setup](google-groups.md).
- **Dependency fails to bundle** — it needs a C extension with no WebAssembly wheel. Keep
  such packages (uvicorn, pytest, ruff) in the `dev` dependency group so they stay out of
  the Worker bundle.

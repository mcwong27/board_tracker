# bTrack

A small web app for tracking who has which lab asset — carrier boards, instruments,
cables, whatever you decide to track — plus a timeline of who is using which FPGAs,
where, and when. People sign in with their @berkeley.edu Google account; access and
admin rights come from two Google Groups.

- **Dashboard:** where you land after signing in — the assets you currently hold, and your past checkouts
- **Asset overview:** every active asset with its status, holder, and checkout time, filterable by type
- **Check out / return:** one active checkout per asset (enforced by the database). Only the holder or an admin can return one.
- A **history page** for each asset
- **FPGA reservations:** a timeline of local FPGA use — project, how many, point of
  contact, special requests, dates, and which server. One row per physical board, each
  with its own hue, collapsed into a single muxed line per model until you expand it.
  Booking more than a server holds is allowed but flagged.
- **Admin:** one page for both systems — add/edit/retire assets, manage asset types,
  manage FPGA types, servers and per-server counts, force-return, CSV export, and CSV
  **import** of assets (same columns as the export, so you can download, edit in a
  spreadsheet, and upload back).
- **Light and dark themes,** following the system setting until you pick one

Stack: a **TypeScript Cloudflare Worker** — [Hono](https://hono.dev) for routing, HTML
from tagged template literals, and **D1** (Cloudflare's managed SQLite) reached with
plain SQL. No ORM and no client-side framework; the only JavaScript in the browser is a
few lines for the theme toggle and the timeline hover cards.

## Docs

- [Requirements](docs/spec.md): what the app must do
- [Google OAuth setup](docs/google-oauth.md): creating the sign-in client
- [Google Groups setup](docs/google-groups.md): the access list and admin rights, no Workspace admin needed
- [Deploying](docs/deployment.md): Cloudflare Workers + D1, hostnames and custom domains, secrets, migrations, backups

## Local development

Requires Node and npm.

```sh
npm install
npm run db:local      # create the local D1 schema, once
npm run dev           # http://localhost:8787
```

`.dev.vars` supplies the local settings and is gitignored; it sets `DEV_LOGIN=1`, which
replaces Google sign-in with a plain form. Sign in as any @berkeley.edu address and
**tick the "admin" box** to get the Admin pages. Dev login never calls Google.

A fresh database has no asset types and no FPGA servers, so visit **Admin** first and
add one of each. The FPGA models the lab already has (U250, XB10, VCU118, U200, U280,
V80, RHS Research Nitefury II) are seeded by the migration, and admins can add more.

```sh
npm test           # Vitest, running inside the Workers runtime against a real local D1
npm run typecheck
```

**Schema changes:** add `migrations/0002_whatever.sql`, then `npm run db:local` (add
`npm run db:remote` for the deployed database). The same files build the database the
tests run against, so there is one source of truth.

## Project layout

```
src/
  index.ts            the Worker: middleware, routes, error handling
  context.ts          per-request session, current user, render/redirect helpers
  html.ts             the html`` tagged template (escapes every interpolation)
  db.ts               D1 wrapper: query / queryOne / value / run / batch
  types.ts dates.ts   domain shapes and date helpers
  services/           business rules and SQL: assets.ts, fpga.ts, csv.ts
  routes/             HTTP glue: assets, fpga, admin, auth, guards
  auth/               signed-cookie sessions, CSRF, Google OIDC, Cloud Identity groups
  views/              one module per page, plus layout.ts and partials.ts
public/static/        style.css (UC Berkeley colors, light + dark), app.js
migrations/           D1 migrations; also the schema the tests build from
test/                 Vitest specs, including an end-to-end integration suite
docs/                 requirements, OAuth setup, Groups setup, deployment guide
wrangler.jsonc        bindings and vars
```

## Configuration

Non-secret settings live in `wrangler.jsonc` under `vars`; secrets are set with
`wrangler secret put` and never appear in the repo. Locally both come from `.dev.vars`.

| Setting | Purpose |
| --- | --- |
| `SECRET_KEY` | *(secret)* Signs session cookies. Generate with `node -e "console.log(crypto.randomUUID()+crypto.randomUUID())"` |
| `GOOGLE_CLIENT_ID` | OAuth client ([setup](docs/google-oauth.md)) |
| `GOOGLE_CLIENT_SECRET` | *(secret)* the matching client secret |
| `BASE_URL` | Public URL, no trailing slash and no path prefix. The OAuth redirect URI is `BASE_URL/auth/callback` |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | *(secret)* Service account that checks group membership ([setup](docs/google-groups.md)) |
| `GOOGLE_USERS_GROUP` | Membership in this group is required to sign in |
| `GOOGLE_ADMINS_GROUP` | Membership in this group grants admin rights |
| `DEV_LOGIN` | `1` replaces Google sign-in with a plain form. Local only |
| `ENV` | `production` or `development` |

Signing in requires all of: a verified Google account, an exact `@berkeley.edu` address
with `hd=berkeley.edu` in the ID token, and membership of `GOOGLE_USERS_GROUP`. Group
membership is checked once at sign-in and cached in the signed session cookie. If the
Cloud Identity API can't be reached, sign-in fails rather than falling back to granting
access.

# bTrack

Server-rendered app for tracking who has which lab asset (boards, instruments, cables —
admins define the types) plus a timeline of FPGA reservations. Berkeley-only Google
sign-in, gated by Google Groups. Requirements: docs/spec.md.
Setup: README.md. OAuth: docs/google-oauth.md. Groups: docs/google-groups.md.
Deployment: docs/deployment.md.

A **TypeScript Cloudflare Worker**: Hono for routing, HTML from tagged template
literals, data in **D1** (Cloudflare's managed SQLite) via plain SQL. No ORM, no
client-side framework, no build step beyond esbuild-via-wrangler.

## Commands
- Install: `npm install`
- Run locally: `npm run dev` (wrangler dev; settings come from `.dev.vars`)
- Create the local D1 schema once: `npm run db:local`
- Apply migrations to the deployed database: `npm run db:remote`
- Test: `npm test` (Vitest inside workerd, against a real local D1)
- Typecheck: `npm run typecheck`
- Regenerate binding types after editing wrangler.jsonc: `npx wrangler types`
- Deploy: `npm run deploy`

## Layout
- `src/index.ts` the Worker: middleware, route mounting, error handling
- `src/context.ts` per-request plumbing — session, current user, `page()`/`redirect()`
  helpers that keep the session cookie in sync
- `src/db.ts` the D1 wrapper (`query`, `queryOne`, `value`, `run`, `batch`)
- `src/html.ts` the `html` tagged template; it escapes every interpolation
- `src/types.ts` domain shapes; `src/dates.ts` date/time helpers
- `src/services/` all business rules and SQL — `assets.ts`, `fpga.ts`, `csv.ts`
- `src/routes/` thin HTTP glue; `guards.ts` holds `requireUser`/`requireAdmin`/`assertCsrf`
- `src/auth/` `session.ts` (signed cookies), `csrf.ts`, `oidc.ts` (Google sign-in),
  `groups.ts` (Cloud Identity membership), `encoding.ts`
- `src/views/` one module per page, plus `layout.ts` and `partials.ts`
- `public/static/` style.css and app.js, served by the Workers assets binding at `/static/*`
- `migrations/*.sql` D1 migrations, and the schema the tests build from
- `test/` Vitest specs; `test/helpers.ts` applies the real migration SQL

## Invariants
- **Escape by default.** Build markup with `` html`` `` only. It escapes interpolations;
  `raw()` opts out and should be rare and obvious. Never concatenate HTML strings.
- **Every POST checks CSRF** via `assertCsrf(c, values)` in the route, and every form
  carries the hidden `csrf_token`. `verifyCsrf` returns a boolean — never ignore it.
- One active checkout per asset is enforced by the partial unique index
  `uq_checkout_active_asset`; don't rely on UI checks alone.
- Use `db.batch()` when several writes must land together: it is D1's only atomic
  primitive (there are no interactive transactions).
- Sign-in requires a verified, exact `@berkeley.edu` address with `hd=berkeley.edu`
  AND membership of `GOOGLE_USERS_GROUP`. Admin rights come from `GOOGLE_ADMINS_GROUP`.
  Both are checked once at sign-in and cached in the signed session; group lookups
  **fail closed** — an API error refuses sign-in rather than granting it.
- The ID token's signature is deliberately not verified: it arrives directly from
  Google's token endpoint over TLS. That reasoning is documented in `oidc.ts` and stops
  holding the moment a token arrives by any other route.
- The OAuth `state` is checked before any network call, and consumed once.
- Only the holder or an admin may return an asset; only the creator or an admin may
  edit or delete an FPGA reservation.
- Dates and datetimes are text, as SQLite stores them: `YYYY-MM-DD` and
  `YYYY-MM-DD HH:MM:SS` (naive UTC). `localDateTime()` renders Berkeley local time.
- Asset types are fully admin-managed: a fresh database has none, and a type in use
  can't be deleted.
- Pages: `/` is the signed-in user's own dashboard, `/assets` is the all-assets
  overview, `/fpga` is the reservation timeline, `/admin` is the single admin page for
  both systems. There is no BASE_URL path prefix support; deploy at a bare hostname.
- FPGA reservations are a shared calendar, not an allocator: booking more than a server
  holds is allowed but flagged (`oversubscribed`). Boards are derived from the admin
  counts, so 4 in a server become `#1`..`#4`, each with its own hue.
- Themes: define colors as tokens on `:root`, override under both
  `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }` and
  `:root[data-theme="dark"]` so the toggle wins in both directions.

## Testing
Tests run in the real runtime (workerd) against a real local D1, so they catch
runtime-specific behaviour. `test/integration.spec.ts` drives the Worker end to end
through a cookie-jar client — note it sets `redirect: "manual"`, because a `Fetcher`
follows redirects by default and would otherwise swallow the app's 303s.

The D1 binding must never be marked `remote` in `wrangler.jsonc`: that points local dev
and the test suite at the **deployed** database. `test/isolation.spec.ts` guards this.

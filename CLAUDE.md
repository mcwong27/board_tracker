# bTrack

FastAPI + Jinja (server-rendered, no JS framework) app for tracking who has which lab asset
(boards, instruments, cables — admins define the types) plus a timeline of FPGA reservations.
Berkeley-only Google sign-in, gated by Google Groups. Requirements: docs/spec.md.
Setup: README.md. OAuth: docs/google-oauth.md. Groups: docs/google-groups.md.
Deployment: docs/deployment.md.

Runs as a **Python Worker on Cloudflare** (FastAPI on Pyodide) with data in **D1**.
The same code runs locally under uvicorn against a SQLite file, which is what the tests use.

## Commands
- Install deps: `uv sync`
- Run locally (fast loop, SQLite, no Workers runtime):
  `DEV_LOGIN=1 ENV=development uv run uvicorn --factory app.main:create_app --reload --app-dir src`
  (tick the "admin" box on the dev login form to get admin rights)
- Run on the real Workers runtime: `uv run pywrangler dev` (settings come from `.dev.vars`)
- Create the local D1 schema once: `npx wrangler d1 execute btrack --local --file=migrations/0001_initial.sql`
- Apply migrations to the deployed database: `npx wrangler d1 migrations apply btrack --remote`
- Deploy: `uv run pywrangler deploy`
- Test: `uv run pytest`
- Lint/format: `uv run ruff check . && uv run ruff format --check .` (fix: `uv run ruff check --fix . && uv run ruff format .`)

## Layout
Only `src/` is bundled into the Worker, so all Python and all templates live there.
- `src/entry.py` Worker entry point; builds the app once per isolate from the bindings
- `src/app/main.py` app factory (`create_app(settings, database=None)`), middleware, error handlers
- `src/app/config.py` settings; `from_workers_env()` reads bindings, `from_env()` reads os.environ;
  `Settings.validate()` refuses unsafe config
- `src/app/db.py` the `Database` interface with two backends — `D1Database` (production) and
  `SqliteDatabase` (tests/dev) — plus the `get_db` dependency
- `src/app/models.py` row mappers between SQL text and Python values (no ORM)
- `src/app/auth.py` identity validation, `CurrentUser` / `AdminUser` dependencies
- `src/app/groups.py` Cloud Identity group-membership checks (the access list and admin rights)
- `src/app/services.py` all business rules and SQL; routes in `src/app/routes/` stay thin
- `src/app/routes/admin.py` every route here gets `require_admin` from the router; assets and the
  FPGA inventory are separate for users but share the one admin page
- `src/app/csrf.py` every POST route needs `dependencies=[Depends(verify_csrf)]` and forms need the hidden `csrf_token`
- `src/app/urls.py` + `path()` template global: build URLs with these so a BASE_URL path prefix works
- `public/static/` style.css and app.js, served by the Workers assets binding at `/static/*`
- `migrations/*.sql` D1 migrations, and the schema the tests build their SQLite file from
- `tests/` pytest against `SqliteDatabase`; `wrangler.jsonc` bindings and vars

## Invariants
- **Every route and dependency must be `async def`.** Workers has no threads, so FastAPI
  running a sync handler or dependency in a threadpool raises "can't start new thread".
- **Keep expensive work at module scope.** The free plan allows 10ms of CPU per request;
  global scope gets a 1s startup budget and is captured in the deploy-time snapshot.
  `src/entry.py` therefore imports FastAPI and calls `create_app(defer=True)` at module
  scope — importing (~220ms) or building the app inside `fetch` raises `CpuLimitExceeded`.
  Templates are precompiled in `templating.py` and the middleware stack is pre-built for
  the same reason.
- **Some packages can't be imported at module scope on Workers**: authlib, google-auth and
  httpx2 fail with "Top-level await in module is unsettled". Import them inside the
  functions that use them (see `auth.make_oauth`, `auth.get_oauth`, `groups.py`).
- Because the app is built before the bindings exist, settings are attached on the first
  request and `DeferredSessionMiddleware` builds the session signer then. A BASE_URL path
  prefix can't work on Workers and `validate(on_workers=True)` rejects it.
- Runtime dependencies must work under Pyodide. Anything needing a C extension without a
  WebAssembly wheel (uvicorn, pytest, ruff) belongs in the `dev` dependency group.
- One active checkout per asset is enforced by the partial unique index
  `uq_checkout_active_asset`; don't rely on UI checks alone.
- Write SQL once: D1 is SQLite, so the same statements run against both backends. Use
  `db.batch()` when several writes must land together (it is the only atomic primitive D1 has).
- Sign-in is restricted server-side to verified exact @berkeley.edu emails with `hd=berkeley.edu`
  AND membership of `GOOGLE_USERS_GROUP`. Admin rights come from `GOOGLE_ADMINS_GROUP`.
  Both are checked once at sign-in and cached in the signed session; group lookups fail closed.
- Only the holder or an admin may return an asset (`services.return_asset`).
- Store naive UTC datetimes (`app.models.utcnow`); templates show local time via `|localtime`.
  SQLite has no date types: datetimes are 'YYYY-MM-DD HH:MM:SS', dates 'YYYY-MM-DD'.
- Asset types are fully admin-managed: a fresh database has none, and a type in use can't be deleted.
- Pages: `/` is the signed-in user's own dashboard, `/assets` is the all-assets overview,
  `/fpga` is the reservation timeline, `/admin` is the single admin page for both systems.
- FPGA reservations are a shared calendar, not an allocator: booking more than a server holds is
  allowed but flagged (`services.oversubscribed`). Only the creator or an admin may edit/delete one.
- Themes: define colors as tokens on `:root`, override under both
  `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }` and `:root[data-theme="dark"]`
  so the toggle wins in both directions. Never give a color its only definition inside one of those.

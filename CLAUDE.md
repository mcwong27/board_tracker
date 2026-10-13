# bTrack

FastAPI + Jinja (server-rendered, no JS framework) app for tracking who has which lab asset
(boards, instruments, cables — admins define the types) plus a timeline of FPGA reservations.
Berkeley-only Google sign-in, gated by Google Groups. Requirements: docs/spec.md.
Setup: README.md. OAuth: docs/google-oauth.md. Groups: docs/google-groups.md.
Deployment and backups: docs/deployment.md.

## Commands
- Install deps: `uv sync`
- Run locally: `DEV_LOGIN=1 ENV=development uv run uvicorn --factory app.main:create_app --reload`
  (tick the "admin" box on the dev login form to get admin rights)
- Migrate DB: automatic on app startup (`app/migrate.py`); manual: `uv run alembic upgrade head`
- New migration: `uv run alembic revision --autogenerate -m "..."` (review the generated file)
- Test: `uv run pytest`
- Lint/format: `uv run ruff check . && uv run ruff format --check .` (fix: `uv run ruff check --fix . && uv run ruff format .`)
- Docker: `docker compose up -d --build`; backups via `deploy/backup.sh` / `deploy/restore.sh`

## Layout
- `app/main.py` app factory (`create_app(settings)`), middleware, error handlers
- `app/config.py` settings from env vars; `Settings.validate()` refuses unsafe config
- `app/auth.py` identity validation (`validate_identity`), `CurrentUser` / `AdminUser` dependencies
- `app/groups.py` Cloud Identity group-membership checks (the access list and admin rights)
- `app/services.py` all business rules; routes in `app/routes/` stay thin
- `app/routes/admin.py` every route here gets `require_admin` from the router; assets and the
  FPGA inventory are separate for users but share the one admin page
- `app/csrf.py` every POST route needs `dependencies=[Depends(verify_csrf)]` and forms need the hidden `csrf_token`
- `app/urls.py` + `path()` template global: build URLs with these so a BASE_URL path prefix works
- `app/static/app.js` the only JS: theme toggle and timeline hover cards (no framework)
- `migrations/` Alembic; `tests/` pytest (each test gets a freshly migrated SQLite file)
- `deploy/` container entrypoint, Caddy example, backup/restore scripts; `docs/` spec and guides

## Invariants
- One active checkout per asset is enforced by the partial unique index
  `uq_checkout_active_asset`; don't rely on UI checks alone.
- Sign-in is restricted server-side to verified exact @berkeley.edu emails with `hd=berkeley.edu`
  AND membership of `GOOGLE_USERS_GROUP`. Admin rights come from `GOOGLE_ADMINS_GROUP`.
  Both are checked once at sign-in and cached in the signed session; group lookups fail closed.
- Only the holder or an admin may return an asset (`services.return_asset`).
- Store naive UTC datetimes (`app.models.utcnow`); templates show local time via `|localtime`.
- Asset types are fully admin-managed: a fresh database has none, and a type in use can't be deleted.
- Pages: `/` is the signed-in user's own dashboard, `/assets` is the all-assets overview,
  `/fpga` is the reservation timeline, `/admin` is the single admin page for both systems.
- FPGA reservations are a shared calendar, not an allocator: booking more than a server holds is
  allowed but flagged (`services.oversubscribed`). Only the creator or an admin may edit/delete one.
- Themes: define colors as tokens on `:root`, override under both
  `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }` and `:root[data-theme="dark"]`
  so the toggle wins in both directions. Never give a color its only definition inside one of those.

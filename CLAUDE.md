# Lab Board Checkout Tracker

FastAPI + Jinja (server-rendered, no JS framework) app for tracking who has which lab board.
Berkeley-only Google sign-in; admins (ADMIN_EMAILS) manage inventory. Requirements: docs/spec.md.
Setup: README.md. OAuth: docs/google-oauth.md. Deployment and backups: docs/deployment.md.

## Commands
- Install deps: `uv sync`
- Run locally: `DEV_LOGIN=1 ENV=development ADMIN_EMAILS=you@berkeley.edu uv run uvicorn --factory app.main:create_app --reload`
- Migrate DB: automatic on app startup (`app/migrate.py`); manual: `uv run alembic upgrade head`
- New migration: `uv run alembic revision --autogenerate -m "..."` (review the generated file)
- Test: `uv run pytest`
- Lint/format: `uv run ruff check . && uv run ruff format --check .` (fix: `uv run ruff check --fix . && uv run ruff format .`)
- Docker: `docker compose up -d --build`; backups via `deploy/backup.sh` / `deploy/restore.sh`

## Layout
- `app/main.py` app factory (`create_app(settings)`), middleware, error handlers
- `app/config.py` settings from env vars; `Settings.validate()` refuses unsafe config
- `app/auth.py` identity validation (`validate_identity`), `CurrentUser` / `AdminUser` dependencies
- `app/services.py` all business rules; routes in `app/routes/` stay thin
- `app/routes/admin.py` every route here gets `require_admin` from the router
- `app/csrf.py` every POST route needs `dependencies=[Depends(verify_csrf)]` and forms need the hidden `csrf_token`
- `app/urls.py` + `path()` template global: build URLs with these so a BASE_URL path prefix works
- `migrations/` Alembic; `tests/` pytest (each test gets a freshly migrated SQLite file)
- `deploy/` container entrypoint, Caddy example, backup/restore scripts; `docs/` spec and guides

## Invariants
- One active checkout per board is enforced by the partial unique index
  `uq_checkout_active_board`; don't rely on UI checks alone.
- Sign-in is restricted server-side to verified exact @berkeley.edu emails with `hd=berkeley.edu`.
- Only the holder or an admin may return a board (`services.return_board`).
- Store naive UTC datetimes (`app.models.utcnow`); templates show local time via `|localtime`.

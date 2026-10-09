# Lab Board Checkout Tracker

FastAPI + Jinja web app for tracking who has which lab board. Berkeley Google sign-in;
admins manage inventory. See SPEC.md for requirements.

## Commands
- Install deps: `uv sync`
- Migrate DB: `uv run alembic upgrade head`
- Test: `uv run pytest`
- Lint/format: `uv run ruff check . && uv run ruff format --check .` (fix: `uv run ruff check --fix . && uv run ruff format .`)

## Layout
- `app/config.py` settings from env vars (validated at startup)
- `app/models.py` SQLAlchemy models; `migrations/` Alembic (add a revision for every schema change)
- `tests/` pytest; each test gets a fresh migrated SQLite file (`tests/conftest.py`)

## Invariants
- One active checkout per board is enforced by the partial unique index
  `uq_checkout_active_board`; don't rely on UI checks alone.
- Store naive UTC datetimes (`app.models.utcnow`).

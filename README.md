# Lab Board Checkout Tracker

A small web app for tracking who has which lab board (Bora Lake and Sophia Lake carrier boards,
and others). People sign in with their @berkeley.edu Google account to check boards out and
back in. Admins manage the inventory and can export everything as CSV.

- **Dashboard:** every active board with its status, holder, and checkout time, filterable by type
- **Check out / return:** one active checkout per board (enforced by the database). Only the holder or an admin can return a board.
- **My boards** and a **history page** for each board
- **Admin:** add, edit, retire, and restore boards, add board types, force-return, CSV export

Stack: Python, FastAPI, Jinja templates, SQLite (SQLAlchemy + Alembic), managed with
[uv](https://docs.astral.sh/uv/).

## Docs

- [Requirements](docs/spec.md): what the app must do
- [Google OAuth setup](docs/google-oauth.md): creating the sign-in client, testing real sign-in locally
- [Deploying](docs/deployment.md): Linux + Docker + Caddy, updates, backup and restore

## Local development

Requires uv (`brew install uv`).

```sh
cd board_tracker                          # run everything from the project folder
uv sync                                   # install dependencies into .venv

# Run with the dev login form (no Google setup needed). The app creates or upgrades
# data/tracker.db on startup.
DEV_LOGIN=1 ENV=development ADMIN_EMAILS=you@berkeley.edu \
  uv run uvicorn --factory app.main:create_app --reload
```

Open http://localhost:8000 and sign in as any @berkeley.edu address. Sign in as the address in
`ADMIN_EMAILS` to see the Admin pages.

Tests and lint:

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

**Schema changes:** edit `app/models.py`, then generate and review a migration with
`uv run alembic revision --autogenerate -m "describe the change"`. The app applies pending
migrations automatically when it starts, or run `uv run alembic upgrade head` yourself.

## Project layout

```
app/                  the web app
  main.py             app setup: create_app(), middleware, error pages
  config.py           settings from environment variables
  models.py           database tables (BoardType, Board, Checkout)
  services.py         business rules: check out, return, retire, admin edits
  auth.py, csrf.py    sign-in checks, admin checks, form protection
  routes/             pages and buttons: auth.py, boards.py, admin.py
  templates/          HTML pages (Jinja)
  static/style.css    styling (UC Berkeley colors)
migrations/           database schema history (Alembic)
tests/                pytest tests
deploy/               Docker entrypoint, Caddy example, backup/restore scripts
docs/                 requirements, OAuth setup, deployment guide
Dockerfile, docker-compose.yml, .env.example
```

## Configuration

All settings come from environment variables. `.env.example` documents each one. In Docker,
they're read from `.env`.

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Signs session cookies. Required in production. Generate with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | OAuth client ([setup](docs/google-oauth.md)). Required unless `DEV_LOGIN=1` |
| `BASE_URL` | Public URL, no trailing slash. The OAuth redirect URI is `BASE_URL/auth/callback`. Can include a path prefix |
| `ADMIN_EMAILS` | Comma-separated admin emails |
| `DATABASE_PATH` | SQLite file. Docker sets `/data/tracker.db` on a volume |
| `DEV_LOGIN` | `1` replaces Google sign-in with an email form. The app refuses to start if this is set with `ENV=production` |
| `ENV` | `production` or `development` |

Only verified Google accounts with an exact `@berkeley.edu` address and `hd=berkeley.edu` can sign
in. The server checks this from the ID token. The `hd` hint on the login URL only pre-filters
Google's account picker.

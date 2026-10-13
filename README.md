# bTrack

A small web app for tracking who has which lab asset — carrier boards, instruments, cables,
whatever you decide to track — plus a timeline of who is using which FPGAs, where, and when.
People sign in with their @berkeley.edu Google account; access and admin rights come from two
Google Groups.

- **Dashboard:** where you land after signing in — the assets you currently hold, and your past checkouts
- **Asset overview:** every active asset with its status, holder, and checkout time, filterable by type
- **Check out / return:** one active checkout per asset (enforced by the database). Only the holder or an admin can return one.
- A **history page** for each asset
- **FPGA reservations:** a timeline of local FPGA use — project, how many, point of contact,
  special requests, dates, and which server. One row per FPGA model, with overlapping bookings
  stacked only as needed. Booking more than a server holds is allowed but flagged.
- **Admin:** one page for both systems — add/edit/retire assets, manage asset types, manage FPGA
  types, servers and per-server counts, force-return, CSV export, and CSV **import** of assets
  (same columns as the export, so you can download, edit in a spreadsheet, and upload back).
  (Assets and FPGA reservations are separate for users; only the admin page combines them.)
- **Light and dark themes,** following the system setting until you pick one

Stack: Python, FastAPI, Jinja templates, SQLite (SQLAlchemy + Alembic), managed with
[uv](https://docs.astral.sh/uv/). No JS framework — just a few lines for the theme toggle and
the timeline hover cards.

## Docs

- [Requirements](docs/spec.md): what the app must do
- [Google OAuth setup](docs/google-oauth.md): creating the sign-in client, testing real sign-in locally
- [Google Groups setup](docs/google-groups.md): the access list and admin rights, no Workspace admin needed
- [Deploying](docs/deployment.md): Linux + Docker + Caddy, updates, backup and restore

## Local development

Requires uv (`brew install uv`).

```sh
cd board_tracker                          # run everything from the project folder
uv sync                                   # install dependencies into .venv

# Run with the dev login form (no Google setup needed). The app creates or upgrades
# data/tracker.db on startup.
DEV_LOGIN=1 ENV=development \
  uv run uvicorn --factory app.main:create_app --reload
```

Open http://localhost:8000 and sign in as any @berkeley.edu address. Tick the **admin** box on the
dev login form to get the Admin pages. Dev login never calls the Google APIs, and the app refuses
to start with `DEV_LOGIN=1` and `ENV=production`.

A fresh database has no asset types and no FPGA servers: add them under **Admin** first.
The FPGA models the lab already has (U250, XB10, VCU118, U200, U280, V80, RHS Research Nitefury II)
are seeded for you, and admins can add more.

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
  models.py           database tables (AssetType, Asset, Checkout, FpgaType,
                      FpgaServer, FpgaPlacement, FpgaReservation)
  services.py         business rules: check out, return, retire, admin edits, FPGA timeline
  auth.py, groups.py  sign-in checks, Google Group membership
  csrf.py             form protection
  routes/             pages and buttons: auth.py, assets.py, fpga.py, admin.py
  templates/          HTML pages (Jinja)
  static/             style.css (UC Berkeley colors, light + dark), app.js
migrations/           database schema history (Alembic)
tests/                pytest tests
deploy/               Docker entrypoint, Caddy example, backup/restore scripts
docs/                 requirements, OAuth setup, Groups setup, deployment guide
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
| `GOOGLE_SERVICE_ACCOUNT_FILE` / `GOOGLE_SERVICE_ACCOUNT_JSON` | Service account that checks group membership ([setup](docs/google-groups.md)). Set one; inline JSON wins |
| `GOOGLE_USERS_GROUP` | Membership in this group is required to sign in |
| `GOOGLE_ADMINS_GROUP` | Membership in this group grants admin rights |
| `DATABASE_PATH` | SQLite file. Docker sets `/data/tracker.db` on a volume |
| `DEV_LOGIN` | `1` replaces Google sign-in with an email form. The app refuses to start if this is set with `ENV=production` |
| `ENV` | `production` or `development` |

Signing in requires all of: a verified Google account, an exact `@berkeley.edu` address with
`hd=berkeley.edu` in the ID token, and membership of `GOOGLE_USERS_GROUP`. Group membership is
checked once at sign-in and cached in the signed session cookie. If the Cloud Identity API can't
be reached, sign-in fails rather than falling back to granting access.

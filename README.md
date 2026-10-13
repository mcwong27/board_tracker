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

Stack: Python, FastAPI, Jinja templates, managed with [uv](https://docs.astral.sh/uv/).
Runs as a Python Worker on Cloudflare with its data in D1 (managed SQLite); the same code
runs locally under uvicorn against a SQLite file. No ORM — plain SQL, since D1 is SQLite.
No JS framework either, just a few lines for the theme toggle and the timeline hover cards.

## Docs

- [Requirements](docs/spec.md): what the app must do
- [Google OAuth setup](docs/google-oauth.md): creating the sign-in client, testing real sign-in locally
- [Google Groups setup](docs/google-groups.md): the access list and admin rights, no Workspace admin needed
- [Deploying](docs/deployment.md): Cloudflare Workers + D1, hostnames and custom domains, secrets, migrations, backups

## Local development

Requires uv (`brew install uv`).

```sh
cd board_tracker                          # run everything from the project folder
uv sync                                   # install dependencies into .venv

# Fast loop: plain uvicorn against a SQLite file, with the dev login form
# (no Google setup needed). The database is created on first run.
DEV_LOGIN=1 ENV=development \
  uv run uvicorn --factory app.main:create_app --reload --app-dir src
```

To run on the real Workers runtime instead, with a local D1 database:

```sh
npx wrangler d1 execute btrack --local --file=migrations/0001_initial.sql   # once
uv run pywrangler dev
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

**Schema changes:** add `migrations/0002_whatever.sql` and apply it with
`npx wrangler d1 migrations apply btrack` (add `--remote` for the deployed database). The
same files build the SQLite database the tests run against, so there is one source of truth.

## Project layout

Only `src/` is bundled into the Worker, so all Python and all templates live there.

```
src/
  entry.py            Worker entry point (builds the app from the bindings)
  app/
    main.py           app setup: create_app(), middleware, error pages
    config.py         settings from Worker bindings or environment variables
    db.py             Database interface: D1 in production, SQLite for tests/dev
    models.py         row mappers between SQL text and Python values
    services.py       business rules and SQL: checkout, return, admin, FPGA timeline
    auth.py, groups.py  sign-in checks, Google Group membership
    csrf.py           form protection
    routes/           pages and buttons: auth.py, assets.py, fpga.py, admin.py
    templates/        HTML pages (Jinja)
public/static/        style.css (UC Berkeley colors, light + dark), app.js
migrations/           D1 migrations; also the schema the tests build from
tests/                pytest tests (run against SQLite, no Workers runtime needed)
docs/                 requirements, OAuth setup, Groups setup, deployment guide
wrangler.jsonc, .env.example
```

## Configuration

On Workers, settings come from `wrangler.jsonc` `vars` and from secrets set with
`wrangler secret put`. Running locally they come from environment variables; `.env.example`
documents each one, and `.dev.vars` supplies them to `pywrangler dev`.

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Signs session cookies. Required in production. Generate with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | OAuth client ([setup](docs/google-oauth.md)). Required unless `DEV_LOGIN=1` |
| `BASE_URL` | Public URL, no trailing slash. The OAuth redirect URI is `BASE_URL/auth/callback`. Can include a path prefix |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Service account that checks group membership ([setup](docs/google-groups.md)). On Workers this must be inline JSON — there is no filesystem. `GOOGLE_SERVICE_ACCOUNT_FILE` also works locally |
| `GOOGLE_USERS_GROUP` | Membership in this group is required to sign in |
| `GOOGLE_ADMINS_GROUP` | Membership in this group grants admin rights |
| `DATABASE_PATH` | Local SQLite file for the uvicorn dev loop. Empty on Workers, where the D1 binding is used instead |
| `DEV_LOGIN` | `1` replaces Google sign-in with an email form. The app refuses to start if this is set with `ENV=production` |
| `ENV` | `production` or `development` |

Signing in requires all of: a verified Google account, an exact `@berkeley.edu` address with
`hd=berkeley.edu` in the ID token, and membership of `GOOGLE_USERS_GROUP`. Group membership is
checked once at sign-in and cached in the signed session cookie. If the Cloud Identity API can't
be reached, sign-in fails rather than falling back to granting access.

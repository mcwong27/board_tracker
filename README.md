# Lab Board Checkout Tracker

A small web app for tracking who has which lab board (Sophia Lake and Bora Lake carrier boards,
FPGAs, and so on). People sign in with their @berkeley.edu Google account to check boards out and
back in. Admins manage the inventory and can export everything as CSV.

- **Dashboard:** every active board with its status, holder, and checkout time, filterable by type
- **Check out / return:** one active checkout per board (enforced by the database). Only the holder or an admin can return a board.
- **My boards** and a **history page** for each board
- **Admin:** add, edit, retire, and restore boards, add board types, force-return, CSV export

Stack: FastAPI, Jinja templates, SQLite (SQLAlchemy + Alembic), managed with [uv](https://docs.astral.sh/uv/).

---

## Local development

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) (`brew install uv`).

```sh
uv sync                                   # install dependencies into .venv
uv run alembic upgrade head               # create/migrate data/tracker.db

# Run with the dev login form (no Google setup needed):
DEV_LOGIN=1 ENV=development ADMIN_EMAILS=you@berkeley.edu \
  uv run uvicorn --factory app.main:create_app --reload
```

Open http://localhost:8000 and sign in as any @berkeley.edu address. Sign in as the address in
`ADMIN_EMAILS` to see the Admin pages.

To test real Google sign-in locally, put your OAuth credentials in `.env` with
`ENV=development`, `DEV_LOGIN=0`, `BASE_URL=http://localhost:8000`, then run
`uv run --env-file .env uvicorn --factory app.main:create_app --reload`.

Tests and lint:

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

### Schema changes

Edit `app/models.py`, then generate and review a migration:

```sh
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```

The Docker container runs `alembic upgrade head` automatically on start.

---

## Configuration

All settings come from environment variables. `.env.example` documents each one. In Docker,
they're read from `.env`.

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Signs session cookies. Required in production. Generate with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | OAuth client (see below). Required unless `DEV_LOGIN=1` |
| `BASE_URL` | Public URL, no trailing slash. The OAuth redirect URI is `BASE_URL/auth/callback`. Can include a path prefix |
| `ADMIN_EMAILS` | Comma-separated admin emails |
| `DATABASE_PATH` | SQLite file. Docker sets `/data/tracker.db` on a volume |
| `DEV_LOGIN` | `1` replaces Google sign-in with an email form. The app refuses to start if this is set with `ENV=production` |
| `ENV` | `production` or `development` |

Only verified Google accounts with an exact `@berkeley.edu` address and `hd=berkeley.edu` can sign
in. The server checks this from the ID token. The `hd` hint on the login URL only pre-filters
Google's account picker.

---

## Google OAuth client setup

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a project (or
   pick an existing one), for example "Lab Board Tracker".
2. Open **APIs & Services → OAuth consent screen** (shown as **Google Auth Platform** in newer
   consoles) and click **Get started**.
   - **App name:** Lab Board Tracker. **Support email:** yours.
   - **Audience:** choose **Internal** if the project belongs to the berkeley.edu organization.
     Otherwise choose **External**. That's fine because the app itself rejects non-Berkeley
     accounts.
   - **Contact email:** yours. Agree to the policy and create the screen.
3. For an **External** app: under **Audience**, click **Publish app** to move it from Testing to
   In production. The app only requests `openid email profile`, so Google doesn't need to verify
   it. While it's still in Testing, only listed test users can sign in.
4. Open **Clients** (or **Credentials → Create credentials → OAuth client ID**):
   - **Application type:** Web application
   - **Authorized JavaScript origins:** the origin of your `BASE_URL`, e.g.
     `https://boards.example.berkeley.edu`
   - **Authorized redirect URIs:** `BASE_URL` + `/auth/callback`, e.g.
     `https://boards.example.berkeley.edu/auth/callback`. Also add
     `http://localhost:8000/auth/callback` if you want to test real sign-in locally. If `BASE_URL`
     has a path prefix, the redirect URI includes it: `https://host/boards/auth/callback`.
5. Click **Create** and copy the **Client ID** and **Client secret** into `.env` as
   `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

If sign-in fails with `redirect_uri_mismatch`, the redirect URI in the console must match
`BASE_URL/auth/callback` exactly, including scheme, host, path, and no trailing slash.

---

## Deploying (any Linux box with Docker + Caddy)

You need a Linux server with a public IP, a DNS name pointing at it (an A/AAAA record), and
ports 80 and 443 open. Caddy gets the HTTPS certificate automatically.

1. **Install Docker** (with the compose plugin):
   ```sh
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker $USER   # log out and back in afterwards
   ```
2. **Install Caddy:** follow https://caddyserver.com/docs/install. On Debian/Ubuntu, that's the
   `apt` repository instructions, which install Caddy as a systemd service.
3. **Get the code and configure it:**
   ```sh
   git clone <this repo> board_tracker && cd board_tracker
   cp .env.example .env
   chmod 600 .env
   $EDITOR .env    # SECRET_KEY, GOOGLE_CLIENT_ID/SECRET, BASE_URL=https://your.host, ADMIN_EMAILS
   ```
   Keep `ENV=production` and `DEV_LOGIN=0`.
4. **Start the app:**
   ```sh
   docker compose up -d --build
   docker compose ps            # should show "healthy" after ~30s
   curl http://127.0.0.1:8000/healthz
   ```
   The app listens only on `127.0.0.1:8000`. The database lives in the `tracker-data` Docker
   volume, so it survives rebuilds and `docker compose down` (but not `down -v`).
5. **Point Caddy at it.** Copy `Caddyfile.example` to `/etc/caddy/Caddyfile`, replace the
   hostname, then:
   ```sh
   sudo systemctl reload caddy
   ```
   Visit `https://your.host` and sign in. Caddy sends `X-Forwarded-*` headers, which the app
   honors.

**Updating:** `git pull && docker compose up -d --build`. Migrations run on start. Take a
backup first (below).

**Logs:** `docker compose logs -f app`.

---

## Backup and restore

The database is a single SQLite file inside the `tracker-data` volume.

**Back up** (safe while the app is running; uses SQLite's online backup):

```sh
scripts/backup.sh                     # writes backups/tracker-YYYYmmdd-HHMMSS.db
scripts/backup.sh /path/to/file.db    # or choose the destination
```

Nightly backups via cron (`crontab -e`), keeping 30 days:

```cron
15 3 * * * cd /home/you/board_tracker && scripts/backup.sh >/dev/null && find backups -name 'tracker-*.db' -mtime +30 -delete
```

Copy `backups/` somewhere off the machine too, with `rsync`, `rclone`, or similar.

**Restore** (stops the app, swaps in the backup with the right file ownership, starts the app):

```sh
scripts/restore.sh backups/tracker-20261009-031500.db
```

You can open any backup file directly with `sqlite3 backups/<file>.db` to inspect it. The
admin CSV exports are also a handy human-readable snapshot.

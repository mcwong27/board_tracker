# Lab Board Checkout Tracker

## Goal
Web app for tracking who has which lab boards (Sophia Lake and Bora Lake carrier boards, FPGAs, etc.).
People sign in with Berkeley Google accounts and check boards out and back in; admins manage inventory.

## Auth
- Google OAuth (OpenID Connect) via Authlib; signed session cookies.
- Only verified @berkeley.edu accounts. Enforce server-side (email_verified + hd claim / email domain);
  the hd parameter on the login URL is only a UI hint.
- Admins: comma-separated ADMIN_EMAILS env var.
- DEV_LOGIN=1: simple login form accepting any @berkeley.edu email, no OAuth, for local testing.
  Refuse to start if DEV_LOGIN is set and ENV=production.

## Data
- Board: id, name, type (shown in order: Bora Lake, Sophia Lake, Other; admins can add types), serial,
  chip mounted, location, notes, retired flag
- Checkout: board, user email, user name, checked_out_at, returned_at, returned_by, notes
  (no due dates: the app tracks who has what and since when)

## Features
- Dashboard: all active boards with status, holder, since when; filter by type
- Check out an available board with an optional note.
  At most one active checkout per board, enforced in the DB, not just the UI.
- Return: holder or admin only
- "My boards" page; per-board history page
- Admin: add/edit/retire boards, force-return, CSV export of boards and checkout history

## Stack
- Python, FastAPI, Jinja server-rendered templates, minimal CSS, no JS framework
- SQLite via SQLAlchemy, Alembic migrations, uv for dependencies

## Deployment (host TBD, keep it host-agnostic)
- All config via env vars; .env.example documents each one
  (SECRET_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, BASE_URL, ADMIN_EMAILS, DATABASE_PATH, DEV_LOGIN, ENV)
- Dockerfile + docker-compose.yml; SQLite file on a mounted volume so data survives rebuilds
- Works behind a reverse proxy at BASE_URL (honor X-Forwarded headers)
- README: local dev; step-by-step Google OAuth client setup incl. redirect URIs;
  deploying on any Linux box with Docker + Caddy for HTTPS; backing up and restoring the DB

## Quality
- pytest tests: no double checkout, only holder/admin can return, non-berkeley emails rejected,
  admin routes protected
- CLAUDE.md with project overview and the commands to run, test, and lint

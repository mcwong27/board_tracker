# bTrack

## Goal
Web app for tracking who has which lab asset. Not tied to any particular kind of hardware:
admins define the asset types (carrier boards, instruments, cables, whatever the lab tracks).
A second tab tracks FPGA use over time: who needs how many of which model, in which server, when.
People sign in with Berkeley Google accounts; admins manage inventory.

## Auth
- Google OAuth (OpenID Connect) via Authlib; signed session cookies.
- Only verified @berkeley.edu accounts. Enforce server-side (email_verified + hd claim / email domain);
  the hd parameter on the login URL is only a UI hint.
- Access list and admin rights come from two Google Groups, checked through the Cloud Identity
  Groups API with a service account that is an Owner/Manager of each group (so no Workspace
  super-admin or domain-wide delegation is needed):
  - GOOGLE_USERS_GROUP: membership required to sign in at all.
  - GOOGLE_ADMINS_GROUP: membership grants admin rights.
  Checked once at sign-in, cached in the signed session. No email-allowlist fallback: if the API
  can't be reached, sign-in fails closed. Direct membership only — nested groups aren't followed.
- DEV_LOGIN=1: simple login form accepting any @berkeley.edu email with an "admin" checkbox,
  no OAuth and no group lookups, for local testing.
  Refuse to start if DEV_LOGIN is set and ENV=production.

## Data
- AssetType: id, name. Fully admin-managed (add, rename, delete); a fresh database has none and a
  type still in use can't be deleted.
- Asset: id, name, type, serial, chip mounted, location, notes, retired flag
- Checkout: asset, user email, user name, checked_out_at, returned_at, returned_by, notes
  (no due dates: the app tracks who has what and since when)
- FpgaType: id, name. Seeded with U250, XB10, VCU118, U200, U280, V80, RHS Research Nitefury II;
  admins add more.
- FpgaServer: id, name, notes — a machine FPGAs are installed in.
- FpgaPlacement: fpga_type, server, quantity — how many of a model live in a given server.
  Unique per (type, server).
- FpgaReservation: fpga_type, server, project, quantity, contact, special_requests,
  start_date, end_date, created_by_email. Every new reservation must name a server; the column
  stays nullable only for rows that predate servers existing. Not tied to a specific named Asset:
  a shared log/calendar, not an inventory check-out.

## Features
- Dashboard (`/`, the page you land on after signing in): the assets you personally hold, plus
  your past checkouts
- Check out an available asset with an optional note.
  At most one active checkout per asset, enforced in the DB, not just the UI.
- Return: holder or admin only
- Asset overview (`/assets`): all active assets with status, holder, since when; filter by type.
  Visible to everyone.
- Per-asset history page
- Admin: a single page covering both systems — add/edit/retire assets, manage asset types,
  force-return, CSV export of assets and checkout history, and manage FPGA types, servers, and
  the how-many-where grid. Assets and FPGA reservations stay separate for users but share one
  admin page; each section's actions sit under its own heading.
- Asset CSV import: same columns as the assets export (name and type required; serial,
  chip_mounted, location, notes, retired optional; derived columns ignored), so an exported file
  can be edited and uploaded back. Rows match existing assets by name: update or create, never
  delete. Missing asset types are created. All-or-nothing — any bad row rejects the whole file
  with per-row messages.
- FPGA reservations tab: any signed-in user logs local FPGA use (project, number of FPGAs,
  username/point of contact, special requests, start/end dates, and which server — all required).
  Timeline view, one collapsed line per FPGA model:
  - Each physical board gets its own row and its own hue. Boards come from the admin counts:
    4 U250s in a server means rows "<server> #1".."#4". Hues are spread evenly around the wheel.
  - Collapsed, a model's boards are muxed into that single line as thin stacked bands, so a type
    stays one line however many boards it has. Clicking the model expands it (plain
    `<details>`, no JS) into a full row per board.
  - Bookings are assigned to specific boards, earliest start first; a booking for 2 takes two
    boards for its whole stretch. All-or-nothing: one that doesn't fit goes to an "Over capacity"
    row rather than being split across a board it can't have.
  - Hovering a bar shows the full details. Booking more of a model than a server holds is allowed
    but flagged in red with a warning listing the over-subscribed stretches — people sort sharing
    out between themselves.
  - A plain table lists every reservation. Only the creator or an admin may edit/delete.
- Light and dark themes: follows the system setting, with a toggle that overrides it and persists.

## Stack
- A TypeScript Cloudflare Worker: Hono for routing, server-rendered HTML from tagged
  template literals that escape by default, minimal CSS, no client-side framework
  (a few lines of vanilla JS for the theme toggle and timeline hover cards)
- Data in D1 (Cloudflare's managed SQLite), reached with plain SQL — no ORM
- Sessions, the service-account JWT and the OAuth flow all use the platform's own
  `fetch` and WebCrypto, so the Worker carries one runtime dependency

## Deployment (Cloudflare Workers)
- Public config in wrangler.jsonc `vars` (ENV, BASE_URL, GOOGLE_CLIENT_ID,
  GOOGLE_USERS_GROUP, GOOGLE_ADMINS_GROUP, DEV_LOGIN); secrets via `wrangler secret put`
  (SECRET_KEY, GOOGLE_CLIENT_SECRET, GOOGLE_SERVICE_ACCOUNT_JSON). The same settings are
  read from .dev.vars when running locally; .dev.vars.example documents each one.
- Schema changes are numbered .sql files in migrations/, applied with
  `wrangler d1 migrations apply`. The same files build the test database.
- Deployed at a bare hostname: a BASE_URL path prefix is not supported, and all links
  in the app are absolute paths.
- Backups: `wrangler d1 export`, plus D1 time-travel within the retention window.
- README: local dev; Google OAuth client setup incl. redirect URIs; Google Groups setup;
  docs/deployment.md covers deploying, secrets, migrations and backups.

## Quality
- Vitest, running inside the Workers runtime against a real local D1: no double
  checkout, only holder/admin can return, non-berkeley emails rejected, non-members
  refused, group API failure fails closed, CSRF enforced, admin routes protected,
  over-subscription detection, CSV round-tripping, and HTML escaping of user text
- CLAUDE.md with project overview and the commands to run, test, and lint

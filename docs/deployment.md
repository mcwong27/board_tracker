# Deploying

These steps work on any Linux box with Docker and Caddy. You need a Linux server with a public
IP, a DNS name pointing at it (an A/AAAA record), and ports 80 and 443 open. Caddy gets the
HTTPS certificate automatically.

The deployment files are `Dockerfile` and `docker-compose.yml` at the top level, plus `deploy/`:

| File | Purpose |
| --- | --- |
| `deploy/docker-entrypoint.sh` | Container start: checks config, then runs uvicorn |
| `deploy/Caddyfile.example` | HTTPS reverse proxy config for Caddy |
| `deploy/backup.sh` | Copies the live database out of the container |
| `deploy/restore.sh` | Replaces the live database with a backup |

## First deploy

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
   $EDITOR .env    # SECRET_KEY, GOOGLE_CLIENT_ID/SECRET, BASE_URL=https://your.host,
                   # GOOGLE_SERVICE_ACCOUNT_FILE or _JSON, GOOGLE_USERS_GROUP, GOOGLE_ADMINS_GROUP
   ```
   Keep `ENV=production` and `DEV_LOGIN=0`. For the sign-in client see
   [Google OAuth setup](google-oauth.md); for the access list and admin rights see
   [Google Groups setup](google-groups.md). If you point `GOOGLE_SERVICE_ACCOUNT_FILE` at a key
   file, mount it into the container and `chmod 600` it; otherwise paste the key into
   `GOOGLE_SERVICE_ACCOUNT_JSON` in `.env`.
4. **Start the app:**
   ```sh
   docker compose up -d --build
   docker compose ps            # should show "healthy" after ~30s
   curl http://127.0.0.1:8000/healthz
   ```
   The app listens only on `127.0.0.1:8000`. The database lives in the `tracker-data` Docker
   volume, so it survives rebuilds and `docker compose down` (but not `down -v`).
5. **Point Caddy at it.** Copy `deploy/Caddyfile.example` to `/etc/caddy/Caddyfile`, replace the
   hostname, then:
   ```sh
   sudo systemctl reload caddy
   ```
   Visit `https://your.host` and sign in. Caddy sends `X-Forwarded-*` headers, which the app
   honors.

**Updating:** `git pull && docker compose up -d --build`. Migrations run on start. Take a
backup first (below).

**Logs:** `docker compose logs -f app`.

## Backup and restore

The database is a single SQLite file inside the `tracker-data` volume.

**Back up** (safe while the app is running; uses SQLite's online backup):

```sh
deploy/backup.sh                     # writes backups/tracker-YYYYmmdd-HHMMSS.db
deploy/backup.sh /path/to/file.db    # or choose the destination
```

Nightly backups via cron (`crontab -e`), keeping 30 days:

```cron
15 3 * * * cd /home/you/board_tracker && deploy/backup.sh >/dev/null && find backups -name 'tracker-*.db' -mtime +30 -delete
```

Copy `backups/` somewhere off the machine too, with `rsync`, `rclone`, or similar.

**Restore** (stops the app, swaps in the backup with the right file ownership, starts the app):

```sh
deploy/restore.sh backups/tracker-20261009-031500.db
```

You can open any backup file directly with `sqlite3 backups/<file>.db` to inspect it. The
admin CSV exports are also a handy human-readable snapshot.

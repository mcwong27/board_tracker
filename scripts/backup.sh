#!/bin/sh
# Online backup of the SQLite DB from the running container (safe while the app is serving).
# Usage: scripts/backup.sh [output-file]    (default: backups/tracker-YYYYmmdd-HHMMSS.db)
set -eu
cd "$(dirname "$0")/.."
out="${1:-backups/tracker-$(date +%Y%m%d-%H%M%S).db}"
mkdir -p "$(dirname "$out")"
# Back up inside the container, switch the copy out of WAL mode so it's one self-contained
# file, and check its integrity before copying it out.
docker compose exec -T app sh -c '
  sqlite3 /data/tracker.db ".backup /data/backup-tmp.db" &&
  sqlite3 /data/backup-tmp.db "PRAGMA journal_mode=DELETE;" >/dev/null &&
  test "$(sqlite3 /data/backup-tmp.db "PRAGMA integrity_check;")" = ok'
docker compose cp app:/data/backup-tmp.db "$out"
docker compose exec -T app rm -f /data/backup-tmp.db
echo "Backed up to $out"

#!/bin/sh
# Replace the live DB with a backup file. Stops the app while restoring.
# Usage: deploy/restore.sh path/to/backup.db
set -eu
cd "$(dirname "$0")/.."
backup="${1:?usage: deploy/restore.sh path/to/backup.db}"
[ -f "$backup" ] || { echo "No such file: $backup" >&2; exit 1; }
backup="$(cd "$(dirname "$backup")" && pwd)/$(basename "$backup")"

docker compose stop app
# Run as root in a one-off container so the restored file is owned by the app user,
# and drop the old WAL/SHM files so SQLite doesn't replay them onto the restored DB.
docker compose run --rm --no-deps --user root --entrypoint sh \
  -v "$backup:/restore.db:ro" app -c \
  'rm -f /data/tracker.db-wal /data/tracker.db-shm &&
   cp /restore.db /data/tracker.db && chown app:app /data/tracker.db'
docker compose start app
echo "Restored from $backup"

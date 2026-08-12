#!/usr/bin/env bash
# Dumps the production Postgres database to a timestamped, gzip-compressed file.
#
# This script only protects data once it's actually running on a schedule on the real
# server -- it does nothing by existing in the repo. See GOING_LIVE.md's "Backups"
# section for how to wire this into cron/systemd-timer, and for the restore procedure.
#
# Usage (run from the repo root, alongside docker-compose.yml):
#   POSTGRES_PASSWORD=... ./backend/scripts/backup_db.sh [output-directory]
#
# Assumes the `postgres` service from docker-compose.yml is running. Reads
# POSTGRES_PASSWORD from the environment (export it, or run via `env $(cat .env | xargs)`
# so it picks up the same value docker-compose itself uses) rather than hardcoding it here.

set -euo pipefail

BACKUP_DIR="${1:-./backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="${BACKUP_DIR}/kelviontech_${TIMESTAMP}.sql.gz"

if [ -z "${POSTGRES_PASSWORD:-}" ]; then
  echo "POSTGRES_PASSWORD is not set -- export it (same value as in .env) before running this script." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

echo "Backing up kelviontech database to ${OUT_FILE} ..."
docker compose exec -T postgres env PGPASSWORD="$POSTGRES_PASSWORD" \
  pg_dump -U postgres -d kelviontech --format=plain --no-owner --no-privileges \
  | gzip > "$OUT_FILE"

echo "Done: $(du -h "$OUT_FILE" | cut -f1) written."

# Keep the last 30 days of daily backups by default -- adjust to match your actual
# retention needs (GST record-retention requirements apply to invoices, not to how long
# you keep raw DB snapshots, so this is purely an operational/storage-cost choice).
find "$BACKUP_DIR" -name "kelviontech_*.sql.gz" -mtime +30 -delete

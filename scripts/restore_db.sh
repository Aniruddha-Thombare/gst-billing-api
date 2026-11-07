#!/usr/bin/env bash
# Restore a dump into a SCRATCH database (never straight over your real one) to prove the backup works.
# Usage:  bash scripts/restore_db.sh backups/gst_XXXX.dump
set -euo pipefail
DUMP="${1:?usage: restore_db.sh <dump file>}"
# tr -d '\r' : a Windows (CRLF) .env would otherwise leave a hidden \r on every value
set -a; source <(tr -d '\r' < .env); set +a
SCRATCH="restore_check"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS ${SCRATCH};"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE ${SCRATCH};"
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$SCRATCH" --no-owner < "$DUMP"
echo "--- row counts in the restored copy ---"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$SCRATCH" -c \
  "SELECT 'tenants' AS t, count(*) FROM tenants UNION ALL SELECT 'invoices', count(*) FROM invoices UNION ALL SELECT 'payments', count(*) FROM payments;"
echo "Done. Remove the scratch copy with:"
echo "  docker compose exec postgres psql -U $POSTGRES_USER -d postgres -c 'DROP DATABASE ${SCRATCH};'"

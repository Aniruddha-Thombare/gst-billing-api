#!/bin/sh
# Runs inside the "backup" container. Dumps the database every 24 hours.
# Format -Fc = compressed custom format, restorable with pg_restore (also selectively).
set -eu
mkdir -p /backups
while true; do
  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  TARGET="/backups/gst_${STAMP}.dump"
  if pg_dump -Fc -f "${TARGET}.partial"; then
    mv "${TARGET}.partial" "${TARGET}"       # a file without .partial is always complete
    echo "[backup] wrote ${TARGET}"
  else
    rm -f "${TARGET}.partial"
    echo "[backup] FAILED at ${STAMP}" >&2
  fi
  find /backups -name 'gst_*.dump' -mtime "+${BACKUP_KEEP_DAYS:-7}" -delete
  sleep 86400
done

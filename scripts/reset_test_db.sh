#!/usr/bin/env bash
# Recreates the throwaway test database from the migrations and (re)starts the
# test API on http://localhost:8001. Safe to run any time: it never touches gst_db.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose --profile test stop api-test >/dev/null 2>&1 || true

docker compose exec -T postgres sh -c \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS gst_test WITH (FORCE)" -c "CREATE DATABASE gst_test"'

docker compose --profile test run --rm migrate-test
docker compose --profile test up -d api-test

echo "Test API starting on http://localhost:8001 (give it ~10 seconds)."

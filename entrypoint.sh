#!/usr/bin/env bash
# entrypoint.sh – Docker container startup script for FormsADDA
#
# 1. Waits until the PostgreSQL service is accepting connections.
# 2. Starts the Gunicorn WSGI server.
#    wsgi.py calls initialize_system(), which runs db.create_all() and
#    seeds organizations on first boot.

set -e

echo "=== FormsADDA Docker Entrypoint ==="

# ── Wait for PostgreSQL ────────────────────────────────────────────────────────
if [ -n "$DATABASE_URL" ]; then
  echo "[1/2] Waiting for PostgreSQL to become ready..."

  # Extract host and port from DATABASE_URL
  # Expected format: postgresql://user:password@host:port/dbname
  DB_HOST=$(echo "$DATABASE_URL" | sed -E 's|.*@([^:/]+).*|\1|')
  DB_PORT=$(echo "$DATABASE_URL" | sed -E 's|.*:([0-9]+)/.*|\1|')
  DB_PORT="${DB_PORT:-5432}"

  MAX_RETRIES=30
  RETRY=0
  until pg_isready -h "$DB_HOST" -p "$DB_PORT" -q 2>/dev/null; do
    RETRY=$((RETRY + 1))
    if [ "$RETRY" -ge "$MAX_RETRIES" ]; then
      echo "ERROR: PostgreSQL did not become ready after $MAX_RETRIES attempts. Exiting."
      exit 1
    fi
    echo "  PostgreSQL is unavailable ($DB_HOST:$DB_PORT) – retrying in 2s... ($RETRY/$MAX_RETRIES)"
    sleep 2
  done
  echo "  PostgreSQL is ready."
else
  echo "[1/2] DATABASE_URL not set – using SQLite fallback."
fi

# ── Execute Custom Command (if passed) or Start Gunicorn ──────────────────────
if [ "$#" -gt 0 ]; then
  echo "[2/2] Running custom command: $@"
  exec "$@"
else
  echo "[2/2] Starting Gunicorn on 0.0.0.0:8000 ..."
  exec gunicorn wsgi:app \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-5}" \
    --threads "${GUNICORN_THREADS:-10}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --log-level "${GUNICORN_LOG_LEVEL:-info}" \
    --access-logfile - \
    --error-logfile -
fi


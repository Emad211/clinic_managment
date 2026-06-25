#!/bin/sh
# halqe/entrypoint.sh
# Idempotent container startup for the halqe Django backend.
#
# Sequence:
#   1) Wait for Postgres to be reachable (lightweight TCP poll — compose
#      healthcheck is the primary gate, but this gives us a safety net).
#   2) apply_schema  — DDL slices (superuser path, idempotent).
#   3) ensure_app_role — create/refresh the least-privilege LOGIN role.
#   4) exec gunicorn  — hand off to the WSGI server (no runserver).
#
# All env vars are injected by docker-compose; nothing is hard-coded here.
# Re-running this script is always safe (idempotent steps).

set -e

# ---------------------------------------------------------------------------
# 1) Wait for Postgres
# ---------------------------------------------------------------------------
PG_HOST="${PG_HOST:-postgres}"
PG_PORT="${PG_PORT:-5432}"

echo "entrypoint: waiting for Postgres at ${PG_HOST}:${PG_PORT} ..."
# Poll until the port accepts a connection (max 60s, 2s interval).
i=0
until python -c "
import socket, sys
try:
    s = socket.create_connection(('${PG_HOST}', int('${PG_PORT}')), timeout=2)
    s.close()
    sys.exit(0)
except OSError:
    sys.exit(1)
" 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
        echo "entrypoint: timed out waiting for Postgres after $((i * 2))s" >&2
        exit 1
    fi
    echo "entrypoint: Postgres not ready yet (attempt $i/30), retrying in 2s ..."
    sleep 2
done
echo "entrypoint: Postgres is reachable."

# ---------------------------------------------------------------------------
# 2) Apply schema slices (superuser — DDL + GRANTs)
# ---------------------------------------------------------------------------
echo "entrypoint: running apply_schema ..."
python manage.py apply_schema
echo "entrypoint: apply_schema done."

# ---------------------------------------------------------------------------
# 3) Ensure least-privilege app LOGIN role exists
# ---------------------------------------------------------------------------
echo "entrypoint: running ensure_app_role ..."
python manage.py ensure_app_role
echo "entrypoint: ensure_app_role done."

# ---------------------------------------------------------------------------
# 4) Start gunicorn
# ---------------------------------------------------------------------------
WORKERS="${GUNICORN_WORKERS:-3}"
echo "entrypoint: starting gunicorn with ${WORKERS} workers ..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${WORKERS}" \
    --timeout 120 \
    --worker-tmp-dir /tmp \
    --access-logfile - \
    --error-logfile -

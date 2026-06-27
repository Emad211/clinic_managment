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
# Access-log format: host, request LINE, status, bytes, response time
# (%(L)s, seconds) and the X-Request-ID echoed by RequestIdMiddleware.
# %({x-request-id}o)s reads the RESPONSE header (the 'o' variant), which the
# middleware always sets — even when the request arrived without one — so every
# access line carries the same rid as the Django structured logs
# (request_id=…), letting an operator join the two for a single request.
# PII-free: only the request LINE is logged — never Authorization/cookies or any
# request/response body.
GUNICORN_ACCESS_FMT='%(h)s "%(r)s" %(s)s %(b)s %(L)s rid=%({x-request-id}o)s'
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${WORKERS}" \
    --timeout 120 \
    --worker-tmp-dir /tmp \
    --access-logfile - \
    --access-logformat "${GUNICORN_ACCESS_FMT}" \
    --error-logfile -

#!/bin/sh
# halqe/entrypoint.sh — idempotent backend container startup.
set -e

PG_HOST="${PG_HOST:-postgres}"
PG_PORT="${PG_PORT:-5432}"

echo "entrypoint: waiting for Postgres at ${PG_HOST}:${PG_PORT} ..."
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

echo "entrypoint: running apply_schema ..."
python manage.py apply_schema

echo "entrypoint: running ensure_app_role ..."
python manage.py ensure_app_role

# The pilot tenant receives its own editable copy of the specialist-clinic
# flag/lab/drug catalogs.  get_or_create makes this safe on every restart and
# never overwrites manager edits. Set RECORD_CATALOG_TENANT_ID=0 to skip.
RECORD_CATALOG_TENANT_ID="${RECORD_CATALOG_TENANT_ID:-1}"
if [ "${RECORD_CATALOG_TENANT_ID}" != "0" ]; then
    echo "entrypoint: seeding patient-record catalogs for tenant ${RECORD_CATALOG_TENANT_ID} ..."
    python manage.py seed_record_catalogs --tenant-id "${RECORD_CATALOG_TENANT_ID}"
fi

WORKERS="${GUNICORN_WORKERS:-3}"
echo "entrypoint: starting gunicorn with ${WORKERS} workers ..."
# Use URL path rather than the full request-line: patient search values in query
# strings must never appear in access logs.
GUNICORN_ACCESS_FMT='%(h)s "%(m)s %(U)s %(H)s" %(s)s %(b)s %(L)s rid=%({x-request-id}o)s'
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${WORKERS}" \
    --timeout 120 \
    --worker-tmp-dir /tmp \
    --access-logfile - \
    --access-logformat "${GUNICORN_ACCESS_FMT}" \
    --error-logfile -

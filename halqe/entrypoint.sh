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
echo "entrypoint: Postgres is reachable."

echo "entrypoint: running apply_schema ..."
python manage.py apply_schema
echo "entrypoint: apply_schema done."

echo "entrypoint: running ensure_app_role ..."
python manage.py ensure_app_role
echo "entrypoint: ensure_app_role done."

# Incremental accounting rollout: do not take the existing clinical platform
# down merely because the new writer secret has not been provisioned yet.
# Once PG_ACCOUNTING_PASSWORD is present, bootstrap the isolated write role.
if [ -n "${PG_ACCOUNTING_PASSWORD:-}" ]; then
    echo "entrypoint: running ensure_accounting_role ..."
    python manage.py ensure_accounting_role
    echo "entrypoint: ensure_accounting_role done."
else
    echo "entrypoint: PG_ACCOUNTING_PASSWORD is unset; accounting write API remains disabled."
fi

WORKERS="${GUNICORN_WORKERS:-3}"
echo "entrypoint: starting gunicorn with ${WORKERS} workers ..."
# Privacy contract: use method + URL PATH + protocol instead of %(r)s. Gunicorn's
# request-line atom includes the query string, which can contain patient search
# values such as national_id or phone. %(U)s deliberately excludes query args.
GUNICORN_ACCESS_FMT='%(h)s "%(m)s %(U)s %(H)s" %(s)s %(b)s %(L)s rid=%({x-request-id}o)s'
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${WORKERS}" \
    --timeout 120 \
    --worker-tmp-dir /tmp \
    --access-logfile - \
    --access-logformat "${GUNICORN_ACCESS_FMT}" \
    --error-logfile -

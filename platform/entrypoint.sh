#!/usr/bin/env bash
# Container entrypoint. Enforces the RLS-correct DB-role split:
#   - migrations + global seeding run as the PRIVILEGED admin role (ADMIN_DATABASE_URL)
#   - the app process runs as the UNPRIVILEGED, NOBYPASSRLS role (DATABASE_URL)
# This is what makes tenant isolation actually hold in production
# (proven by manage.py verify_rls).
set -euo pipefail

ADMIN_URL="${ADMIN_DATABASE_URL:-$DATABASE_URL}"

echo "[entrypoint] waiting for database…"
python - <<'PY'
import os, time, psycopg
url = os.environ.get("ADMIN_DATABASE_URL") or os.environ["DATABASE_URL"]
for i in range(60):
    try:
        psycopg.connect(url).close(); print("  db ready"); break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("database not reachable")
PY

echo "[entrypoint] migrate (admin role)…"
DATABASE_URL="$ADMIN_URL" python manage.py migrate --noinput

if [ "${SEED_ON_START:-0}" = "1" ]; then
  echo "[entrypoint] seeding global ADA catalogs (admin role)…"
  DATABASE_URL="$ADMIN_URL" python manage.py seed_catalog || true
fi

echo "[entrypoint] starting gunicorn (app role, NOBYPASSRLS)…"
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-3}" \
  --timeout "${GUNICORN_TIMEOUT:-60}"

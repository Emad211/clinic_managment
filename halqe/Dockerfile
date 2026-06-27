# halqe/Dockerfile
# Build context: repo root (hesabdari_darmangah/)
# docker build -f halqe/Dockerfile -t halqe-backend .
#
# Two source trees are copied:
#   halqe/                  — the Django app
#   halqe/db/schema/        — SQL schema slices
#     (SCHEMA_SLICE_DIR points here; apply_schema reads them at startup)
#
# Dependencies install from PyPI by default (portable, no committed binaries).
#
# OFFLINE FALLBACK — restricted networks (e.g. an Iranian VPS that cannot reach
# PyPI directly; this was the validation host's situation too). On a connected
# machine, pre-download wheels for the TARGET platform, then switch the deps RUN:
#   pip download -r halqe/requirements.txt gunicorn==23.0.0 --dest halqe/wheels \
#       --platform manylinux2014_x86_64 --python-version 313 \
#       --implementation cp --only-binary=:all:
#   # then: COPY halqe/wheels/ /tmp/wheels/  +  pip install --no-index
#           --find-links=/tmp/wheels -r /tmp/requirements.txt gunicorn==23.0.0
# The wheels are platform/arch-specific build artifacts — NOT committed to git
# (see .dockerignore). The step-55 deploy runbook handles the target-arch build.
#
# No secrets are baked in. All credentials come from env vars at runtime.

# ---------------------------------------------------------------------------
# Stage 1: dependency installation (separate layer for cache efficiency)
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS deps

WORKDIR /app

# psycopg[binary] uses a pre-compiled manylinux wheel — no gcc/libpq-dev needed.
COPY halqe/requirements.txt /tmp/requirements.txt

# Install the app dependencies + gunicorn (production WSGI server) from PyPI.
# gunicorn is pinned here (deploy-only dep, not in the dev/test venv → not in
# requirements.txt); bump it deliberately alongside the offline wheel rebuild.
# For restricted networks, see the OFFLINE FALLBACK note in the header above.
RUN pip install --no-cache-dir -r /tmp/requirements.txt gunicorn==23.0.0

# ---------------------------------------------------------------------------
# Stage 2: runtime image
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# Non-root user for security hardening.
# --create-home creates /home/halqe so gunicorn's control server can bind
# its internal socket without a "Permission denied: '/home/halqe'" warning.
RUN groupadd --system halqe && useradd --system --gid halqe --create-home halqe

WORKDIR /app

# Copy installed packages from deps stage.
COPY --from=deps /usr/local/lib/python3.13 /usr/local/lib/python3.13
COPY --from=deps /usr/local/bin/gunicorn   /usr/local/bin/gunicorn

# Copy the Django application.
# .dockerignore excludes .venv, __pycache__, *.db, wheels/, etc.
COPY halqe/ /app/

# Copy SQL schema slices into the image.
# The path inside the image: /slices/schema_pg_slice*.sql
# SCHEMA_SLICE_DIR is set to /slices via ENV below.
COPY halqe/db/schema/ /slices/

# Tell apply_schema where to find the slices (overrides the source-tree default
# that points one level above halqe/ — not valid inside the container).
ENV SCHEMA_SLICE_DIR=/slices

# Django settings module.
ENV DJANGO_SETTINGS_MODULE=config.settings

# Unbuffered Python output so logs appear immediately in docker logs.
ENV PYTHONUNBUFFERED=1

# Entrypoint script.
COPY halqe/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Change ownership so the non-root user can read the app files.
RUN chown -R halqe:halqe /app /slices /entrypoint.sh

USER halqe

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

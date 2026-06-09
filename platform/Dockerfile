# Clinic platform — production image (docs/TECH_STACK.md).
# From inside Iran, Docker Hub + PyPI are often blocked — pass mirrors at build:
#   docker build \
#     --build-arg PY=docker.arvancloud.ir/python:3.13-slim \
#     --build-arg PIP_INDEX_URL=https://mirror-pypi.runflare.com/simple \
#     -t clinic-platform .
ARG PY=python:3.13-slim
FROM ${PY}

# Optional Iranian PyPI mirror (e.g. runflare / arvan). Empty => default PyPI.
ARG PIP_INDEX_URL=""

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_DEBUG=False

WORKDIR /app

# psycopg[binary] ships its own libpq, so no system build deps are needed.
COPY requirements.txt .
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --no-cache-dir -i "$PIP_INDEX_URL" -r requirements.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

COPY . .

# Collect static at build time (no DB needed). DEBUG=False above.
RUN DJANGO_SECRET_KEY=build-time python manage.py collectstatic --noinput

RUN chmod +x /app/entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]

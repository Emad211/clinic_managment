# halqe/web/Dockerfile — Next.js production image (step 79 / T1)
# Build context: halqe/web/   (docker-compose: build.context: ./web)
#   docker build -t halqe-web halqe/web/
#
# Multi-stage → a lean STANDALONE runtime (next.config.ts: output:"standalone").
# Self-hosted only: vazirmatn fonts are vendored in public/fonts (no font CDN),
# and the API is called via a RELATIVE /api/v1 path (same-origin behind nginx),
# so NOTHING (no NEXT_PUBLIC_API_BASE host) needs to be baked at build for the pilot.
#
# OFFLINE FALLBACK — restricted networks (an Iranian VPS / CI that cannot reach the
# npm registry; the same constraint as the backend's PyPI note in halqe/Dockerfile).
# On a CONNECTED machine, prime an offline cache then switch the deps stage:
#   npm ci --cache ./.npm-cache                                  # connected machine
#   # deps stage:  RUN npm ci --offline --prefer-offline --cache /app/.npm-cache
# Or build the whole image on a connected machine and `docker save | docker load`
# onto the VPS. The npm cache / node_modules are platform build artifacts — NOT
# committed (see .dockerignore); the deploy runbook §11 handles the target build.
#
# No secrets are baked in.

# ---------------------------------------------------------------------------
# Stage 1 — deps (reproducible install from the committed lockfile; cached layer)
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS deps
WORKDIR /app
# npm registry — parametrised for Iran's national uplink. Default is the OFFICIAL
# registry, so normal builds / CI are unchanged. Pass --build-arg
# NPM_REGISTRY=<iranian-mirror> ONLY on the restricted VPS (registry.npmjs.org
# times out there). npm v10 rewrites the resolved host of lockfile entries when
# the configured registry is a plain default-style registry — package-lock.json
# is NOT edited, so the install stays reproducible.
ARG NPM_REGISTRY=https://registry.npmjs.org
COPY package.json package-lock.json ./
RUN npm config set registry "${NPM_REGISTRY}" && npm ci

# ---------------------------------------------------------------------------
# Stage 2 — builder (next build → .next/standalone + .next/static)
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# Cap the node heap: `next build` on a small VPS (the 2 vCPU / 4 GB staging box)
# can OOM when node expands its default heap while postgres etc. share the RAM.
# 1536 MB is plenty for this app's build and harmless on bigger machines.
ENV NODE_OPTIONS=--max-old-space-size=1536
COPY --from=deps /app/node_modules ./node_modules
COPY . ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 3 — runner (minimal standalone server; non-root)
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Non-root user (mirrors halqe/Dockerfile's hardening).
RUN groupadd --system halqe && useradd --system --gid halqe --create-home halqe

# standalone does NOT bundle public/ or .next/static — copy them explicitly,
# else fonts (public/fonts/*.woff2) and JS/CSS (/_next/static) 404.
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

USER halqe

# Next standalone server.js honours PORT/HOSTNAME. HOSTNAME=0.0.0.0 so nginx
# (a sibling container) can reach it on the internal network; default localhost
# would only bind inside the container.
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
EXPOSE 3000

CMD ["node", "server.js"]

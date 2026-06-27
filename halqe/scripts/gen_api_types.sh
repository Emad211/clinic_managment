#!/usr/bin/env bash
#
# gen_api_types.sh — OPTIONAL TypeScript typegen from the OpenAPI contract.
#
# WHAT THIS DOES
#   Generates web/src/lib/api/schema.gen.ts from the committed contract snapshot
#   docs/openapi.json, using `openapi-typescript`.
#
# WHY IT IS OPTIONAL (offline-by-design)
#   `openapi-typescript` is NOT a dependency of web/package.json and is NOT
#   required for `npm ci`, `npm test`, `tsc`, or `next build` to work. The repo
#   is offline-first: the SOURCE OF TRUTH is the committed docs/openapi.json plus
#   the hand-written clients under web/src/lib/api/*. This script is a developer
#   convenience to (re)generate a fully-typed `schema.gen.ts` WHEN ONLINE.
#
#   Nothing in the app imports schema.gen.ts yet — it is an opt-in artifact a
#   developer may wire into the per-domain clients incrementally. Generating it
#   does not change runtime behaviour.
#
# PREREQUISITES
#   - Network access (npx will fetch openapi-typescript on first run), OR
#     openapi-typescript already installed locally.
#   - A regenerated docs/openapi.json (run `manage.py dump_openapi` first if the
#     API changed).
#
# USAGE
#   # 1. refresh the contract snapshot (requires the Django venv):
#   (cd halqe && .venv/Scripts/python.exe manage.py dump_openapi)
#   # 2. generate the TS types (requires network the first time):
#   bash scripts/gen_api_types.sh
#   # 3. typecheck:
#   (cd halqe/web && npx tsc --noEmit)
#
# This script REFUSES to run if openapi-typescript cannot be obtained without a
# forced install, so it can never silently break an offline checkout.

set -euo pipefail

# Resolve repo paths relative to this script (scripts/ lives under halqe/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HALQE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

CONTRACT="${HALQE_DIR}/docs/openapi.json"
OUT="${HALQE_DIR}/web/src/lib/api/schema.gen.ts"

if [[ ! -f "${CONTRACT}" ]]; then
  echo "ERROR: contract snapshot not found: ${CONTRACT}" >&2
  echo "Run:  (cd halqe && .venv/Scripts/python.exe manage.py dump_openapi)" >&2
  exit 1
fi

# Probe for openapi-typescript WITHOUT triggering a forced install.
# `npx --no-install` exits non-zero (in older npm) or prints a cancel notice if
# the package is not already available — either way we treat it as "absent".
if ! npx --no-install openapi-typescript --version >/dev/null 2>&1; then
  cat >&2 <<'MSG'
openapi-typescript is not installed locally and this script will not force a
network install (offline-by-design).

To generate types, do ONE of the following while online, then re-run this script:
  - npx openapi-typescript --version        # warm the npx cache, then re-run
  - npm i -D openapi-typescript --prefix web

Until then, the committed docs/openapi.json + the hand-written web/src/lib/api/*
clients remain the source of truth. Nothing is broken — generation is optional.
MSG
  exit 2
fi

echo "Generating ${OUT}"
echo "  from ${CONTRACT}"
npx --no-install openapi-typescript "${CONTRACT}" -o "${OUT}"
echo "Done. Now run:  (cd halqe/web && npx tsc --noEmit)"

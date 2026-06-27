#!/usr/bin/env bash
# scripts/restore_drill.sh — VERIFIED restore drill (the proof backups work).
#
# WHAT IT DOES (fully automated, idempotent, self-cleaning):
#   (a) Build a FRESH source DB (halqe_drill_src) by applying all schema slices
#       in numeric order, populating platform.schema_version (replicating what
#       apply_schema does), and seeding a couple of patient rows. This makes the
#       drill completely self-contained — it does not depend on any pre-existing DB.
#   (b) pg_dump -Fc the source DB into a temp file.
#   (c) Create a THROWAWAY verify DB (halqe_restore_drill) — drop first if it
#       lingers from a prior failed run, so the drill is idempotent.
#   (d) pg_restore the dump into the throwaway DB.
#   (e) VERIFY the restore against the schema-version anchor + key tables:
#         - platform.schema_version has >= MIN_SCHEMA_ROWS rows
#         - platform.tenants, accounting.patients, clinical.patient_links exist
#         - row counts are sane (>= expected minimums)
#   (f) Drop BOTH the throwaway AND the source DB (always — via EXIT trap).
#   (g) Exit non-zero if any check fails.
#
# RUNNING ON THIS DEV HOST (Windows + git-bash, no postgres-client on PATH)
#   Set PG_CONTAINER to the name of the Docker container that HAS pg_dump/psql:
#
#     PG_CONTAINER=halqe_pg_validate \
#     PGUSER=postgres PGPASSWORD=validate_only \
#     bash scripts/restore_drill.sh
#
#   When PG_CONTAINER is set ALL pg commands (pg_dump/pg_restore/psql/createdb/
#   dropdb) run via "docker exec -i $PG_CONTAINER bash -c '...'". The dump file
#   lives as a tmpfile INSIDE the container — it never needs to cross the host/
#   container boundary. PGHOST defaults to "localhost" inside the container.
#
#   When PG_CONTAINER is empty (default), bare pg tools on PATH are used — the
#   production/VPS path where postgres-client is installed natively.
#
# CONNECTION (no hardcoded credentials — from env; see _pg_env.sh):
#   PGHOST PGPORT PGUSER PGPASSWORD   — standard libpq vars, or
#   DATABASE_URL                       — parsed by _pg_env.sh, or
#   PG_HOST PG_PORT PG_USER PG_PASSWORD — project vars from settings/.env
#   Note: when PG_CONTAINER is set, the pg commands run INSIDE the container, so
#   PGHOST is interpreted inside it (use "localhost" — the default — not the host
#   machine's hostname).
#
# CONFIG (env):
#   PG_CONTAINER     docker container name for pg tools (default: empty = native)
#   SCHEMA_SLICE_DIR path to schema_pg_slice*.sql files (default: ./db/schema)
#   SOURCE_DB        fresh source DB to build       (default: halqe_drill_src)
#   DRILL_DB         throwaway verify DB name       (default: halqe_restore_drill)
#   MIN_TENANTS      min rows in tenants            (default: 1)
#   MIN_SCHEMA_ROWS  min rows in schema_version     (default: 1)
#
# USAGE
#   # On this dev host via container:
#   PG_CONTAINER=halqe_pg_validate PGUSER=postgres PGPASSWORD=validate_only \
#     bash scripts/restore_drill.sh
#
#   # On VPS / any host with postgres-client:
#   PG_DB=halqe_app bash scripts/restore_drill.sh
#
# EXIT CODES
#   0 — drill PASSED (dump is restorable and verified)
#   1 — verify checks failed
#   2 — safety guard triggered (bad DB name)
#   3 — schema slice directory not found
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Repo root = one level up from scripts/
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=_pg_env.sh
. "$SCRIPT_DIR/_pg_env.sh"

# ── Config ────────────────────────────────────────────────────────────────────
PG_CONTAINER="${PG_CONTAINER:-}"
SOURCE_DB="${SOURCE_DB:-halqe_drill_src}"
DRILL_DB="${DRILL_DB:-halqe_restore_drill}"
MIN_TENANTS="${MIN_TENANTS:-1}"
MIN_SCHEMA_ROWS="${MIN_SCHEMA_ROWS:-1}"

# Path to SQL slices — inside-container path if using container, else host path.
HOST_SLICE_DIR="${SCHEMA_SLICE_DIR:-$REPO_ROOT/db/schema}"
if [ -n "$PG_CONTAINER" ]; then
    CONTAINER_SLICE_DIR="/tmp/halqe_drill_slices_$$"
fi

# When pg commands run inside the container, PGHOST/PGPORT must be the address
# reachable FROM INSIDE the container (the container's own loopback).
# The host-side port (e.g. 55432) is irrelevant inside the container —
# Postgres listens on its own 5432.
# PG_CONTAINER_HOST/PG_CONTAINER_PORT let the caller override if Postgres runs
# in a different container (not on the same loopback); defaults cover the
# standard setup where the Postgres container IS halqe_pg_validate itself.
if [ -n "$PG_CONTAINER" ]; then
    _PG_HOST="${PG_CONTAINER_HOST:-localhost}"
    _PG_PORT="${PG_CONTAINER_PORT:-5432}"
else
    _PG_HOST="${PGHOST:-localhost}"
    _PG_PORT="${PGPORT:-5432}"
fi

# ── pg command wrappers ────────────────────────────────────────────────────────
# All pg commands go through these wrappers. When PG_CONTAINER is set they run
# via docker exec; otherwise they run the local binary directly.

_pg_exec() {
    # _pg_exec <command-string>  — runs inside container or locally
    if [ -n "$PG_CONTAINER" ]; then
        # MSYS_NO_PATHCONV=1 prevents git-bash from mangling /tmp paths.
        MSYS_NO_PATHCONV=1 docker exec -i \
            -e "PGHOST=$_PG_HOST" \
            -e "PGPORT=$_PG_PORT" \
            -e "PGUSER=${PGUSER:-postgres}" \
            -e "PGPASSWORD=${PGPASSWORD:-}" \
            "$PG_CONTAINER" bash -c "$1"
    else
        bash -c "$1"
    fi
}

# Shortcuts for common operations.
_psql_admin()  { _pg_exec "psql -d postgres    -tAqc $(printf '%q' "$1")"; }
_psql_src()    { _pg_exec "psql -d $(printf '%q' "$SOURCE_DB") -tAqc $(printf '%q' "$1")"; }
_psql_drill()  { _pg_exec "psql -d $(printf '%q' "$DRILL_DB")  -tAqc $(printf '%q' "$1")"; }

# ── HARD GUARDS ───────────────────────────────────────────────────────────────
for _db in "$SOURCE_DB" "$DRILL_DB"; do
    case "$_db" in
        *drill|*src) : ;;   # must end in 'drill' or 'src'
        *) echo "FATAL: DB name '$_db' must end in 'drill' or 'src' — refusing." >&2; exit 2 ;;
    esac
    case "$_db" in
        halqe_app|halqe_app_test|postgres|template0|template1)
            echo "FATAL: DB name '$_db' is a protected name — refusing." >&2; exit 2 ;;
    esac
done

# ── Tracking vars for cleanup ─────────────────────────────────────────────────
CREATED_SOURCE=0
CREATED_DRILL=0
CONTAINER_TMP_DUMP=""   # path inside container (or local tmp path)

FAILED=0
note_fail() { echo "    [FAIL] $1"; FAILED=1; }
note_ok()   { echo "    [ OK ] $1"; }

# ── EXIT trap — always drop both DBs and remove temp files ────────────────────
cleanup() {
    local ec=$?
    echo ""
    echo "==> cleanup"
    if [ "$CREATED_DRILL" -eq 1 ]; then
        echo "    dropping throwaway DB '$DRILL_DB'"
        _psql_admin "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DRILL_DB' AND pid <> pg_backend_pid()" >/dev/null 2>&1 || true
        _psql_admin "DROP DATABASE IF EXISTS \"$DRILL_DB\"" >/dev/null 2>&1 || true
    fi
    if [ "$CREATED_SOURCE" -eq 1 ]; then
        echo "    dropping source DB '$SOURCE_DB'"
        _psql_admin "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$SOURCE_DB' AND pid <> pg_backend_pid()" >/dev/null 2>&1 || true
        _psql_admin "DROP DATABASE IF EXISTS \"$SOURCE_DB\"" >/dev/null 2>&1 || true
    fi
    if [ -n "${CONTAINER_TMP_DUMP:-}" ]; then
        echo "    removing temp dump $CONTAINER_TMP_DUMP"
        _pg_exec "rm -f $(printf '%q' "$CONTAINER_TMP_DUMP")" >/dev/null 2>&1 || true
    fi
    if [ -n "${PG_CONTAINER:-}" ] && [ -n "${CONTAINER_SLICE_DIR:-}" ]; then
        _pg_exec "rm -rf $(printf '%q' "$CONTAINER_SLICE_DIR")" >/dev/null 2>&1 || true
    fi
    return $ec
}
trap cleanup EXIT

# ── Banner ────────────────────────────────────────────────────────────────────
echo "============================================================"
echo " halqe RESTORE DRILL"
if [ -n "$PG_CONTAINER" ]; then
    echo "   mode      : docker exec into container '$PG_CONTAINER'"
    echo "   pg        : $_PG_HOST:$_PG_PORT (inside container)"
else
    echo "   pg        : $(pg_target_desc "postgres")"
fi
echo "   source DB : $SOURCE_DB (will be built fresh then dropped)"
echo "   drill  DB : $DRILL_DB  (throwaway — dropped on exit)"
echo "   slices    : $HOST_SLICE_DIR"
echo "============================================================"

# ── Validate slice dir ────────────────────────────────────────────────────────
[ -d "$HOST_SLICE_DIR" ] || {
    echo "FATAL: SCHEMA_SLICE_DIR not found: $HOST_SLICE_DIR" >&2
    echo "Set SCHEMA_SLICE_DIR to the directory containing schema_pg_slice*.sql" >&2
    exit 3
}
SLICE_COUNT="$(ls "$HOST_SLICE_DIR"/schema_pg_slice*.sql 2>/dev/null | wc -l | tr -d ' ')"
[ "${SLICE_COUNT:-0}" -gt 0 ] || {
    echo "FATAL: no schema_pg_slice*.sql files found in $HOST_SLICE_DIR" >&2; exit 3
}
echo "==> found $SLICE_COUNT schema slices in $HOST_SLICE_DIR"

# ── (a) Build fresh source DB ─────────────────────────────────────────────────
echo "==> (a) building fresh source DB '$SOURCE_DB'"
_psql_admin "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$SOURCE_DB' AND pid <> pg_backend_pid()" >/dev/null 2>&1 || true
_psql_admin "DROP DATABASE IF EXISTS \"$SOURCE_DB\"" >/dev/null
_psql_admin "CREATE DATABASE \"$SOURCE_DB\"" >/dev/null
CREATED_SOURCE=1

# --- if using container, copy slices into it (a tmpdir inside the container) --
if [ -n "$PG_CONTAINER" ]; then
    _pg_exec "mkdir -p $(printf '%q' "$CONTAINER_SLICE_DIR")"
    SLICE_DIR_FOR_APPLY="$CONTAINER_SLICE_DIR"
    # Copy each slice file into the container.
    for f in "$HOST_SLICE_DIR"/schema_pg_slice*.sql; do
        docker cp "$f" "$PG_CONTAINER:$CONTAINER_SLICE_DIR/" >/dev/null
    done
else
    SLICE_DIR_FOR_APPLY="$HOST_SLICE_DIR"
fi

# --- apply slices in numeric order (replicate apply_schema's ordering) --------
# Inline sort: build "0000000002 b /path" lines, sort, extract paths.
APPLY_SLICES_SCRIPT="$(cat <<'PYEOF'
import os, re, sys
d = sys.argv[1]
files = [f for f in os.listdir(d) if re.match(r'schema_pg_slice\d+', f) and f.endswith('.sql')]
def key(name):
    m = re.search(r'schema_pg_slice(\d+)([a-z]*)', name)
    return (int(m.group(1)), m.group(2)) if m else (9999, name)
for f in sorted(files, key=key):
    print(os.path.join(d, f))
PYEOF
)"

# Prefer python/python3 if available (for correct sorting); fall back to bash.
_sorted_slices() {
    local sd="$1"
    if _pg_exec "command -v python3 >/dev/null 2>&1"; then
        _pg_exec "python3 -c $(printf '%q' "$APPLY_SLICES_SCRIPT") $(printf '%q' "$sd")"
    elif _pg_exec "command -v python >/dev/null 2>&1"; then
        _pg_exec "python -c $(printf '%q' "$APPLY_SLICES_SCRIPT") $(printf '%q' "$sd")"
    else
        # bash-only: extract number+suffix, zero-pad, sort
        _pg_exec "for f in $(printf '%q' "$sd")/schema_pg_slice*.sql; do
          b=\"\$(basename \"\$f\")\";
          num=\"\$(echo \"\$b\" | sed -E 's/^schema_pg_slice([0-9]+).*/\1/')\";
          suf=\"\$(echo \"\$b\" | sed -E 's/^schema_pg_slice[0-9]+([a-z]*).*/\1/')\";
          printf '%010d %s %s\n' \"\$num\" \"\${suf:-_}\" \"\$f\";
        done | LC_ALL=C sort | awk '{print \$3}'"
    fi
}

echo "==> applying $SLICE_COUNT slices to '$SOURCE_DB'"
# Run as a single bash script inside (or locally) to avoid one exec per slice.
APPLY_CMD="$(cat <<SHEOF
set -e
export PGPASSWORD=\${PGPASSWORD:-}
# Collect sorted slice paths
declare -a SLICES
while IFS= read -r line; do SLICES+=("\$line"); done < <(
  for f in $(printf '%q' "$SLICE_DIR_FOR_APPLY")/schema_pg_slice*.sql; do
    b="\$(basename "\$f")"
    num="\$(echo "\$b" | sed -E 's/^schema_pg_slice([0-9]+).*/\1/')"
    suf="\$(echo "\$b" | sed -E 's/^schema_pg_slice[0-9]+([a-z]*).*/\1/')"
    printf '%010d %s %s\n' "\$num" "\${suf:-_}" "\$f"
  done | LC_ALL=C sort | awk '{print \$3}'
)
for f in "\${SLICES[@]}"; do
  psql -v ON_ERROR_STOP=1 -d $(printf '%q' "$SOURCE_DB") -q -f "\$f" >/dev/null
done
echo "    slices applied: \${#SLICES[@]}"
SHEOF
)"
if [ -n "$PG_CONTAINER" ]; then
    MSYS_NO_PATHCONV=1 docker exec -i \
        -e "PGHOST=$_PG_HOST" -e "PGPORT=$_PG_PORT" \
        -e "PGUSER=${PGUSER:-postgres}" -e "PGPASSWORD=${PGPASSWORD:-}" \
        "$PG_CONTAINER" bash -c "$APPLY_CMD"
else
    bash -c "$APPLY_CMD"
fi

# --- populate platform.schema_version (replicating apply_schema's ledger) -----
echo "==> populating platform.schema_version ledger (sha256 per slice)"
LEDGER_CMD="$(cat <<SHEOF
set -e
export PGPASSWORD=\${PGPASSWORD:-}
psql -v ON_ERROR_STOP=1 -d $(printf '%q' "$SOURCE_DB") -tAqc "
  CREATE TABLE IF NOT EXISTS platform.schema_version (
    filename   TEXT PRIMARY KEY,
    checksum   TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
  )" >/dev/null
for f in $(printf '%q' "$SLICE_DIR_FOR_APPLY")/schema_pg_slice*.sql; do
  fn="\$(basename "\$f")"
  sum="\$(sha256sum "\$f" | cut -d' ' -f1)"
  psql -v ON_ERROR_STOP=1 -d $(printf '%q' "$SOURCE_DB") -tAqc "
    INSERT INTO platform.schema_version (filename, checksum) VALUES ('\$fn','\$sum')
    ON CONFLICT (filename) DO UPDATE SET checksum=EXCLUDED.checksum, applied_at=now()" >/dev/null
done
echo "    schema_version rows: \$(psql -d $(printf '%q' "$SOURCE_DB") -tAqc 'SELECT count(*) FROM platform.schema_version')"
SHEOF
)"
if [ -n "$PG_CONTAINER" ]; then
    MSYS_NO_PATHCONV=1 docker exec -i \
        -e "PGHOST=$_PG_HOST" -e "PGPORT=$_PG_PORT" \
        -e "PGUSER=${PGUSER:-postgres}" -e "PGPASSWORD=${PGPASSWORD:-}" \
        "$PG_CONTAINER" bash -c "$LEDGER_CMD"
else
    bash -c "$LEDGER_CMD"
fi

# --- seed a couple of rows for row-count verification ------------------------
# ASCII-only seed values: the drill only verifies ROW COUNTS, never the text.
# Non-ASCII (Persian) literals get mangled to cp1252 (byte 0x85) when piped
# through git-bash → docker exec on a Windows host, breaking the INSERT.
_psql_src "INSERT INTO accounting.patients (tenant_id, name, family_name, national_id)
  VALUES (1,'DrillPatient','One','0011223344'),(1,'DrillPatient','Two','0055667788')
  ON CONFLICT (tenant_id, national_id) DO NOTHING" >/dev/null
_psql_src "INSERT INTO clinical.patient_links (tenant_id, patient_id)
  SELECT p.tenant_id, p.id FROM accounting.patients p
  WHERE p.national_id IN ('0011223344','0055667788')
  ON CONFLICT (tenant_id, patient_id) DO NOTHING" >/dev/null

SRC_SUM="$(_psql_src "SELECT 'tenants='||count(*) FROM platform.tenants"): $(_psql_src "SELECT 'patients='||count(*) FROM accounting.patients"): $(_psql_src "SELECT 'links='||count(*) FROM clinical.patient_links")"
echo "==> source DB ready: $SRC_SUM"

# ── (b) pg_dump source into a temp file (inside container or local /tmp) ─────
echo "==> (b) dumping '$SOURCE_DB'"
if [ -n "$PG_CONTAINER" ]; then
    # temp file lives inside the container — no cross-boundary file transfer needed
    TMP_NAME="halqe-drill-$$.dump"
    CONTAINER_TMP_DUMP="/tmp/$TMP_NAME"
    MSYS_NO_PATHCONV=1 docker exec -i \
        -e "PGHOST=$_PG_HOST" -e "PGPORT=$_PG_PORT" \
        -e "PGUSER=${PGUSER:-postgres}" -e "PGPASSWORD=${PGPASSWORD:-}" \
        "$PG_CONTAINER" bash -c \
        "pg_dump -Fc --no-owner --no-privileges -d $(printf '%q' "$SOURCE_DB") -f $(printf '%q' "$CONTAINER_TMP_DUMP")"
    DUMP_BYTES="$(_pg_exec "wc -c < $(printf '%q' "$CONTAINER_TMP_DUMP") | tr -d ' '")"
    DUMP_PATH="$CONTAINER_TMP_DUMP"   # used only for reference in messages
else
    DUMP_PATH="$(mktemp -t halqe-drill-XXXXXX).dump"
    pg_dump -Fc --no-owner --no-privileges -d "$SOURCE_DB" -f "$DUMP_PATH"
    DUMP_BYTES="$(wc -c < "$DUMP_PATH" | tr -d ' ')"
fi
echo "    dump path : $DUMP_PATH"
echo "    dump bytes: $DUMP_BYTES"

# ── (c) create throwaway verify DB ───────────────────────────────────────────
echo "==> (c) creating throwaway DB '$DRILL_DB'"
_psql_admin "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DRILL_DB' AND pid <> pg_backend_pid()" >/dev/null 2>&1 || true
_psql_admin "DROP DATABASE IF EXISTS \"$DRILL_DB\"" >/dev/null
_psql_admin "CREATE DATABASE \"$DRILL_DB\"" >/dev/null
CREATED_DRILL=1

# ── (d) pg_restore into throwaway ────────────────────────────────────────────
echo "==> (d) restoring into '$DRILL_DB'"
if [ -n "$PG_CONTAINER" ]; then
    MSYS_NO_PATHCONV=1 docker exec -i \
        -e "PGHOST=$_PG_HOST" -e "PGPORT=$_PG_PORT" \
        -e "PGUSER=${PGUSER:-postgres}" -e "PGPASSWORD=${PGPASSWORD:-}" \
        "$PG_CONTAINER" bash -c \
        "pg_restore --no-owner --no-privileges --exit-on-error -d $(printf '%q' "$DRILL_DB") $(printf '%q' "$CONTAINER_TMP_DUMP")"
else
    pg_restore --no-owner --no-privileges --exit-on-error -d "$DRILL_DB" "$DUMP_PATH"
fi

# ── (e) VERIFY ───────────────────────────────────────────────────────────────
echo "==> (e) verifying restored DB '$DRILL_DB'"

SV_EXISTS="$(_psql_drill "SELECT to_regclass('platform.schema_version') IS NOT NULL")"
if [ "$SV_EXISTS" = "t" ]; then
    SV_ROWS="$(_psql_drill "SELECT count(*) FROM platform.schema_version")"
    if [ "${SV_ROWS:-0}" -ge "$MIN_SCHEMA_ROWS" ]; then
        note_ok "platform.schema_version: $SV_ROWS slice(s) recorded (>= $MIN_SCHEMA_ROWS)"
        LATEST="$(_psql_drill "SELECT filename FROM platform.schema_version ORDER BY applied_at DESC, filename DESC LIMIT 1")"
        echo "           latest in ledger: $LATEST"
    else
        note_fail "platform.schema_version has $SV_ROWS rows (< $MIN_SCHEMA_ROWS)"
    fi
else
    note_fail "platform.schema_version table is MISSING in restored DB"
fi

for t in platform.tenants accounting.patients clinical.patient_links; do
    EX="$(_psql_drill "SELECT to_regclass('$t') IS NOT NULL")"
    if [ "$EX" = "t" ]; then
        note_ok "table exists: $t"
    else
        note_fail "table MISSING: $t"
    fi
done

T_ROWS="$(_psql_drill "SELECT count(*) FROM platform.tenants" 2>/dev/null || echo ERR)"
if [ "$T_ROWS" != "ERR" ] && [ "${T_ROWS:-0}" -ge "$MIN_TENANTS" ]; then
    note_ok "platform.tenants row count: $T_ROWS (>= $MIN_TENANTS)"
else
    note_fail "platform.tenants row count failed (got '$T_ROWS', need >= $MIN_TENANTS)"
fi

P_ROWS="$(_psql_drill "SELECT count(*) FROM accounting.patients" 2>/dev/null || echo ERR)"
L_ROWS="$(_psql_drill "SELECT count(*) FROM clinical.patient_links" 2>/dev/null || echo ERR)"
if [ "$P_ROWS" != "ERR" ] && [ "$L_ROWS" != "ERR" ]; then
    note_ok "accounting.patients=$P_ROWS  clinical.patient_links=$L_ROWS (readable)"
else
    note_fail "could not read patient tables (patients='$P_ROWS' links='$L_ROWS')"
fi

echo "------------------------------------------------------------"
if [ "$FAILED" -ne 0 ]; then
    echo " DRILL RESULT: FAIL — verify checks failed. See [FAIL] lines above."
    exit 1
fi
echo " DRILL RESULT: PASS — dump taken, restored, and verified."
echo "------------------------------------------------------------"
# cleanup (drop both DBs + temp files) runs via EXIT trap

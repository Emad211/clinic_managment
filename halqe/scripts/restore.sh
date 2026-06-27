#!/usr/bin/env bash
# scripts/restore.sh — restore a halqe .dump into a TARGET database.
#
# WHAT IT DOES
#   pg_restore a custom-format dump (produced by backup.sh) into an explicitly
#   named target DB. This is a DESTRUCTIVE operation for the target — guarded so
#   it cannot silently clobber a production/main DB.
#
# SAFETY GUARDS
#   * The target DB name is a REQUIRED explicit argument — no default.
#   * A built-in DENYLIST refuses obviously-real DB names (halqe_app,
#     halqe_app_test, postgres, template0/1) unless you pass --force.
#   * If the target DB already exists AND is non-empty (has user tables), the
#     script refuses unless --force is given.
#   * --create drops & recreates the target first (still subject to denylist).
#
# CONNECTION (no hardcoded credentials — read from env; see _pg_env.sh):
#   PGHOST/PGPORT/PGUSER/PGPASSWORD  or DATABASE_URL  or PG_HOST/PG_PORT/...
#   (PGDATABASE is IGNORED for restore — the target is the positional arg.)
#
# USAGE
#   scripts/restore.sh <dump-file> <target-db> [--create] [--force]
#
#   scripts/restore.sh backups/halqe-halqe_app-20260627-031500.dump halqe_restore_check --create
#   scripts/restore.sh mydump.dump halqe_app --force        # override denylist (DANGER)
#
# Verifies the sidecar .sha256 (if present) before restoring.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_pg_env.sh
. "$SCRIPT_DIR/_pg_env.sh"

usage() { sed -n '2,30p' "$0"; exit "${1:-2}"; }

DUMP=""
TARGET=""
DO_CREATE=0
FORCE=0
for arg in "$@"; do
    case "$arg" in
        --create) DO_CREATE=1 ;;
        --force)  FORCE=1 ;;
        -h|--help) usage 0 ;;
        -*) echo "unknown flag: $arg" >&2; usage 2 ;;
        *)
            if [ -z "$DUMP" ]; then DUMP="$arg"
            elif [ -z "$TARGET" ]; then TARGET="$arg"
            else echo "unexpected arg: $arg" >&2; usage 2
            fi
            ;;
    esac
done

[ -n "$DUMP" ]   || { echo "ERROR: dump file is required." >&2; usage 2; }
[ -n "$TARGET" ] || { echo "ERROR: target DB name is required." >&2; usage 2; }
[ -f "$DUMP" ]   || { echo "ERROR: dump file not found: $DUMP" >&2; exit 1; }

# --- DENYLIST: never restore over these without --force ----------------------
DENY="postgres template0 template1 halqe_app halqe_app_test"
for d in $DENY; do
    if [ "$TARGET" = "$d" ] && [ "$FORCE" -ne 1 ]; then
        echo "REFUSING to restore into protected DB '$TARGET' (denylist)." >&2
        echo "Pass --force only if you are certain. This is destructive." >&2
        exit 3
    fi
done

echo "==> halqe restore"
echo "    dump   : $DUMP"
echo "    target : $(pg_target_desc "$TARGET")"

# --- integrity check via sidecar checksum (if present) -----------------------
if [ -f "$DUMP.sha256" ] && command -v sha256sum >/dev/null 2>&1; then
    echo "==> verifying dump checksum"
    EXPECT="$(cut -d' ' -f1 < "$DUMP.sha256")"
    ACTUAL="$(sha256sum "$DUMP" | cut -d' ' -f1)"
    if [ "$EXPECT" != "$ACTUAL" ]; then
        echo "CHECKSUM MISMATCH — dump may be corrupt. Aborting." >&2
        echo "    expected: $EXPECT" >&2
        echo "    actual  : $ACTUAL" >&2
        exit 4
    fi
    echo "    checksum OK"
fi

# psql helper against the maintenance DB (postgres) for CREATE/DROP/existence.
_psql_admin() { psql -d postgres -tAqc "$1"; }

DB_EXISTS="$(_psql_admin "SELECT 1 FROM pg_database WHERE datname='$TARGET'" || true)"

if [ "$DO_CREATE" -eq 1 ]; then
    echo "==> (--create) dropping & recreating $TARGET"
    _psql_admin "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$TARGET' AND pid <> pg_backend_pid()" >/dev/null 2>&1 || true
    _psql_admin "DROP DATABASE IF EXISTS \"$TARGET\"" >/dev/null
    _psql_admin "CREATE DATABASE \"$TARGET\"" >/dev/null
    DB_EXISTS="1"
elif [ -z "$DB_EXISTS" ]; then
    echo "==> target does not exist — creating $TARGET"
    _psql_admin "CREATE DATABASE \"$TARGET\"" >/dev/null
    DB_EXISTS="1"
else
    # Target exists and we are NOT recreating — refuse if it has user tables.
    NTABLES="$(psql -d "$TARGET" -tAqc "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema')" || echo 0)"
    if [ "${NTABLES:-0}" -gt 0 ] && [ "$FORCE" -ne 1 ]; then
        echo "REFUSING: target '$TARGET' already has $NTABLES table(s)." >&2
        echo "Use --create to drop+recreate, or --force to restore on top." >&2
        exit 5
    fi
fi

echo "==> pg_restore into $TARGET"
# --no-owner/--no-privileges: roles in the dump may not exist in this cluster.
# --exit-on-error so a partial/failed restore is a hard failure, not silent.
pg_restore --no-owner --no-privileges --exit-on-error -d "$TARGET" "$DUMP"

echo "==> restore complete into $TARGET"

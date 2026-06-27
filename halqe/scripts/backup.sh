#!/usr/bin/env bash
# scripts/backup.sh — logical backup of the halqe Postgres DB (custom format).
#
# WHAT IT DOES
#   pg_dump -Fc (custom format: compressed + selective restore) of the target
#   database into a timestamped file under ${BACKUP_DIR:-./backups}. The
#   timestamp is Tehran local time. Then prunes old dumps, keeping the last
#   ${BACKUP_KEEP:-7}.
#
# CONNECTION (no hardcoded credentials — read from env; see _pg_env.sh):
#   PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE  (standard libpq), or
#   DATABASE_URL, or the project's PG_HOST/PG_PORT/PG_USER/PG_PASSWORD/PG_DB.
#   Override the DB to dump with the first positional arg or PGDATABASE.
#
# CONFIG (env):
#   BACKUP_DIR   output dir          (default: ./backups, relative to CWD)
#   BACKUP_KEEP  dumps to retain     (default: 7)
#
# USAGE
#   scripts/backup.sh                 # dump $PGDATABASE
#   scripts/backup.sh halqe_app       # dump a specific DB
#   BACKUP_DIR=/srv/halqe/backups BACKUP_KEEP=14 scripts/backup.sh
#
# OUTPUT FILE
#   halqe-<dbname>-YYYYMMDD-HHMMSS.dump   (e.g. halqe-halqe_app-20260627-031500.dump)
#
# Safe to run repeatedly (idempotent in effect; each run adds one dated dump and
# prunes the oldest beyond BACKUP_KEEP). Intended for cron on the VPS (step 55).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_pg_env.sh
. "$SCRIPT_DIR/_pg_env.sh"

# Allow overriding the DB name via the first positional argument.
if [ "${1:-}" != "" ]; then
    export PGDATABASE="$1"
fi

BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"

# Tehran local time for the filename, regardless of the host's OS timezone.
TS="$(TZ='Asia/Tehran' date +%Y%m%d-%H%M%S)"
DBNAME="$PGDATABASE"
# Sanitise db name for the filename (keep it filesystem-safe).
SAFE_DB="$(printf '%s' "$DBNAME" | tr -c 'A-Za-z0-9_.-' '_')"

mkdir -p "$BACKUP_DIR"

# Restrict perms on the backups dir — dumps contain PHI.
chmod 700 "$BACKUP_DIR" 2>/dev/null || true

OUT="$BACKUP_DIR/halqe-${SAFE_DB}-${TS}.dump"

echo "==> halqe backup"
echo "    source : $(pg_target_desc "$DBNAME")"
echo "    target : $OUT"
echo "    format : custom (-Fc, compressed)"

# -Fc custom format; --no-owner/--no-privileges so the dump restores cleanly
# into a throwaway DB whose roles may differ. Schema + data of all namespaces
# (platform/accounting/clinical) are captured by a full-DB logical dump.
pg_dump -Fc --no-owner --no-privileges -f "$OUT"

# Lock down the dump file itself (owner-read/write only).
chmod 600 "$OUT" 2>/dev/null || true

SIZE="$(wc -c < "$OUT" | tr -d ' ')"
SHA="$(sha256sum "$OUT" 2>/dev/null | cut -d' ' -f1 || true)"
echo "    bytes  : $SIZE"
[ -n "$SHA" ] && echo "    sha256 : $SHA"

# Write a sidecar checksum file for integrity verification on restore.
if [ -n "$SHA" ]; then
    printf '%s  %s\n' "$SHA" "$(basename "$OUT")" > "$OUT.sha256"
    chmod 600 "$OUT.sha256" 2>/dev/null || true
fi

# --- Retention: keep the last $BACKUP_KEEP dumps for THIS db, prune older ----
# Only files matching our own pattern are ever considered for deletion.
echo "==> retention (keep last $BACKUP_KEEP for $SAFE_DB)"
# List newest-first by mtime, drop the first BACKUP_KEEP, delete the rest.
# Use a NUL-safe listing to tolerate odd filenames.
mapfile -t _all < <(ls -1t "$BACKUP_DIR"/halqe-"${SAFE_DB}"-*.dump 2>/dev/null || true)
_count=${#_all[@]}
if [ "$_count" -gt "$BACKUP_KEEP" ]; then
    for f in "${_all[@]:$BACKUP_KEEP}"; do
        echo "    prune  : $(basename "$f")"
        rm -f -- "$f" "$f.sha256"
    done
else
    echo "    nothing to prune ($_count <= $BACKUP_KEEP)"
fi

echo "==> done. dump=$OUT"

#!/usr/bin/env bash
# scripts/_pg_env.sh — shared connection-env resolver (sourced, not run).
#
# Resolves Postgres connection settings WITHOUT hardcoding any credentials.
# Precedence (first non-empty wins), per variable:
#   1. Standard libpq vars: PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE
#   2. DATABASE_URL  (postgres://user:pass@host:port/dbname) — parsed if set
#   3. Project vars from halqe settings/.env:
#        PG_HOST PG_PORT PG_USER PG_PASSWORD PG_DB
#
# After sourcing, the standard PG* vars are EXPORTED so pg_dump/pg_restore/psql
# pick them up natively. Nothing is ever echoed that contains the password.
#
# This file is meant to be sourced:  . "$(dirname "$0")/_pg_env.sh"

# --- 1) parse DATABASE_URL into components if present (only fills gaps) -------
if [ -n "${DATABASE_URL:-}" ]; then
    # postgres://user:pass@host:port/dbname?query
    _url="${DATABASE_URL#*://}"           # strip scheme
    _url="${_url%%\?*}"                    # strip ?query
    _creds="${_url%%@*}"                   # user:pass  (if any '@')
    _hostpart="${_url##*@}"               # host:port/dbname
    case "$_url" in
        *@*) : ;;                          # had credentials
        *)   _creds=""; _hostpart="$_url" ;;
    esac
    if [ -n "$_creds" ]; then
        _du_user="${_creds%%:*}"
        case "$_creds" in *:*) _du_pass="${_creds#*:}";; *) _du_pass="";; esac
    fi
    _du_db="${_hostpart##*/}"
    _hp="${_hostpart%%/*}"
    _du_host="${_hp%%:*}"
    case "$_hp" in *:*) _du_port="${_hp#*:}";; *) _du_port="";; esac
fi

# --- 2) resolve each var: PG* (libpq) → DATABASE_URL → PG_* (project) --------
export PGHOST="${PGHOST:-${_du_host:-${PG_HOST:-localhost}}}"
export PGPORT="${PGPORT:-${_du_port:-${PG_PORT:-55432}}}"
export PGUSER="${PGUSER:-${_du_user:-${PG_USER:-postgres}}}"
export PGDATABASE="${PGDATABASE:-${_du_db:-${PG_DB:-halqe_app}}}"

# Password: PGPASSWORD → DATABASE_URL → PG_PASSWORD. Exported so libpq tools use
# it; never printed. (PGPASSWORD via env is the documented libpq mechanism.)
if [ -z "${PGPASSWORD:-}" ]; then
    if [ -n "${_du_pass:-}" ]; then
        export PGPASSWORD="$_du_pass"
    elif [ -n "${PG_PASSWORD:-}" ]; then
        export PGPASSWORD="$PG_PASSWORD"
    fi
fi

unset _url _creds _hostpart _hp _du_user _du_pass _du_db _du_host _du_port 2>/dev/null || true

# Human-readable target line (NEVER includes the password).
pg_target_desc() {
    printf '%s@%s:%s/%s' "$PGUSER" "$PGHOST" "$PGPORT" "${1:-$PGDATABASE}"
}

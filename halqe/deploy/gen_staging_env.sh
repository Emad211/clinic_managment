#!/usr/bin/env bash
# =============================================================================
# halqe — generate the STAGING .env ON THE SERVER (MVP step 81).
#
# WHY THIS EXISTS: the production .env carries random secrets. Typing 50-char
# secrets into the Arvan web console by hand is error-prone, and pasting may not
# work. This script GENERATES the secrets locally on the box (openssl) and writes
# a complete, correct halqe/.env — so the console flow is just:
#
#     git clone https://github.com/Emad211/clinic_managment.git /opt/halqe
#     cd /opt/halqe/halqe
#     bash deploy/gen_staging_env.sh
#     bash deploy/provision_vps.sh
#
# It is the STAGING-on-bare-IP profile: no domain, self-signed TLS, SMS OFF,
# scheduler worklist-only, GUNICORN_WORKERS tuned for 2 vCPU. Values mirror
# docs/deploy_runbook.md §2 + .env.example.
#
# SAFETY:
#   • REFUSES to overwrite an existing .env (re-running would rotate PG_PASSWORD
#     and lock you out of the already-initialised postgres volume). Use --force
#     ONLY on a truly fresh box with no pgdata volume yet.
#   • Never prints any secret. Only reports that the file was written.
# =============================================================================
set -euo pipefail

VPS_IP="${VPS_IP:-95.38.187.128}"   # ALLOWED_HOSTS + SEO base for the bare-IP box
FORCE=0
for a in "$@"; do
  case "$a" in
    --force) FORCE=1 ;;
    *) echo "ERROR: unknown arg '$a' (only --force)"; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HALQE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"     # .../halqe
ENV_FILE="${HALQE_DIR}/.env"

command -v openssl >/dev/null 2>&1 || { echo "ERROR: openssl not found (apt-get install -y openssl)"; exit 1; }

if [ -f "$ENV_FILE" ] && [ "$FORCE" -eq 0 ]; then
  echo "ERROR: ${ENV_FILE} already exists."
  echo "       Refusing to overwrite (would rotate the DB password and lock you"
  echo "       out of an initialised postgres volume). Edit it by hand, or pass"
  echo "       --force ONLY on a fresh box with no pgdata volume."
  exit 1
fi

# Strong URL/shell-safe secrets (base64 minus +/=; trimmed to fixed lengths).
gen() { openssl rand -base64 "$1" | tr -d '=+/\n' | cut -c1-"$2"; }
SECRET_KEY="$(gen 48 50)"
PG_PASSWORD="$(gen 32 32)"
PG_APP_PASSWORD="$(gen 32 32)"

umask 077   # the .env is created 0600
cat > "$ENV_FILE" <<EOF
# halqe STAGING .env — generated on-server by deploy/gen_staging_env.sh
# Bare-IP staging: no domain, self-signed TLS, SMS off, scheduler worklist-only.
PRODUCTION=1
SECRET_KEY=${SECRET_KEY}
DEBUG=false
ALLOWED_HOSTS=${VPS_IP}
CORS_ALLOWED_ORIGINS=
NEXT_PUBLIC_SITE_URL=https://${VPS_IP}

# Postgres superuser (container-internal only; never published to the host)
PG_USER=postgres
PG_PASSWORD=${PG_PASSWORD}
PG_DB=halqe_app
PG_HOST=postgres
PG_PORT=5432
# Least-privilege app role (ensure_app_role creates it with this password)
PG_APP_USER=halqe_app
PG_APP_PASSWORD=${PG_APP_PASSWORD}

# gunicorn workers tuned for 2 vCPU (default 3 is too many here)
GUNICORN_WORKERS=2

# SMS — HARD OFF until owner completes Kavenegar KYC (account returns 430)
KAVENEGAR_API_KEY=
SMS_LIVE_ENABLED=false

# Backups
BACKUP_KEEP=14
BACKUP_EVERY=86400

# Scheduler (step 80): worklist-only until the holdout cohort is frozen (V3)
SCHEDULER_WORKLIST_ONLY=1
SCHEDULER_EVERY=300
SCHEDULER_WARMUP=30
EOF
chmod 600 "$ENV_FILE"

echo "OK: wrote ${ENV_FILE} (0600, secrets generated on-server, not shown)."
echo "    PRODUCTION=1  ALLOWED_HOSTS=${VPS_IP}  SMS off  scheduler worklist-only  workers=2"
echo "    Next: bash deploy/provision_vps.sh"

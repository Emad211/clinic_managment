#!/usr/bin/env bash
# =============================================================================
# halqe — one-shot, idempotent VPS provisioning for the Iranian staging server
# (MVP step 81/82). Run it ON THE SERVER, from the repo-root of a fresh clone:
#
#     git clone https://github.com/Emad211/clinic_managment.git /opt/halqe
#     cd /opt/halqe/halqe            # <- .env lives here (owner-provided, git-ignored)
#     sudo bash deploy/provision_vps.sh
#
# This script is the COMPLEMENT to docs/deploy_runbook.md — it AUTOMATES the
# host prep the runbook describes as "owner-owned" (§1 prereqs, §4 cert, §5 first
# deploy) for the specific Arvan staging box. It does NOT re-implement anything
# the app already owns: schema apply + app-role creation stay in entrypoint.sh;
# .env is a PRECONDITION (never generated here); secrets are never printed.
#
# SERVER FACTS (confirmed by owner, 2026-07):
#   • ArvanCloud "Abrak", Ubuntu 22.04/24.04 (this script is version-agnostic).
#   • 2 vCPU / 4 GB RAM / IOPS ~1300. Public IP 95.38.187.128 straight on eth0.
#   • No domain → staging on the bare IP with a SELF-SIGNED cert (browser warning
#     is expected; real domain + Let's Encrypt is a T4 task — runbook §4).
#
# IRAN NETWORK CONSTRAINTS baked in (WHY each step exists is commented inline):
#   • Docker Hub (registry-1.docker.io) is BLOCKED from Iran → we set an Arvan
#     registry mirror before any pull (step 4).
#   • download.docker.com may be unreachable → Docker comes from Ubuntu's OWN apt
#     repo (docker.io + docker-compose-v2), NOT docker.com (step 3).
#   • 4 GB RAM + a Next.js build risks OOM → we ensure a 2 GB swapfile (step 2).
#
# IDEMPOTENT: every step checks state first and is safe to re-run. Re-running
# after a partial/failed run just continues.
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Tunables (top-of-file, as required). Override via env, e.g.
#   VPS_IP=1.2.3.4 sudo -E bash deploy/provision_vps.sh
# ---------------------------------------------------------------------------
VPS_IP="${VPS_IP:-95.38.187.128}"          # SAN of the self-signed staging cert
SWAP_SIZE_MB="${SWAP_SIZE_MB:-2048}"       # 2 GB swap (OOM guard for the web build)
CERT_DAYS="${CERT_DAYS:-365}"              # self-signed cert validity
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-300}"    # seconds to wait for services healthy
FORCE_CERT=0                               # --force-cert regenerates the cert
DEBIAN_FRONTEND=noninteractive
export DEBIAN_FRONTEND

# Arvan's official mirror (this box is ON Arvan → same-network, ideal) + a
# community fallback. Used only when /etc/docker/daemon.json has no mirror yet.
DOCKER_MIRRORS='["https://docker.arvancloud.ir", "https://focker.ir"]'

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
step() { echo; echo "==> $*"; }
info() { echo "    $*"; }
die()  { echo "ERROR: $*" >&2; exit 1; }

for arg in "$@"; do
    case "$arg" in
        --force-cert) FORCE_CERT=1 ;;
        *) die "unknown argument: $arg (only --force-cert is supported)" ;;
    esac
done

# The compose project lives in halqe/ (this script sits in halqe/deploy/). Resolve
# the halqe dir from the script's own location so cwd does not matter.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HALQE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"    # .../halqe
cd "${HALQE_DIR}"

# One compose invocation string reused everywhere (v2 plugin: `docker compose`).
COMPOSE="docker compose"

# ---------------------------------------------------------------------------
# STEP 1 — Preflight: privileges, OS, resources, and the .env PRECONDITION.
# ---------------------------------------------------------------------------
step "STEP 1: preflight"
[ "$(id -u)" -eq 0 ] || die "run with sudo/root (needs apt, docker daemon, /etc)."
info "user: $(id -un) (uid=$(id -u))"

if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    info "os: ${PRETTY_NAME:-unknown}"
    case "${VERSION_ID:-}" in
        22.04|24.04) : ;;  # tested
        *) info "note: untested Ubuntu ${VERSION_ID:-?} — script is version-agnostic, continuing." ;;
    esac
else
    info "os: /etc/os-release missing — continuing (best effort)."
fi

info "ram: $(free -h | awk '/^Mem:/{print $2}')   swap: $(free -h | awk '/^Swap:/{print $2}')"
info "disk (/): $(df -h / | awk 'NR==2{print $4" free of "$2}')"

# .env is the owner's secret-bearing file. It is git-ignored and NEVER generated
# here. Fail loud with guidance if it is missing.
if [ ! -f "${HALQE_DIR}/.env" ]; then
    cat >&2 <<EOF
ERROR: ${HALQE_DIR}/.env not found.

  .env is the owner-provided, secret-bearing config (git-ignored). This script
  never creates it. Provide it first, e.g. on the Arvan web console paste its
  contents, or scp it once SSH is reachable:

      cp .env.example .env   # then fill REAL values (see docs/deploy_runbook.md §2)

  It must contain PRODUCTION=1, a strong SECRET_KEY, explicit ALLOWED_HOSTS,
  and strong PG_PASSWORD / PG_APP_PASSWORD. Re-run this script afterwards.
EOF
    exit 1
fi
chmod 600 "${HALQE_DIR}/.env" 2>/dev/null || true

# Verify PRODUCTION=1 is present WITHOUT printing any .env content (no secret echo).
if grep -Eq '^[[:space:]]*PRODUCTION[[:space:]]*=[[:space:]]*1' "${HALQE_DIR}/.env"; then
    info ".env present and PRODUCTION=1 (contents not shown)."
else
    die ".env is present but PRODUCTION=1 is not set. Set PRODUCTION=1 (runbook §3) and re-run."
fi

# ---------------------------------------------------------------------------
# STEP 2 — Swap: ensure a 2 GB swapfile if the box has NO swap.
# WHY: 4 GB RAM + the Next.js (`docker compose build web`) step can OOM. Swap is
# the cheap insurance. Idempotent: only acts when `swapon --show` is empty.
# ---------------------------------------------------------------------------
step "STEP 2: swap (${SWAP_SIZE_MB} MB, only if none exists)"
if [ -n "$(swapon --show --noheadings 2>/dev/null || true)" ]; then
    info "swap already active — skipping."
else
    SWAPFILE=/swapfile
    if [ ! -f "$SWAPFILE" ]; then
        info "creating ${SWAP_SIZE_MB}MB swapfile at ${SWAPFILE} ..."
        # fallocate is fast; fall back to dd where the FS does not support it.
        if ! fallocate -l "${SWAP_SIZE_MB}M" "$SWAPFILE" 2>/dev/null; then
            info "fallocate unavailable — using dd (slower) ..."
            dd if=/dev/zero of="$SWAPFILE" bs=1M count="${SWAP_SIZE_MB}" status=none
        fi
    fi
    chmod 600 "$SWAPFILE"
    # mkswap is safe to re-run only on a non-active file; guard with blkid.
    if ! blkid "$SWAPFILE" >/dev/null 2>&1; then
        mkswap "$SWAPFILE" >/dev/null
    fi
    swapon "$SWAPFILE"
    # fstab: add the entry only once (idempotent).
    if ! grep -qE "^\s*${SWAPFILE}\s" /etc/fstab; then
        echo "${SWAPFILE} none swap sw 0 0" >> /etc/fstab
        info "added ${SWAPFILE} to /etc/fstab."
    fi
    info "swap active: $(free -h | awk '/^Swap:/{print $2}')"
fi

# ---------------------------------------------------------------------------
# STEP 3 — Packages from UBUNTU's OWN apt repo (NOT docker.com — it may be
# unreachable from Iran). docker.io + docker-compose-v2 give us `docker` and the
# `docker compose` v2 plugin, which is all the compose file needs.
# ---------------------------------------------------------------------------
step "STEP 3: apt packages (docker.io docker-compose-v2 git curl openssl)"
NEED_PKGS=""
for pkg in docker.io docker-compose-v2 git curl openssl; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
        NEED_PKGS="${NEED_PKGS} ${pkg}"
    fi
done
if [ -n "${NEED_PKGS# }" ]; then
    info "installing:${NEED_PKGS}"
    apt-get update -qq
    # shellcheck disable=SC2086
    apt-get install -y -qq ${NEED_PKGS}
else
    info "all packages already installed — skipping apt."
fi
docker --version || die "docker not available after install."
$COMPOSE version >/dev/null 2>&1 || die "'docker compose' v2 plugin not available."

# ---------------------------------------------------------------------------
# STEP 3b — Host clock: Tehran timezone + NTP sync (audit finding).
# WHY: the whole app is Tehran-local (backups' weekly schedule, structured-log
# timestamps) and JWT `exp` validation breaks if the host clock drifts. Compose
# passes TZ=Asia/Tehran to containers, but the HOST clock itself must be sane.
# ---------------------------------------------------------------------------
step "STEP 3b: host timezone (Asia/Tehran) + NTP"
CURRENT_TZ="$(timedatectl show -p Timezone --value 2>/dev/null || echo unknown)"
if [ "$CURRENT_TZ" = "Asia/Tehran" ]; then
    info "timezone already Asia/Tehran."
else
    timedatectl set-timezone Asia/Tehran && info "timezone set to Asia/Tehran (was: ${CURRENT_TZ})."
fi
# Enable NTP sync (systemd-timesyncd ships with Ubuntu; ignore if a chrony setup exists).
timedatectl set-ntp true 2>/dev/null || info "note: could not enable NTP via timedatectl (chrony?) — verify clock sync manually."
info "clock: $(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo '?') (NTPSynchronized)"

# ---------------------------------------------------------------------------
# STEP 4 — Docker registry mirror (CRITICAL for Iran). Docker Hub is blocked;
# point the daemon at Arvan's mirror (this box is on Arvan) + a fallback BEFORE
# any pull. Merge-safe: if daemon.json already has registry-mirrors, leave it be.
# ---------------------------------------------------------------------------
step "STEP 4: docker registry mirror (Iran — Docker Hub is blocked)"
DAEMON_JSON=/etc/docker/daemon.json
MIRROR_CHANGED=0
mkdir -p /etc/docker
if [ -f "$DAEMON_JSON" ] && grep -q "registry-mirrors" "$DAEMON_JSON"; then
    info "daemon.json already has registry-mirrors — leaving it untouched."
elif [ -f "$DAEMON_JSON" ] && [ -s "$DAEMON_JSON" ]; then
    # File exists with other content but no mirrors: do NOT clobber it blindly.
    info "WARNING: ${DAEMON_JSON} exists without registry-mirrors."
    info "Not overwriting an existing config automatically. Add manually:"
    info "  \"registry-mirrors\": ${DOCKER_MIRRORS}"
    info "Then: systemctl restart docker. Continuing (pulls may fail without it)."
else
    info "writing ${DAEMON_JSON} with Arvan mirror + fallback ..."
    cat > "$DAEMON_JSON" <<EOF
{
  "registry-mirrors": ${DOCKER_MIRRORS}
}
EOF
    MIRROR_CHANGED=1
fi

# ---------------------------------------------------------------------------
# STEP 5 — Enable docker; restart only if the mirror config changed; add ubuntu
# to the docker group (idempotent).
# ---------------------------------------------------------------------------
step "STEP 5: enable docker + group membership"
systemctl enable --now docker >/dev/null 2>&1 || die "could not enable/start docker."
if [ "$MIRROR_CHANGED" -eq 1 ]; then
    info "registry mirror changed → restarting docker ..."
    systemctl restart docker
fi
# Wait for the daemon socket to be live before any compose call.
for _ in $(seq 1 15); do
    if docker info >/dev/null 2>&1; then break; fi
    sleep 1
done
docker info >/dev/null 2>&1 || die "docker daemon not responding after start."

if id ubuntu >/dev/null 2>&1; then
    if id -nG ubuntu | tr ' ' '\n' | grep -qx docker; then
        info "user 'ubuntu' already in docker group."
    else
        usermod -aG docker ubuntu
        info "added 'ubuntu' to docker group (takes effect on next login/relogin)."
        info "this script runs as root, so it continues without relogin."
    fi
else
    info "user 'ubuntu' not present — skipping group step."
fi

# ---------------------------------------------------------------------------
# STEP 6 — Self-signed TLS cert INTO the compose `certs` named volume.
# WHY: no domain → nginx needs *some* cert at /etc/nginx/certs/{fullchain,privkey}.pem
# (see deploy/nginx/halqe.conf). We generate a cert with subjectAltName=IP:<VPS_IP>
# and drop it into the named volume via a throwaway alpine container (the volume
# does not exist as a host path). Idempotent: skip if fullchain.pem already there
# (unless --force-cert). This satisfies runbook §4 path B for staging.
# ---------------------------------------------------------------------------
step "STEP 6: self-signed TLS cert for IP:${VPS_IP} → compose 'certs' volume"

# Compose prefixes named volumes with the project name. Resolve the real volume
# name from `compose config` (authoritative) with a directory-name fallback.
CERTS_VOL="$($COMPOSE config --format json 2>/dev/null \
    | grep -o '"[a-zA-Z0-9_-]*_certs"' | head -n1 | tr -d '"' || true)"
if [ -z "${CERTS_VOL}" ]; then
    PROJECT="$(basename "${HALQE_DIR}" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')"
    CERTS_VOL="${PROJECT}_certs"
    info "compose config gave no volume name — falling back to '${CERTS_VOL}'."
else
    info "certs volume: ${CERTS_VOL}"
fi

# Ensure the named volume exists (compose creates it on `up`, but we write to it
# BEFORE up, so create it now — idempotent).
docker volume create "${CERTS_VOL}" >/dev/null

CERT_EXISTS="$(docker run --rm -v "${CERTS_VOL}:/certs" alpine:3 \
    sh -c 'test -f /certs/fullchain.pem && echo yes || echo no' 2>/dev/null || echo no)"

if [ "$CERT_EXISTS" = "yes" ] && [ "$FORCE_CERT" -eq 0 ]; then
    info "fullchain.pem already in volume — skipping (use --force-cert to regenerate)."
else
    info "generating self-signed cert (SAN IP:${VPS_IP}, ${CERT_DAYS}d) ..."
    TMP_CERT_DIR="$(mktemp -d)"
    trap 'rm -rf "${TMP_CERT_DIR}"' EXIT
    openssl req -x509 -nodes -newkey rsa:2048 \
        -keyout "${TMP_CERT_DIR}/privkey.pem" \
        -out    "${TMP_CERT_DIR}/fullchain.pem" \
        -days   "${CERT_DAYS}" \
        -subj   "/CN=${VPS_IP}" \
        -addext "subjectAltName=IP:${VPS_IP}" >/dev/null 2>&1 \
        || die "openssl cert generation failed."
    # Copy both files into the named volume via a throwaway alpine container.
    docker run --rm \
        -v "${CERTS_VOL}:/certs" \
        -v "${TMP_CERT_DIR}:/src:ro" \
        alpine:3 sh -c 'cp /src/fullchain.pem /certs/fullchain.pem \
            && cp /src/privkey.pem /certs/privkey.pem \
            && chmod 644 /certs/fullchain.pem && chmod 600 /certs/privkey.pem' \
        || die "copying cert into volume '${CERTS_VOL}' failed."
    rm -rf "${TMP_CERT_DIR}"
    trap - EXIT
    info "cert installed into volume '${CERTS_VOL}' (self-signed — browser warning is expected)."
fi

# ---------------------------------------------------------------------------
# STEP 7 — Validate → build → up → wait-healthy → probe.
# A plain `up` starts ONLY postgres/app/web/nginx (backup + scheduler are
# profile-gated). entrypoint.sh (app) applies the schema — we do NOT touch it.
# ---------------------------------------------------------------------------
step "STEP 7: compose config → build → up → health"

info "validating compose + .env interpolation ..."
$COMPOSE config -q || die "docker compose config failed (check .env). See runbook §5."

info "building images SEQUENTIALLY (audit: parallel build of backend+web can OOM on 4GB) ..."
# app first (pip wheels — light), then web (npm ci + next build — the heavy one).
# Building one-at-a-time removes the concurrent memory peak; swap (step 2) is the
# backstop. web/Dockerfile also caps the node heap (NODE_OPTIONS) for this box.
$COMPOSE build app
$COMPOSE build web

info "starting stack (postgres → app → web → nginx) ..."
$COMPOSE up -d

info "waiting up to ${HEALTH_TIMEOUT}s for services to become running/healthy ..."
deadline=$(( $(date +%s) + HEALTH_TIMEOUT ))
while :; do
    # A container that reports a health state must be 'healthy'; a container with
    # no healthcheck (web, nginx → Health="") only needs State=running. `BAD`
    # collects any container violating that, using the templated ps output.
    BAD="$($COMPOSE ps --format '{{.Service}} {{.State}} {{.Health}}' 2>/dev/null \
        | awk '$2!="running" || ($3!="" && $3!="healthy") {print}' || true)"
    if [ -z "$BAD" ]; then
        info "all services running/healthy."
        break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "    WARNING: timed out after ${HEALTH_TIMEOUT}s. Current state:" >&2
        $COMPOSE ps || true
        info "not fatal — inspect with: $COMPOSE logs app  /  $COMPOSE logs postgres"
        break
    fi
    sleep 5
done

info "probing TLS health endpoints (self-signed → curl -k) ..."
# /healthz = liveness (no DB); /readyz = readiness (DB reachable + app role).
HEALTHZ="$(curl -ks -o /dev/null -w '%{http_code}' https://127.0.0.1/healthz || echo 000)"
READYZ="$(curl -ks -o /dev/null -w '%{http_code}' https://127.0.0.1/readyz || echo 000)"
REDIR="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/ || echo 000)"
info "https /healthz -> ${HEALTHZ}   https /readyz -> ${READYZ}   http / -> ${REDIR} (expect 301)"
[ "$HEALTHZ" = "200" ] || info "WARNING: /healthz not 200 — check '$COMPOSE logs app'."
[ "$READYZ"  = "200" ] || info "WARNING: /readyz not 200 — DB or app role issue; check logs."

# ---------------------------------------------------------------------------
# STEP 8 — Summary + explicit reminders about the profile-gated services and the
# safe-by-default gates (SMS off / scheduler worklist-only).
# ---------------------------------------------------------------------------
step "STEP 8: summary"
$COMPOSE ps || true
cat <<EOF

    ---------------------------------------------------------------------------
    Provisioning complete for staging on https://${VPS_IP}/  (self-signed cert).

    RUNNING now (plain \`up\`): postgres, app, web, nginx.

    PROFILE-GATED (NOT started by \`up\` — bring up deliberately):
      • backups:   ${COMPOSE} --profile backup up -d backup
                   (or the recommended HOST cron — see deploy_runbook.md §7)
      • scheduler: ${COMPOSE} --profile scheduler up -d scheduler
                   (the follow-up/engagement ticker — needed for the clinical
                    worklist to generate; runbook §7 / docker-compose.yml)

    SAFE-BY-DESIGN GATES (leave as-is until the owner flips them):
      • SMS is OFF (SMS_LIVE_ENABLED=false + Kavenegar KYC 430). No real sends.
      • scheduler defaults to SCHEDULER_WORKLIST_ONLY=1 → generates the worklist
        but queues NO outreach until the holdout cohort is frozen (runbook §7).

    T3 DRILLS (runbook §6/§7 — run on this host, DB stays internal-only):
      • restore drill (uses the postgres CONTAINER's own version-matched tools;
        no host postgresql-client, no published port needed):
          PG_CONTAINER=\$(${COMPOSE} ps -q postgres) bash scripts/restore_drill.sh
      • pre-deploy backup: ${COMPOSE} --profile backup up -d backup   (or backup.sh)

    NEXT: verify from a compatible network / the Arvan web console:
      curl -k https://${VPS_IP}/healthz
    Rollback / backup / cert-to-Let's-Encrypt: see docs/deploy_runbook.md §4/§7/§8
    and docs/deploy_vps_arvan.md (this server's delta).
    ---------------------------------------------------------------------------
EOF

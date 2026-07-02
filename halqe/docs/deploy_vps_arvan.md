# halqe — Arvan VPS staging (delta on the runbook)

This is a **delta** on [`deploy_runbook.md`](deploy_runbook.md) for the specific
Iranian staging box the owner purchased. It does **not** repeat the runbook — read
that for topology, `.env` (§2), cert paths (§4), first deploy (§5), backups (§7),
and rollback (§8). Here we record only what is different for **this server** and
the one-shot automation that provisions it.

## The server (confirmed)

| Fact | Value |
|------|-------|
| Provider | **ArvanCloud "Abrak"** |
| OS | Ubuntu (22.04/24.04 — the provision script is version-agnostic) |
| Size | **2 vCPU / 4 GB RAM**, IOPS ~1300 |
| Public IP | **`95.38.187.128`** straight on `eth0` (no NAT — confirmed from console) |
| Ingress | `sshd` up; `ufw inactive`; Arvan firewall (arDefault) fully open |
| Users | `ubuntu` (sudo) + `root` (password) |
| Domain | **none** → staging on the bare IP with a **self-signed** cert |

## Network finding (for future troubleshooting)

The IP currently **routes only from certain Iranian fixed-line paths**. As of
provisioning:

- **Mobile (MCI / Irancell) does NOT reach it** — a routing gap on the mobile side,
  not a server problem.
- **International is blocked.**
- **GitHub is reachable from the server**, so cloning the repo on the box works
  even when you cannot SSH in from your own network.

Practical consequence: if SSH times out from your laptop/phone, use the **Arvan web
console** to drive the server. Do not assume the server is down.

## One-shot provisioning

Everything host-side is automated by [`../deploy/provision_vps.sh`](../deploy/provision_vps.sh)
— idempotent, safe to re-run. Run it **on the server**, from a fresh clone:

```sh
git clone https://github.com/Emad211/clinic_managment.git /opt/halqe
cd /opt/halqe/halqe
# Provide .env (owner-provided, secret-bearing, git-ignored). The real content is
# held by the owner/orchestrator — paste it in the Arvan console, or scp it once
# SSH is reachable. It MUST contain PRODUCTION=1 (see runbook §2/§3).
sudo bash deploy/provision_vps.sh
```

What the script does (why each step exists is commented in the script):

1. **Preflight** — root check, OS/RAM/disk print, and it **requires `halqe/.env`**
   with `PRODUCTION=1` (fails loudly with guidance if missing; never generates or
   prints secrets).
2. **Swap** — creates a **2 GB** swapfile if the box has none. *Why: 4 GB RAM + the
   Next.js `docker compose build web` step can OOM.*
3. **Packages** — installs `docker.io docker-compose-v2 git curl openssl` from
   **Ubuntu's own apt repo**, not `download.docker.com` (which may be unreachable
   from Iran). `docker-compose-v2` provides the `docker compose` plugin.
4. **Registry mirror** — writes `/etc/docker/daemon.json` with
   `https://docker.arvancloud.ir` (Arvan's official mirror — this box is *on* Arvan)
   + `https://focker.ir` fallback. *Why: Docker Hub (`registry-1.docker.io`) is
   blocked from Iran.* Merge-safe: leaves an existing mirror config untouched.
5. **Docker enable + group** — enables the daemon, restarts it only if the mirror
   changed, adds `ubuntu` to the `docker` group.
6. **Self-signed cert** — generates a cert with `subjectAltName=IP:95.38.187.128`
   and installs it into the compose **`certs` named volume** (the same volume
   `halqe.conf` reads `/etc/nginx/certs/{fullchain,privkey}.pem` from). Idempotent;
   `--force-cert` regenerates.
7. **Deploy** — `docker compose config -q` → `build` → `up -d`, then waits (≤300s)
   for services to be running/healthy and probes `https://127.0.0.1/healthz`,
   `/readyz`, and the `http → 301` redirect.
8. **Summary** — prints service state and the reminders below.

Override the IP for a different box: `VPS_IP=1.2.3.4 sudo -E bash deploy/provision_vps.sh`.

## Staging-on-IP specifics

- **Self-signed cert → the browser shows a warning.** That is expected on staging.
  For T4 / real production, get a **domain + Let's Encrypt** (runbook §4 path A) and
  set `ALLOWED_HOSTS` to that domain.
- **Profile-gated services are NOT started by `up`** (this is correct — see
  `docker-compose.yml`). Bring them up deliberately:
  - `docker compose --profile backup up -d backup` (or the host cron in runbook §7)
  - `docker compose --profile scheduler up -d scheduler` (the follow-up/engagement
    ticker — the clinical worklist won't generate without it)
- **Safe gates stay on:** SMS is OFF (`SMS_LIVE_ENABLED=false` + Kavenegar KYC 430);
  the scheduler defaults to `SCHEDULER_WORKLIST_ONLY=1` (worklist generated, no
  outreach queued until the holdout is frozen — runbook §7).

## Iran troubleshooting quick-table

| Symptom | Cause | Fix |
|---------|-------|-----|
| `docker compose build/up` hangs on image pull | Docker Hub blocked from Iran | script step 4 (Arvan mirror). If it still hangs, confirm `/etc/docker/daemon.json` has `registry-mirrors` then `systemctl restart docker`. |
| `web` build killed / OOM | 4 GB RAM + Next.js build | script step 2 (2 GB swap). Confirm `swapon --show` is non-empty; re-run the script. |
| `npm` step very slow inside the web build | npm registry latency from Iran | set an Iranian npm mirror (e.g. `npm config set registry <mirror>`) per the OFFLINE FALLBACK note in `halqe/web/Dockerfile`, or build on a connected box and `docker save | docker load`. |
| Can't SSH from phone | mobile routing gap (see above) | use the **Arvan web console**; the server itself is fine. |
| `apt-get install docker.io` fails | apt cache stale | script runs `apt-get update` first; if it still fails, check Ubuntu mirror reachability. |

For everything else (backup schedule, restore drill, rollback, cert renewal, the
go-live checklist) the authoritative source remains
[`deploy_runbook.md`](deploy_runbook.md).

---

## Post-deploy: T3 verification drills (run on THIS live box, from the Arvan console)

Verified by the team (principal-architect + delivery-reliability + security-privacy,
2026-07-02) against the running stack. None of these need real patient data — they
use throwaway/synthetic DBs and never touch the live `halqe_app` DB.

```sh
cd /opt/halqe/halqe
CF="-f docker-compose.yml -f deploy/compose.iran-mirrors.yml"   # keep the SAME -f set everywhere

# (a) restore drill — proves backups are actually restorable. Uses the postgres
#     CONTAINER's version-matched tools (host has no psql; port 5432 is unpublished).
#     PASS = final line "DRILL RESULT: PASS" + exit 0. Touches ONLY halqe_drill_src /
#     halqe_restore_drill (hard-guarded), never the live DB.
PG_CONTAINER=$(docker compose $CF ps -q postgres) \
  PGUSER="$PG_USER" PGPASSWORD="$PG_PASSWORD" bash scripts/restore_drill.sh

# (b) backup-before-deploy — dump lands in the NAMED VOLUME `backups` (NOT a host path).
docker compose $CF --profile backup up backup    # one-shot, watch output
#     then copy OFF-BOX (PHI must not live only in one volume):
docker run --rm -v halqe_backups:/b -v /root/halqe-backups:/out alpine sh -c 'cp /b/*.dump /b/*.sha256 /out/ 2>/dev/null; ls -l /out'

# (c) fail-fast boot guard — throwaway container, does NOT touch the live app.
#     PASS = NON-zero exit + explicit SECRET_KEY rejection.
docker compose $CF run --rm -e SECRET_KEY= app python -c "import config.settings"; echo "exit=$?"

# (d) 429 burst on the public token endpoints (need a real card token first).
#     PASS = 429 appears (card after ~6 rapid reqs, report after ~4).
for i in $(seq 1 20); do curl -k -s -o /dev/null -w "%{http_code}\n" https://127.0.0.1/api/v1/card/<TOKEN>; done | sort | uniq -c

# Bring up the scheduler (else the clinical worklist never generates in prod):
docker compose $CF --profile scheduler up -d scheduler
docker compose $CF ps            # scheduler must show healthy after warmup
```

## Pre-stage the T5 leak-gate NOW (no PHI needed)

Run the isolation/RLS/leak/verified suites on the LIVE prod-config Postgres, using the
least-privilege `halqe_app` role (NOT postgres — else the anti-false-green guard warns):
`test_rls_coverage`, `test_guc_leak`, `test_e2e_tenant_isolation` (+ the superuser guard),
`test_single_tenant_guarantee`, and the verified-gate card test. These build a `_test`
DB, so they never pollute `halqe_app`. If green here, T5 (step 83) becomes a rerun+sign,
not a bug hunt. ⚠️ Confirm RLS on `platform.users` (the E4 case must PASS, not warn).

## T4 (domain + Arvan CDN) — prep BEFORE the cutover

`halqehealth.ir` is bought (pending IRNIC). When live:
1. **CDN → origin**: add `halqehealth.ir` in Arvan CDN, A-record/origin → `95.38.187.128`,
   proxy ON. Edge is reachable from everywhere (incl. mobile) → this ALSO fixes the
   owner's access problem. `server_name _;` already accepts any Host — no nginx edit for that.
2. **`.env`**: add the domain to `ALLOWED_HOSTS` (currently IP,127.0.0.1,localhost).
3. **TLS**: Arvan edge serves a real DV cert to users; set CDN→origin to full/verify
   (keep origin TLS — self-signed is acceptable to the edge, or upgrade origin to
   Let's Encrypt via **DNS-01** since http-01 can't reach this box from outside). For
   PHI, edge-only TLS is NOT enough — the CDN→origin hop must be encrypted too.
4. **⚠️ real_ip (the #1 T4 risk)**: behind the CDN every request arrives from an Arvan
   EDGE ip, so `limit_req_zone $binary_remote_addr` (the sacred card/report rate-limit)
   would bucket ALL patients under one IP. FIX: add Arvan's official edge ranges to
   `set_real_ip_from` in `deploy/nginx/halqe.conf` (lines 82-87) so nginx trusts Arvan's
   XFF and extracts the real client IP. Then RE-TEST the 429 burst from an EXTERNAL
   network via the domain. (Get the edge ranges from Arvan's docs — do not guess.)
5. **Origin firewall (hide the origin)**: allow only Arvan edge ranges + `80/443` to the
   origin, else an attacker hits the IP directly and bypasses the CDN/WAF/rate-limit.
   `8000/5432` stay unpublished. Use the Arvan security-group (Docker bypasses UFW).

## Security cleanup after this deploy (owner, in the Arvan panel)

The code transfer exchanged three secrets over chat — rotate/close, in order:
1. **S3 keys** → revoke/rotate in the panel; make the `halqe-deploy` bucket **private** or
   **delete** it (and purge object versions). If S3 was a one-shot transfer tool, delete the key.
2. **Server console password** → change it; better, switch SSH to key-only
   (`PasswordAuthentication no`).
3. **(conservative)** rotate `SECRET_KEY` once (cheap now — no real sessions/PHI yet);
   do NOT rotate `PG_PASSWORD` (would lock out the initialised pgdata volume). Scan git
   history for accidental secrets. App secrets were generated on-server and never printed
   → safe unless the leaked root password let someone read `.env`.

> **Environments:** do NOT build a second box — upgrade THIS one to production
> (provision_vps.sh is idempotent). The staging→prod boundary is the **T5 gate**: before
> the first real patient row, wipe synthetic/drill DBs, record a final `restore_drill`
> PASS, and prove restore on a fresh host once (single-site disaster rehearsal).

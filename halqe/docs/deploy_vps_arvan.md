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

# halqe — Deploy Runbook (Iranian VPS, Docker Compose)

Step-by-step deployment of the halqe platform onto a single Iranian VPS using the
`docker-compose.yml` + nginx config built in **step 55 (cluster M)**.

> **⛔ OWNER GATE.** This runbook is CONFIG + DOCS. The actual VPS provisioning,
> the TLS certificates, the DNS records, the backup cron, and SMS go-live are the
> **owner's** responsibility and approval. Nothing here deploys anything live by
> itself. Treat every "run this on the VPS" step as owner-gated.

Related docs: [`backup_restore.md`](backup_restore.md) · [`sms_go_live.md`](sms_go_live.md) ·
[`adr/0008-tenant-guc-lifecycle-and-pooling.md`](adr/0008-tenant-guc-lifecycle-and-pooling.md).

---

## 0. Topology recap

```
internet ──443/80──▶ nginx ──(internal docker net)──▶ app:8000 ──▶ postgres:5432
                                                                      │
                                                            backup volume (pg_dump)
```

- **nginx is the only public ingress.** It publishes host ports `80` + `443`.
- **`app:8000` and `postgres:5432` are internal-only** — never published to the
  host. nginx is the single front door and the **real rate-limit boundary**.
- **CONN_MAX_AGE=0 invariant (ADR-0008):** the app talks to Postgres **directly**.
  There is **no transaction-mode pooler** (no PgBouncer). Do not add one — it
  would break the per-request tenant GUC lifecycle.
- Named volumes: `pgdata` (the DB), `backups` (pg_dump output), `certs` (TLS).

Files this runbook uses:
- `halqe/docker-compose.yml` — the topology.
- `halqe/deploy/nginx/halqe.conf` — TLS + reverse proxy + `limit_req`.
- `halqe/Dockerfile` + `halqe/entrypoint.sh` — the app image + startup (waits for
  PG, runs `apply_schema` + `ensure_app_role`, then `exec gunicorn`).
- `halqe/scripts/backup.sh` / `restore.sh` / `restore_drill.sh` — backup tooling.

---

## 1. Prerequisites (on the VPS — owner)

- A VPS with **Docker Engine + the Docker Compose plugin** (`docker compose`,
  not the old `docker-compose`).
- The repo checked out on the VPS (or the build context copied). The compose
  `app` service builds from the **repo root** context (`context: ..`) because the
  Dockerfile `COPY`s `halqe/` and `halqe/db/schema/` from the repo root.
- A DNS A record pointing your API hostname (e.g. `api.halqe.ir`) at the VPS IP.
- Ports `80` + `443` open in the VPS firewall; `8000`/`5432` **closed** to the
  internet (they are internal-only by design — do not open them).
- For restricted-network hosts that cannot reach PyPI: pre-build the image's
  wheels per the **OFFLINE FALLBACK** note in `halqe/Dockerfile`'s header.

---

## 2. Configure `.env` (no secrets in git)

Copy the template and fill in **real** values on the VPS only. `.env` is
git-ignored — never commit it.

```sh
cd halqe
cp .env.example .env
# then edit .env
```

Required for production (see `.env.example` for the full annotated list):

| Variable | Production value |
|----------|------------------|
| `PRODUCTION` | `1` — turns on the fail-fast boot guards (see §3). |
| `SECRET_KEY` | a strong unique value: `python -c "import secrets; print(secrets.token_urlsafe(50))"`. **Not** the dev placeholder. |
| `DEBUG` | irrelevant when `PRODUCTION=1` (forced `False`), but set `false`. |
| `ALLOWED_HOSTS` | explicit, no wildcard, e.g. `api.halqe.ir`. |
| `CORS_ALLOWED_ORIGINS` | the real web origin(s), e.g. `https://app.halqe.ir`. |
| `PG_DB` | the DB name (default `halqe_app`). Must match `POSTGRES_DB`. |
| `PG_USER` / `PG_PASSWORD` | the **superuser** creds. Compose passes these to the `postgres` service AND uses them for `apply_schema`/`ensure_app_role` + backups. Pick a strong password. |
| `PG_APP_USER` / `PG_APP_PASSWORD` | the **least-privilege app role** creds (Django ORM). Strong, distinct from the superuser. `ensure_app_role` creates this role on first boot. |
| `KAVENEGAR_API_KEY` | the live key — **env-only, never git**. Leave blank to stay on simulation. |
| `SMS_LIVE_ENABLED` | **`false`** — stays off until owner KYC (see §9 + `sms_go_live.md`). |

Notes:
- `.env` carries `PG_HOST`/`PG_PORT` pointing at the host-side dev port. Compose
  **overrides** these for the `app` service to `PG_HOST=postgres` / `PG_PORT=5432`
  (the internal network address). You do not need to change them for the app.
- Secrets live **only** in `.env` (chmod it `600` on the VPS). The compose file,
  the nginx conf, and every committed file contain **placeholders only**.

---

## 3. Production boot guards (what `PRODUCTION=1` enforces)

`config/settings.py` + `config/env.py` fail-fast on boot unless, with
`PRODUCTION=1`:
- `SECRET_KEY` is non-empty and not the dev placeholder → else the server
  refuses to start.
- `DEBUG` is forced `False` regardless of the env value.
- `ALLOWED_HOSTS` is explicit — a wildcard `*` is **rejected**.
- `CORS_ALLOWED_ORIGINS` comes from env (not the localhost dev default).

If any guard fails the container exits immediately — that is intended; fix `.env`
and re-up. This is part of the go-live checklist (§10).

---

## 4. TLS certificate provisioning (owner)

nginx expects certs at (inside the container) `/etc/nginx/certs/fullchain.pem`
and `/etc/nginx/certs/privkey.pem`, mounted from the `certs` named volume. Pick
**one** path:

**A) Let's Encrypt (recommended where reachable).**
- Use certbot on the host (standalone or webroot). For webroot, uncomment the
  `/.well-known/acme-challenge/` block in `halqe.conf` and mount a webroot.
- Copy/symlink the issued `fullchain.pem` + `privkey.pem` into the `certs`
  volume (e.g. populate `./deploy/nginx/certs/` on the host and switch the
  compose `certs` volume to a bind mount of that dir).
- Automate renewal (certbot cron/timer) + `docker compose exec nginx nginx -s reload`.

**B) Owner-provided cert (common for Iranian CAs / internal CAs).**
- Place the owner's `fullchain.pem` + `privkey.pem` into the `certs` volume with
  `600` perms on the key.

Either way: the **private key never enters git** (`.gitignore` blocks
`deploy/nginx/certs/` and `*.pem`/`*.key`).

---

## 5. First deploy

```sh
cd halqe

# 5.1 sanity-check the compose file + .env interpolation (no containers start)
docker compose config

# 5.2 build the app image (from the repo-root context)
docker compose build

# 5.3 bring up postgres → app → nginx
docker compose up -d
```

What happens on `up`:
1. `postgres` starts; its `healthcheck` (`pg_isready`) gates everything else.
2. `app` waits for `postgres` to be **healthy**, then `entrypoint.sh`:
   - polls the PG port (safety net),
   - runs **`apply_schema`** (idempotent DDL slices — the schema is applied here,
     there is no separate migration step),
   - runs **`ensure_app_role`** (creates/refreshes the least-privilege LOGIN role),
   - `exec gunicorn` on `0.0.0.0:8000`.
3. `nginx` starts and fronts the app on `443`/`80`.

Verify:
```sh
docker compose ps                       # all healthy
docker compose logs -f app              # watch apply_schema → gunicorn
curl -fsS https://api.halqe.ir/healthz  # {"status":"ok"}
curl -fsS https://api.halqe.ir/readyz   # {"status":"ready"} (200) — DB reachable
curl -I  http://api.halqe.ir/           # 301 → https
```

---

## 6. Staging first

**Do not make production the first thing you bring up.** Stand up a **staging**
stack identically (same compose, a separate `.env` with `PRODUCTION=1`, a staging
hostname, and self-signed or staging certs). Exercise:
- login → JWT → a staff endpoint,
- the public card (`/api/v1/card/{token}`) + self-report
  (`/api/v1/patient-report/{token}`), confirming **429** kicks in under a burst
  (the nginx `limit_req` boundary — §8),
- a backup + a **restore drill** (§7),
- the production boot guards (§3) by deliberately breaking `.env` once.

Only promote to production after staging is green. Use distinct volumes/passwords
for staging vs production — never share a DB.

---

## 7. Backups — schedule + before every deploy

Backup tooling is step 54 (`scripts/backup.sh`, `restore.sh`, `restore_drill.sh`),
fully documented in [`backup_restore.md`](backup_restore.md). Dumps contain **PHI**
— keep them `600`, off-box, and out of git (already enforced in `.gitignore`).

**Scheduled backups (owner — pick one):**

- **Host cron (recommended).** A line on the VPS host:
  ```cron
  # nightly 03:15 Tehran — dump + retention into the shared backups location
  15 3 * * *  cd /srv/halqe/halqe && PG_DB=halqe_app BACKUP_DIR=/srv/halqe/backups BACKUP_KEEP=14 \
               PGUSER=$PG_USER PGPASSWORD=$PG_PASSWORD bash scripts/backup.sh >> /var/log/halqe-backup.log 2>&1
  ```
  (Source the same creds the compose `.env` uses; the script reads `PG*`/`PG_*`.)

- **The compose `backup` service** (for hosts where host cron is inconvenient):
  ```sh
  docker compose --profile backup up -d backup   # dumps to the `backups` volume on a loop
  ```
  It reads `PG_USER`/`PG_PASSWORD`/`PG_DB` + `BACKUP_KEEP` from `.env`, runs
  `scripts/backup.sh` every `BACKUP_EVERY` seconds (default 24h), reaching
  `postgres` over the internal network.

**Prove backups are restorable (run periodically + after major changes):**
```sh
SOURCE_DB=halqe_app bash scripts/restore_drill.sh   # builds → dumps → restores → verifies → drops
```

**⚠️ Backup BEFORE every deploy.** The first thing any upgrade/redeploy does:
```sh
PG_DB=halqe_app BACKUP_DIR=/srv/halqe/backups bash scripts/backup.sh
```
Note the resulting `halqe-halqe_app-YYYYMMDD-HHMMSS.dump` filename — that is your
rollback point (§8).

---

## 8. Rollback

The schema is applied **additively** by `apply_schema` (idempotent slices), so
most app upgrades are forward-compatible. Rollback has two parts:

**8.1 Roll back the app image** (no data change):
```sh
# pin to the previous image/tag (or previous git checkout) and re-up just the app
docker compose up -d --no-deps app
# or, if you tag images per release:
#   IMAGE_TAG=<previous> docker compose up -d --no-deps app
```

**8.2 Restore the database** (only if a release corrupted/changed data — and only
after a fresh **backup of the current state** so the rollback is itself reversible):
```sh
# 1) take a safety dump of the CURRENT (bad) state first
PG_DB=halqe_app BACKUP_DIR=/srv/halqe/backups bash scripts/backup.sh

# 2) restore the pre-deploy dump into a NEW db, verify, then cut over
scripts/restore.sh /srv/halqe/backups/halqe-halqe_app-<pre-deploy-ts>.dump halqe_app_restored --create
#    restore.sh has a denylist (halqe_app / _test / postgres / template*) and a
#    non-empty-DB guard so it cannot silently clobber the live DB. See backup_restore.md.
```
Then point the app at the restored DB (rename/swap `PG_DB`) and re-up. Keep the
bad-state dump until you have confirmed the rollback is healthy.

**Rollback validation:** `/readyz` returns 200, login works, a known patient card
renders, `restore_drill.sh` passes.

---

## 9. SMS stays OFF (owner gate)

Real SMS is **off by default** and must stay off until the owner completes
Kavenegar KYC and explicitly flips the second gate. See
[`sms_go_live.md`](sms_go_live.md).

- `SMS_LIVE_ENABLED=false` in `.env` — keep it false. A configured
  `KAVENEGAR_API_KEY` alone is **not** enough to send; the live flag is a second,
  explicit gate.
- The Kavenegar account currently returns **code 430** (KYC incomplete) — no real
  sends are possible regardless. This is a known operational gate, not a bug.
- Only after owner KYC **and** an explicit decision: set `SMS_LIVE_ENABLED=true`
  (+ a valid key) and redeploy. Until then the system simulates via NullProvider.

---

## 10. Go-live checklist

Tick every box before declaring production live:

- [ ] **`docker compose config` parses** with the production `.env` (no
      unresolved interpolation, no syntax error).
- [ ] **Production boot guards pass** (§3): `PRODUCTION=1`, strong `SECRET_KEY`,
      explicit `ALLOWED_HOSTS` (no `*`), `DEBUG` off, CORS from env. (Verify the
      app container is **healthy**, not crash-looping.)
- [ ] **8000 / 5432 are NOT reachable from the internet** — only `443`/`80` via
      nginx. Confirm with an external port scan.
- [ ] **TLS works**: `https://<host>/healthz` is 200, `http://` 301-redirects,
      cert is valid, TLS1.2+ only.
- [ ] **nginx `limit_req` is active**: a burst on `/api/v1/card/` and
      `/api/v1/patient-report/` returns **429** (the real per-IP boundary,
      step 66). `X-Forwarded-For` sent by a client does **not** change the
      rate-limit key (real_ip overwrites it).
- [ ] **`/readyz` is 200** (primary DB reachable; app role works).
- [ ] **Backups scheduled** (host cron or the `backup` service) **and** a
      `restore_drill.sh` has PASSED on this host.
- [ ] **A pre-deploy backup exists** and its filename is recorded as the rollback
      point.
- [ ] **`SMS_LIVE_ENABLED=false`** (stays false until owner KYC — §9).
- [ ] **Accounting boundary is read-only** — the app role has `SELECT`-only on
      `accounting.*` (enforced by `ensure_app_role` GRANTs, not just code). No
      write path to accounting is introduced by the deploy.
- [ ] **Owner gates acknowledged:** R1/R3 (per ROADMAP), VPS provisioning, TLS
      certs, DNS, and the backup cron are owner-owned and signed off.

---

## 11. Serving the web (Next.js — separate)

The front-end (`halqe/web/`) is a **separate Next.js app** and is **not** part of
this compose stack. It reads the API base from `NEXT_PUBLIC_API_BASE` (see
`web/src/lib/api/_core.ts`). Two supported models:

1. **Separate deployment (recommended):** build + run the web on its own host
   (`npm run build` → `npm start`, or a static export behind any static host),
   with `NEXT_PUBLIC_API_BASE=https://api.halqe.ir/api/v1`. Add that origin to
   `CORS_ALLOWED_ORIGINS` in the API's `.env`.
2. **Colocate later (optional):** front the web behind the same nginx under a
   **different hostname** (e.g. `app.halqe.ir`) with its own `server {}` block and
   a `web` upstream — see the commented sketch at the bottom of `halqe.conf`. Do
   **not** mix it into the `api.halqe.ir` server block.

Keeping them separate keeps the API server block (and its rate-limit boundary)
focused and simple.

---

## 12. Operational notes

- **Logs:** `docker compose logs -f app` (gunicorn access/error to stdout; JSON
  key=value format in production — see `config/settings.py` LOGGING).
- **Restart a service:** `docker compose restart app` (Python changes need a full
  app restart — the schema bootstrap is gated on a per-process flag).
- **Apply new schema slices:** they are applied automatically by `apply_schema`
  on the next `app` start (idempotent). Back up first (§7).
- **Reload nginx after cert renewal:** `docker compose exec nginx nginx -s reload`.
- **Never** `docker compose down -v` in production — `-v` deletes the named
  volumes (`pgdata`, `backups`). Use `down` without `-v`.

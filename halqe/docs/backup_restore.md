# halqe — Backup & Verified Restore (Postgres)

Logical-dump backups of the halqe Postgres database (the single DB that holds all
three namespaces — `platform`, `accounting`, `clinical`) plus a **verified restore
drill** that proves a dump is actually restorable. Built in step 54 (cluster M).

> halqe runs on Postgres. The two legacy Flask apps (`webapp`, `specialist_clinic`)
> use a weekly SQLite **file-copy** daemon — that mechanism does **not** apply here.
> Postgres needs `pg_dump`/`pg_restore`-based logical dumps (this doc) and, later,
> WAL archiving for PITR (see the PITR-ready note below).

---

## TL;DR

```sh
# nightly on the VPS (cron) — dump + retention
PG_DB=halqe_app BACKUP_DIR=/srv/halqe/backups BACKUP_KEEP=14 scripts/backup.sh

# prove the latest backups are restorable (creates+drops a throwaway DB)
SOURCE_DB=halqe_app scripts/restore_drill.sh

# disaster recovery into a fresh DB
scripts/restore.sh /srv/halqe/backups/halqe-halqe_app-YYYYMMDD-HHMMSS.dump halqe_app_new --create
```

All three scripts read connection info **from the environment** — no credentials are
ever hardcoded. See "Connection" below.

---

## The scripts (`halqe/scripts/`)

| Script | Purpose |
|--------|---------|
| `_pg_env.sh` | Sourced helper. Resolves connection settings from env and exports the standard `PG*` libpq vars. **Not run directly.** |
| `backup.sh` | `pg_dump -Fc` (custom format: compressed + selective restore) into `${BACKUP_DIR}`, Tehran-timestamped filename, sha256 sidecar, retention pruning. |
| `restore.sh` | `pg_restore` a dump into an explicit target DB, with a denylist + non-empty-DB guard so it can't silently clobber prod. |
| `restore_drill.sh` | The **proof**: dump → throwaway DB → restore → verify schema_version + key tables → drop throwaway → non-zero exit on any failure. |

### Connection (no hardcoded secrets)

`_pg_env.sh` resolves each setting in this precedence (first non-empty wins):

1. Standard **libpq** vars: `PGHOST` `PGPORT` `PGUSER` `PGPASSWORD` `PGDATABASE`
2. `DATABASE_URL` (`postgres://user:pass@host:port/dbname`) — parsed if set
3. Project vars (same names halqe's `config/settings.py` / `.env` use):
   `PG_HOST` `PG_PORT` `PG_USER` `PG_PASSWORD` `PG_DB`

The password is only ever exported as `PGPASSWORD` for libpq tools — it is never
echoed. On the VPS, prefer a **`~/.pgpass`** file (mode 0600) or a systemd
`EnvironmentFile=` over inline env so the password never appears in `ps`/shell
history.

---

## backup.sh — take a dump

```sh
scripts/backup.sh                 # dump $PGDATABASE (or PG_DB)
scripts/backup.sh halqe_app       # dump a specific DB (first positional arg)
BACKUP_DIR=/srv/halqe/backups BACKUP_KEEP=14 scripts/backup.sh
```

- **Format:** custom (`-Fc`) — compressed, and supports **selective** restore
  (`pg_restore -t / -n`) if you ever need a single table/schema back.
- **Flags:** `--no-owner --no-privileges` so the dump restores cleanly into any
  cluster regardless of which roles exist there.
- **Filename:** `halqe-<dbname>-YYYYMMDD-HHMMSS.dump` in **Tehran local time**
  (`TZ=Asia/Tehran`), regardless of the host OS timezone — consistent with the
  project's Iran-local-time convention.
- **Integrity:** writes a `<dump>.sha256` sidecar; `restore.sh`/`restore_drill.sh`
  verify it before restoring.
- **Permissions:** the backups dir is `chmod 700`, each dump `chmod 600`
  (best-effort) — dumps contain PHI.
- **Retention:** keeps the last `BACKUP_KEEP` (default **7**) dumps **for that DB
  name**, pruning older ones (and their sidecars). Pruning only ever touches files
  matching `halqe-<dbname>-*.dump` — nothing else in the directory is at risk.

**Where dumps live (VPS):** `/srv/halqe/backups` (recommended) — an encrypted,
access-restricted volume. See SECURITY below.

---

## restore.sh — manual restore (disaster recovery)

```sh
scripts/restore.sh <dump-file> <target-db> [--create] [--force]
```

Safety guards (so you never clobber the wrong DB):

- The **target DB name is a required explicit argument** — there is no default.
- A **denylist** refuses `postgres`, `template0/1`, `halqe_app`, `halqe_app_test`
  unless you pass `--force`. (Restoring over the live DB should be a conscious act.)
- If the target **exists and is non-empty**, it refuses unless `--create`
  (drop+recreate) or `--force` (restore on top) is given.
- It **verifies the sha256 sidecar** (if present) before restoring; a mismatch
  aborts.

Typical disaster-recovery flow — restore into a **new** DB, verify, then cut over:

```sh
scripts/restore.sh /srv/halqe/backups/halqe-halqe_app-20260627-031500.dump \
    halqe_app_restored --create
# inspect halqe_app_restored, confirm platform.schema_version + row counts,
# then rename/point the app at it.
```

---

## restore_drill.sh — the verified-restore PROOF

This is what makes the backups trustworthy: a backup you've never restored is a
hope, not a backup.

```sh
SOURCE_DB=halqe_app scripts/restore_drill.sh         # dump SOURCE_DB, then verify
scripts/restore_drill.sh --dump <existing.dump>      # verify an existing dump
```

What it does (fully automated, idempotent, self-cleaning):

1. Take a fresh dump of `SOURCE_DB` (or use `--dump <file>`).
2. Create a **throwaway** DB — default `halqe_restore_drill`. The name is
   **hard-guarded to end in `drill`** and rejected if it matches any real/test DB,
   so the drill can never write to prod.
3. `pg_restore --exit-on-error` into the throwaway.
4. **Verify** against the **schema-version anchor** and key tables:
   - `platform.schema_version` exists and has `>= MIN_SCHEMA_ROWS` rows (this is the
     `apply_schema` ledger added in step 67 — the canonical "schema fully applied"
     marker), and prints the latest recorded slice;
   - `platform.tenants`, `accounting.patients`, `clinical.patient_links` all exist
     (one table per namespace), with sane row-count checks.
5. **Drop** the throwaway DB (always — via an EXIT trap, even on failure).
6. **Exit non-zero** if any check fails.

### Actual drill output (step-54 acceptance run, Docker `halqe_pg_validate`, PG 16.10)

```
============================================================
 halqe RESTORE DRILL
   source DB : postgres@localhost:5432/halqe_drill_src
   drill  DB : halqe_restore_drill (throwaway)
============================================================
==> dumping halqe_drill_src → /tmp/halqe-drill-XXXX.dump
    dump bytes: 301883
==> creating throwaway DB 'halqe_restore_drill'
==> restoring into 'halqe_restore_drill'
==> verifying restored DB
    [ OK ] platform.schema_version: 20 slice(s) recorded (>= 1)
           latest slice in ledger: schema_pg_slice9_population_thresholds.sql
    [ OK ] table exists: platform.tenants
    [ OK ] table exists: accounting.patients
    [ OK ] table exists: clinical.patient_links
    [ OK ] platform.tenants row count: 1 (>= 1)
    [ OK ] accounting.patients=2  clinical.patient_links=2 (readable)
------------------------------------------------------------
 DRILL RESULT: PASS — dump taken, restored, and verified.
------------------------------------------------------------
==> cleanup: dropping throwaway DB 'halqe_restore_drill'
EXIT CODE: 0
```

A negative run (dump of an empty DB) correctly fails all six checks and exits 1 —
the verification is real, not a rubber stamp.

**Run the drill regularly** (e.g. weekly cron, or after every schema change) so a
broken backup is caught immediately, not during an outage.

---

## Retention & schedule (recommended)

- **backup.sh** nightly via cron, `BACKUP_KEEP=14` (two weeks of nightlies).
- **restore_drill.sh** weekly via cron — alert if it exits non-zero.
- Keep an **off-box copy** (a backup that only exists on the same VPS does not
  survive that VPS dying). Sync the encrypted dumps to a second location.

---

## PITR-ready note (future upgrade)

Logical dumps (this doc) are the **baseline** — they give you a consistent
point-per-dump recovery (you lose changes since the last nightly). The future
upgrade to **point-in-time recovery (PITR)** is a server-level concern, not these
scripts:

- Set `wal_level = replica` (or higher) and `archive_mode = on`.
- Set an `archive_command` that ships each completed WAL segment to durable,
  off-box storage (e.g. `pgBackRest`, `wal-g`, or a plain `cp`/`rsync` to an
  encrypted archive).
- Take a periodic `pg_basebackup` and keep the WAL stream; recover to any moment by
  replaying WAL up to a `recovery_target_time`.

PITR belongs to the **step-55 VPS runbook** (it needs a configured Postgres server
+ archive storage, which only exist on the real VPS). Until then, nightly logical
dumps + the weekly verified drill are the recovery guarantee. `pgBackRest` is the
recommended tool when PITR is enabled — it does both base backups and WAL archiving
with built-in encryption and retention.

---

## SECURITY — dumps contain PHI (owner/ops gate)

**A halqe dump is a full copy of patient data (`accounting.patients` demographics,
`clinical.*` vitals/meds/notes). Treat every `.dump` as PHI.**

- **Never commit dumps to git.** `halqe/.gitignore` ignores `backups/`, `*.dump`,
  and `*.dump.sha256`. Verify with `git status` after any backup run.
- **Encrypt at rest.** On the VPS, store dumps on an **encrypted volume** (LUKS /
  cloud-provider disk encryption) and/or encrypt each dump (`age`/`gpg`) before it
  leaves the box. The scripts produce plaintext custom-format dumps; encryption is
  an ops wrapper around them.
- **Restrict access.** `backups/` is `chmod 700`, dumps `chmod 600`. Only the
  backup/ops user should be able to read them. No world-readable backup dirs.
- **Off-box copies must also be encrypted** and access-controlled.
- **Credentials never in git.** Scripts read connection info from env; on the VPS
  use `~/.pgpass` (0600) or a systemd `EnvironmentFile`, not inline shell.

> **OWNER / OPS GATE (blocks step 55 go-live):** before halqe holds real patient
> data on a VPS, the owner must decide and provision: (1) where encrypted dumps
> live, (2) the at-rest encryption mechanism, (3) the off-box copy target, and
> (4) who may access them. This is a data-trust decision (ADR-0006 trust model),
> not something the scripts can satisfy alone.

---

## Hooking into the step-55 VPS runbook (compose / cron)

The scripts are **infrastructure-agnostic** — they only need `pg_dump`/`pg_restore`
on `PATH` and connection env. They do **not** require docker-compose. When step 55
lands the real VPS deploy (Nginx + HTTPS + compose), wire backups in as follows
(no code change needed here):

- **Cron (simplest):** on the host or in a small sidecar, schedule
  `scripts/backup.sh` nightly and `scripts/restore_drill.sh` weekly, with
  `BACKUP_DIR` pointed at the encrypted backups volume and `PG_*`/`DATABASE_URL`
  from the deploy's env file.
- **docker-compose:** add a `backup` service (or a cron sidecar) that mounts the
  scripts read-only and a named **encrypted volume** at `BACKUP_DIR`, sharing the
  Postgres service's connection env. There is **no `docker-compose.yml` in the repo
  yet** — it is part of step 55; this is where the backup service/volume hooks in.
- The container's `entrypoint.sh` already runs `apply_schema` (which populates
  `platform.schema_version`), so the drill's verification anchor is guaranteed to
  exist on a freshly-deployed DB.

Cross-reference: **step 55** (VPS deploy / runbook) and **step 67** (the
`platform.schema_version` ledger this drill verifies against).

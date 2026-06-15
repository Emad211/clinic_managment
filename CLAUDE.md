# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⛳ دستور همیشگی — اول از همه بخوان · STANDING RULE: read before ANY task

**دستور اولِ کاربر (always, every task):** پیش از شروع هر کاری در این پروژه، ابتدا **هر ۳ منبع** را بخوان و مبنا قرار بده —
1. **مموری (Memory):** `~/.claude/projects/.../memory/MEMORY.md` و فایل‌های مموریِ مرتبط — چه‌کسی/چه/چرا که در کد نیست.
2. **CLAUDE.md:** همین فایل + نزدیک‌ترین CLAUDE.md به محلِ کار (مثل [`specialist_clinic/CLAUDE.md`](specialist_clinic/CLAUDE.md)) — قوانین معماری و «کد چطور کار می‌کند».
3. **گراف دانشِ graphify:** گرافِ همان اپ/پوشه‌ای که در آن کار می‌کنی، مثل [`specialist_clinic/graphify-out/GRAPH_REPORT.md`](specialist_clinic/graphify-out/GRAPH_REPORT.md) و `graph.json` — نقشهٔ نود/جامعه/god-node. برای پرسش `/graphify query "…"`؛ اگر اپی هنوز گراف ندارد با `/graphify` بساز.

فقط بعد از خواندن این سه شروع کن. `MEMORY.md` و `CLAUDE.md` خودکار لود می‌شوند، اما `GRAPH_REPORT.md` را باید صریحاً Read کنی. اگر کد به‌طور معنادار تغییر کرد، گراف را با `/graphify --update` تازه کن.

---

## What this repository is

Two **independent Flask + SQLite desktop apps** for an Iranian clinic. They share the same architecture and conventions but run as separate processes on different ports with different databases. They are linked only by patient `national_id`, through a strictly **read-only** bridge.

| App | Path | Purpose | Port | Database |
|-----|------|---------|------|----------|
| **Hesabdari (Accounting)** | `webapp/` | Reception, invoicing, visits, injections, procedures, consumables, payroll, reports | 8080 | `webapp/clinic_new.db` |
| **Specialist Clinic** | `specialist_clinic/` | Chronic-disease management (diabetes, hypertension): vitals, appointments, follow-up worklist, SMS campaigns, ADA clinical decision support | 8090 | `specialist_clinic/specialist.db` |

`specialist_clinic` reads patient demographics and revenue **live and read-only** from the accounting DB via `specialist_clinic/src/adapters/accounting_bridge.py` (opens `clinic_new.db` with the sqlite3 URI `mode=ro`). **Never write to the accounting DB from the specialist app.** The path defaults to `../webapp/clinic_new.db` and is overridable with the `ACCOUNTING_DB_PATH` env var.

Most domain comments and UI strings are Persian. The product is RTL/Jalali throughout.

> **Project scope note:** this repo currently holds exactly these two apps. Earlier exploratory trees (`platform/`, `ai_service/`, `docs/`) were intentionally removed and are **not** part of the project — do not resurrect them from git history or describe them as if they exist.

## Per-app deep docs

[`specialist_clinic/CLAUDE.md`](specialist_clinic/CLAUDE.md) is the authoritative guide for the Specialist Clinic app (its layering, the ADA clinical engine, the `patient_links` model, conventions, gotchas). Read it before working there. `webapp/` follows the same conventions described below but has no separate CLAUDE.md yet.

## Running

**Specialist Clinic** (known-good venv, Python 3.13):
```powershell
cd specialist_clinic
.\.venv\Scripts\python.exe start.py        # http://127.0.0.1:8090 — login admin/admin
```

**Accounting** (`webapp`):
```powershell
cd webapp
python start.py                            # http://127.0.0.1:8080  (or run.bat)
```
Both `start.py` scripts open a browser tab after ~1.5s and run with `debug=False`, `use_reloader=False`. Use a system Python or a fresh venv for `webapp`; `specialist_clinic/.venv` is the known-good interpreter for the specialist app.

### Seeding / CLI
- `specialist_clinic`: `.\.venv\Scripts\python.exe seed_demo_data.py` — idempotent seed of **10 demo patients** (`TEST0001..TEST0010`) with ~2 years of vitals/meds/flags. **Use these for all dev/testing.**
- `webapp`: `flask --app src.app init-db` and `flask --app src.app create-user <username> <password> [role]`; helper scripts under `webapp/scripts/`.

### Tests
There is **no automated test suite** in either app — verify changes by exercising the running app. Both `create_app` factories accept a `test_config`/`TestConfig` with `DATABASE_PATH=':memory:'`.

### Building the .exe (PyInstaller)
Each app ships as a single Windows `.exe` that creates its DB and `backups/` next to the executable.
- `webapp`: `pyinstaller HesabdariSib.spec` (bundles `src/templates`, `src/static`, `schema.sql`).
- `specialist_clinic`: see the `pyinstaller` command in `specialist_clinic/README.md`; pass `ACCOUNTING_DB_PATH` to point the build at the real accounting DB.

Both `create_app` factories detect frozen mode via `sys.frozen` / `sys._MEIPASS`. Keep that dual source/frozen path handling intact when touching app/config bootstrap or adding bundled data files (and update the PyInstaller `datas`/command, or the file will be missing from the `.exe`).

## Shared architecture & conventions

Both apps use the same strict layering — respect it when adding features:

```
src/api/        Flask Blueprints — routes, request/response, auth checks only
src/services/   Business logic (the only place rules/calculations live)
src/adapters/sqlite/   Repositories — all SQL lives here; one repo per aggregate
src/domain/ or dataclasses   Plain domain models (where present)
src/common/     Cross-cutting utils: jalali.py, utils.py, validators.py
src/config/settings.py   Config (DB path, ports, backup folder)
```

A route calls a service; a service calls a repository. **Do not put SQL in routes or services** — add/extend a repo in `src/adapters/sqlite/`.

- **No migration framework.** `src/adapters/sqlite/schema.sql` is the source of truth and is applied on first connection (idempotent via `IF NOT EXISTS` / `INSERT OR IGNORE`). Schema changes to existing DBs are made with **additive runtime migrations** (an `_ensure_column(...)`/`_run_migrations` call in `core.py`) that must be safe to re-run. Never assume a fresh DB.
- **Jalali dates everywhere.** Conversion via `src/common/jalali.py` + `utils.py`, exposed as Jinja filters. UI date inputs are Jalali (`YYYY/MM/DD`) and converted to Gregorian server-side before storage. Persian digits via a `fa_num` filter.
- **Iran local time (UTC+3:30).** Timestamps are stored as Tehran local time via `utils.iran_now()` (OS-timezone-independent) or SQLite `datetime('now','+3 hours','+30 minutes')`. Never introduce naive `datetime.now()` / UTC timestamps.
- **Auth & roles.** Passwords use `bcrypt`; legacy `werkzeug` hashes migrate to bcrypt on successful login. After **5 failed attempts the account locks for 15 minutes**. `webapp` roles: `manager` / `reception` / `doctor`. `specialist_clinic` roles: `manager` / `staff` (login `admin/admin`); it has both `login_required` and `manager_required` decorators.
- **Activity logging.** Log new state-changing actions into the `activity_logs` table via each app's activity logger.
- **Automatic backups.** A daemon thread copies the DB weekly into `backups/`, keeping the last few. Started from `create_app` unless `TESTING`.

`webapp/clinic_new.db` **is committed to git** (it carries real seeded data) — be deliberate about committing changes to it. `specialist.db` is not tracked.

When working in `specialist_clinic/`, follow [`specialist_clinic/CLAUDE.md`](specialist_clinic/CLAUDE.md) for that app's specifics (the ADA rule engine, `patient_links`, the read-only bridge, threshold-sync rule).

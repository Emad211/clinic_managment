# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project vision & North Star (read this first)

This repo is the **seed of a larger Iranian medical-software startup**, not just two clinic apps. The full product strategy, market research, positioning, roadmap, and the knowledge-pipeline architecture live in **[`docs/`](docs/README.md)** — start at [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) (strategy & roadmap), [`docs/TECH_STACK.md`](docs/TECH_STACK.md) (the locked target stack), and [`docs/MARKET_RESEARCH.md`](docs/MARKET_RESEARCH.md). Treat `docs/` as the source of truth for *why* and *what next*; treat this file as the source of truth for *how the current code works*.

**Heads-up on the stack:** the two apps documented below are the *current* state (Flask + SQLite desktop). The *target* is a cloud multi-tenant SaaS on **Django + django-ninja + PostgreSQL** (see `docs/TECH_STACK.md`), reached by **evolving** the existing layered code — keep `services/`+`domain/` (incl. the ADA engine), swap SQLite→Postgres and Flask→Django, unify the two apps into modules — **not** rewriting from scratch. Don't assume Flask/SQLite is the end-state.

The strategy is a **3-rung ladder** (decided خرداد۱۴۰۵):
1. **Revenue wedge (now):** turn `specialist_clinic` into a sellable **chronic-disease co-pilot** (diabetes/HTN) + add **e-prescription/insurance integration** — this hits a real market gap no Iranian clinic-software competitor fills.
2. **Differentiation:** generalize the ADA rule engine (`rule_engine.py` + `clinical_rules`) into a **physician-facing clinical-intelligence layer** inside the clinic product (lower regulatory risk than a consumer diagnosis app).
3. **Long-term moat:** a **clinical-knowledge platform** (education → diagnostic reasoning → treatment assistant) powered by a multi-agent **knowledge-extraction pipeline** (Phase-0), built in parallel and fed by the proprietary Iranian patient data the clinic product accumulates.

Safety/legal principle baked into every clinical feature: **the system suggests, it does not decide** ("پیشنهاد — تأیید با پزشک"), gated to licensed users, with logged disclaimers. See `docs/MASTER_PLAN.md` §4.4.

## Repository layout: two independent apps

This repo holds **two separate Flask + SQLite desktop apps** for an Iranian clinic. They share the same architecture and conventions but run as different processes on different ports with different databases. They are linked only by patient `national_id` through a strictly read-only bridge.

| App | Path | Purpose | Port | Database |
|-----|------|---------|------|----------|
| **Hesabdari (Accounting)** | `webapp/` | Reception, invoicing, visits, injections, procedures, consumables, payroll, reports | 8080 | `webapp/clinic_new.db` |
| **Specialist Clinic** | `specialist_clinic/` | Chronic-disease management (diabetes, hypertension): vitals tracking, appointments, follow-up worklist, SMS campaigns, ADA clinical decision support | 8090 | `specialist_clinic/specialist.db` |

`specialist_clinic` reads patient demographics and revenue **live and read-only** from the accounting DB via `specialist_clinic/src/adapters/accounting_bridge.py` (opens `clinic_new.db` with `sqlite3` URI `mode=ro`). **Never write to the accounting DB from the specialist app** — the bridge is intentionally read-only and any write must stay impossible. The path defaults to `../webapp/clinic_new.db` and is overridable with the `ACCOUNTING_DB_PATH` env var.

Most domain comments and UI strings are in Persian. The product is RTL/Jalali throughout.

**Emerging third tree — `platform/` (the Evolve target, do not confuse with the Flask apps):** a separate **Django + django-ninja + PostgreSQL** project that is the cloud SaaS destination per `docs/TECH_STACK.md` + `docs/DATA_MODEL.md`. It is **additive and isolated** — building it never touches `webapp/` or `specialist_clinic/` (still on 8080/8090). Current state: **v0.18 scaffold (full SaaS loop; RLS proven; deployable; RTL/Jalali UI)** — all 8 modules from `docs/DATA_MODEL.md` §2 modelled (`common`/`identity`/`billing`/`patients`/`chronic`/`rx`/`accounting`/`messaging`, ~40 models), PostgreSQL **RLS multi-tenancy** wired across every tenant table (per-request `SET LOCAL app.current_clinic` + `tenant_isolation` policies, deny-by-default; `plan`/`drug` are global no-RLS reference tables; the GUC no-ops off PostgreSQL so it also runs on SQLite for dev), django-ninja API (`/api/health`, `/api/auth`, `/api/patients`, `/api/chronic`) with **session login/logout/me** (bcrypt + 5-fail/15-min lockout, RLS-correct ordering) and **authz-guarded data routers** (`common.auth.SessionAuth`), management commands: `etl_catalog` (ports the **real full ADA engine** from `specialist.db` — 57 rules/13 indicators/18 flags/19 drug classes/5 conditions; catalog models mirror the specialist schema 1:1 so no clinical fields are lost), `seed_catalog` (minimal fresh-install fallback, **mutually exclusive** with etl_catalog — keep thresholds in sync with `specialist_clinic` THRESHOLDS/TARGETS), `bootstrap_clinic`, and `etl_import` (legacy webapp+specialist SQLite → one tenant: users + patients merged by national_id + **per-patient chronic records** vitals/meds/conditions/flags/followups via a `patient_links.id→Patient` map; run `etl_catalog` first; source DBs read-only). The **ADA rule engine is ported** to `apps/chronic/rule_engine.py` (pure `trigger_json` DSL evaluator + ORM `build_facts`) and surfaced at `GET /api/chronic/suggestions` (suggestion-only). End-to-end verified on the **real** legacy data: TEST0008 → 22 suggestions from real vitals. A **server-rendered web frontend** (`apps/web/`, RTL Django templates) makes it demoable. Login lands on `/dashboard/` (clinic-at-a-glance KPIs + overdue preview + subscription status), then the three core chronic workflows: `/patients/<id>/` (One-Page Snapshot + grouped ADA suggestions, each with a physician **acknowledge** action → append-only `SuggestionLog`, the "suggests, physician decides, logged" safety principle) and `/worklist/` (recall/follow-up worklist split overdue/today/upcoming, mark-done). The **e-prescription** workflow (Epic 1, WebView bridge: compose → open insurer portal → record tracking code → register, with `InsurerLog` audit) is in `apps/web` + `apps/rx`. **RLS tenant isolation is proven on real PostgreSQL** via `manage.py verify_rls` (deny-by-default, A/B isolation, cross-tenant write rejection; no-op on SQLite — run it against prod Postgres before launch). **Deployment artifacts** exist: `Dockerfile` (gunicorn + WhiteNoise, Iran pip/image mirror build-args), `docker-compose.yml`, and `deploy/db-init.sql` + `entrypoint.sh` enforcing the **RLS-correct DB-role split** — the app runs as a NOBYPASSRLS `clinic_app` role while migrations/seeding use a privileged role (or RLS is silently bypassed). **SMS reminders** (Epic 6) go through `apps/messaging/services.py` (Mediana + NullProvider fallback + compliance rewrite); the worklist has a per-row 📲 reminder action. Root `.gitlab-ci.yml` runs a `pytest` job (25 tests on in-memory SQLite via `config/settings_test`) + `check`+`migrate`+`verify_rls` on every push. **Unlike the Flask apps, `platform/` HAS an automated test suite** (`platform/tests/`, `conftest.py` fixtures) — run `python -m pytest` from `platform/`. **SaaS subscription billing** (Epic 0) goes through `apps/billing/services.py` (ZarinPal v4 with a SimulatedGateway dev fallback; `seed_plans`; `/billing/` UI) — subscribe → pay → activate Subscription. `manage.py check` clean. Its own venv (`platform/.venv`, Python 3.13) and `platform/requirements.txt`. See `platform/README.md`. When working in `platform/`, follow Django conventions there, not the Flask `src/api|services|adapters` layering of the two desktop apps.

**Fourth tree — `ai_service/` (Phase-0 knowledge pipeline, ladder rung 3):** a **separate FastAPI + arq** service (its own `.venv`, `requirements.txt`, `pytest`) that turns authoritative guidelines into a queryable clinical-knowledge graph (architecture in `docs/PIPELINE.md`). Kept apart from Django so the LLM workload/cadence doesn't destabilise the clinic app; its `knowledge` data has **no RLS** (global knowledge, not per-tenant). Current state: **M1** — Model Gateway (AvalAI + NullModel fallback), Ingestion/Registry (content-hash dedup), data model (SourceDocument/DocumentChunk/Claim), FastAPI `/health`+`/ingest`, 8 tests green. See `ai_service/README.md`.

## Running

**Specialist Clinic** (working venv with Python 3.13):
```powershell
cd specialist_clinic
.\.venv\Scripts\python.exe start.py        # http://127.0.0.1:8090 — login admin/admin
```

**Accounting** (`webapp`):
```powershell
cd webapp
python start.py                            # http://127.0.0.1:8080  (or run.bat)
```
Both `start.py` scripts open a browser tab after ~1.5s and run with `debug=False`, `use_reloader=False`.

**Important venv caveat:** `webapp/.venv` is broken (built against a since-deleted miniconda) — do not rely on it; use a system Python or a fresh venv for `webapp`. `specialist_clinic/.venv` (Python 3.13) is the known-good interpreter and is what `.claude/launch.json` points at.

### Dependencies
- `specialist_clinic/requirements.txt` is complete: `Flask`, `bcrypt`, `jdatetime` (SMS uses only stdlib `urllib`).
- `webapp/requirements.txt` lists `flask`, `jdatetime`, `pytest` but is **incomplete** — `webapp` also imports `bcrypt` and `werkzeug` at runtime (`src/services/auth_service.py`). Install those too.

### Tests
`pytest` is declared in `webapp/requirements.txt` but **there are currently no test files** in the repo. There is no test suite to run; verify changes by exercising the app. The Flask factories accept a `test_config` with `TestConfig` (`DATABASE_PATH=':memory:'`).

### CLI / seeding
- `webapp`: `flask --app src.app init-db` and `flask --app src.app create-user <username> <password> [role]` (registered in `webapp/src/app.py`). Helper scripts: `webapp/scripts/create_doctor_user.py`, `webapp/scripts/seed_clinic_data.py`.
- `specialist_clinic`: `.\.venv\Scripts\python.exe seed_demo_data.py` — idempotent seed of **10 demo patients** (national IDs `TEST0001..0010`) with 2 years of vitals/meds/flags spanning diverse clinical profiles. **Use these patients for all dev/testing.**

### Building the .exe (PyInstaller)
Both apps ship as a single Windows `.exe` that creates its DB and `backups/` next to the executable.
- `webapp`: `pyinstaller HesabdariSib.spec` (bundles `src/templates`, `src/static`, and `schema.sql`).
- `specialist_clinic`: see the `pyinstaller` command in `specialist_clinic/README.md`; pass `ACCOUNTING_DB_PATH` to point the build at the real accounting DB.

Both `create_app` factories detect frozen mode via `sys.frozen` / `sys._MEIPASS` and resolve `templates/`, `static/`, and `schema.sql` accordingly. Keep that dual source/frozen path handling intact when touching app/config bootstrap or adding bundled data files.

## Architecture

Both apps use the same strict layering — respect it when adding features:

```
src/api/        Flask Blueprints — routes, request/response, auth checks only
src/services/   Business logic (the only place rules/calculations live)
src/adapters/sqlite/   Repositories — all SQL lives here; one repo per aggregate
src/domain/     Plain domain models / dataclasses
src/common/     Cross-cutting utils: jalali.py, utils.py, validators.py
src/config/settings.py   Config (DB path, ports, backup folder)
```

A route should call a service; a service should call a repository. Do not put SQL in routes or services — add or extend a repo in `src/adapters/sqlite/`.

### Database lifecycle (no migration framework)
There is no Alembic/migrations tool. Instead:
- `src/adapters/sqlite/schema.sql` is the source of truth and is **applied on first connection** (and is idempotent via `IF NOT EXISTS` / `INSERT OR IGNORE`), driven by `get_db()` in `src/adapters/sqlite/core.py`.
- Schema changes to **existing** databases are made with **additive runtime migrations**: add an `_ensure_column(...)` call in `core.py` (`_ensure_*` in webapp, `_run_migrations` in specialist). Migrations run once per process and must be safe to re-run. Never assume a fresh DB.
- In `specialist_clinic`, the ADA clinical-rule catalog is re-seeded idempotently on every startup from `core._run_migrations` → `clinical_rules_seed.seed_clinical_rules` (manager edits to rules are preserved). New seed data (`flag_catalog`, `drug_classes`, etc.) follows the same idempotent pattern.

`webapp/clinic_new.db` **is committed to git** (despite `*.db` in `webapp/.gitignore`) — it carries real seeded data. Be deliberate about committing changes to it. `specialist.db` is not tracked.

### Auth & roles
- Passwords use `bcrypt`; legacy `werkzeug` hashes are transparently migrated to bcrypt on successful login (`webapp/src/services/auth_service.py`). After **5 failed attempts the account locks for 15 minutes**.
- `webapp` has three roles — `manager` (`/manager`), `reception` (`/reception`), `doctor` (`/doctor`, plus a live "doctor room" backed by `doctor_room_state`). `specialist_clinic` logs in `admin/admin` (manager).
- `g.user` is loaded in a `before_request` hook. Routes guard with the `login_required` decorator (`src/api/auth.py`) **plus an inline `if g.user['role'] != 'manager'` check** — there is no role decorator; follow the existing inline pattern.

### Cross-cutting conventions (do not break these)
- **Jalali dates everywhere.** Conversion via `src/common/jalali.py` + `src/common/utils.py`; exposed to templates as Jinja filters (`jalali_datetime`/`jalali`/`jalali_date`). UI date inputs are Jalali (`YYYY/MM/DD`) and converted to Gregorian server-side before storage.
- **Persian digits in the UI** via the `fa_num` Jinja filter (adds thousands separators and converts `0-9` → `۰-۹`).
- **Iran local time.** All timestamps are stored as Tehran local time (UTC+3:30), produced by `utils.iran_now()` (`datetime.utcnow() + offset`, OS-timezone-independent) or by SQLite `datetime('now','+3 hours','+30 minutes')`. Do not introduce naive `datetime.now()` or UTC timestamps.
- **Manual shifts (webapp only).** Shifts (`morning`/`evening`/`night`) are switched manually by the user — there are **no automatic time boundaries**. Operational rows carry an explicit `work_date` (and `shift`) column rather than deriving the day from `DATE(timestamp)`, because a night shift can cross midnight. Use `utils.get_work_date_for_datetime()` / `g.user_shift_status`, not the calendar date, when attributing activity to a work day.
- **Activity logging.** User actions are logged via `services/activity_logger.log_activity(...)` into `activity_logs`. Add a log call for new state-changing actions.
- **Automatic backups.** A daemon thread (`services/scheduler.py`) copies the DB weekly (Saturday 03:00 Tehran) into `backups/`, keeping the last 4. It is started from `create_app` unless `TESTING`.

### Specialist Clinic — domain specifics
- **Clinical engines** live in `src/services/`: `rule_engine.py` (evaluates `clinical_rules.trigger_json` — a small all/any/not + leaf DSL — against patient "facts"), `followup_engine.py` (turns due rules into `followup_tasks`), `analytics_service.py` / `vitals_service.py` (risk/control scoring). The clinical thresholds are ADA-based; the authoritative spec is `specialist_clinic/docs/clinical_reference.md` and `specialist_clinic/ada_t2_rules.md`. When changing a threshold, update that doc **and** `vitals_service.THRESHOLDS` **and** `analytics_service.TARGETS` together. Decision support is advisory only ("suggestion, confirm with physician"); Red-Flag rules surface immediately.
- **SMS** goes through Mediana (`src/services/sms/`): an abstract `provider` layer + `mediana_provider.py` (stdlib `urllib`, header `X-API-KEY`, `POST https://api.mediana.ir/sms/v1/send/sms`). With no API key configured it falls back to a `NullProvider` (simulated send). Keys/sending-number/message-type are stored in the `settings` table (Manager → Settings). `compliance.py` rewrites banned promo words automatically. Patient **wallet** credit (`wallet_repo.py`) is the lawful replacement for "discount/free".
- **Offline by design:** front-end libraries (jQuery, persian-date, persian-datepicker, Chart.js) are vendored under `src/static/vendor/` — no CDNs. Date inputs with class `.jdate` get the datepicker wired up in `base.html`.

## Dev gotchas
- The preview/dev server runs with `debug=False`. Templates auto-reload in source mode, **but Python code changes require a full server restart** (stop + start) to take effect.
- When adding a bundled file (template, static asset, schema), update the PyInstaller `datas` (in `webapp/HesabdariSib.spec` or the specialist `README.md` command) or it will be missing from the `.exe`.

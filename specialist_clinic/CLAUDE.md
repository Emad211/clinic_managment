# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⛳ دستور همیشگی — اول از همه بخوان · STANDING RULE: read before ANY task

**دستور اولِ کاربر (always, every task):** پیش از شروع هر کاری در این پروژه، ابتدا **هر ۳ منبع** را بخوان و مبنا قرار بده —
1. **مموری (Memory):** `~/.claude/projects/.../memory/MEMORY.md` و فایل‌های مموریِ مرتبط — چه‌کسی/چه/چرا که در کد نیست.
2. **CLAUDE.md:** همین فایل + ریشهٔ پروژه ([`../CLAUDE.md`](../CLAUDE.md)) — قوانین معماری و «کد چطور کار می‌کند».
3. **گراف دانشِ graphify:** [`graphify-out/GRAPH_REPORT.md`](graphify-out/GRAPH_REPORT.md) و `graphify-out/graph.json` — نقشهٔ نود/جامعه/god-node. برای پرسش، `/graphify query "…"` را اجرا کن.

فقط بعد از خواندن این سه شروع به کار کن. `MEMORY.md` و `CLAUDE.md` خودکار لود می‌شوند، اما `GRAPH_REPORT.md` را باید صریحاً Read کنی (خودکار لود نمی‌شود). اگر کد به‌طور معنادار تغییر کرد، گراف را با `/graphify --update` تازه کن تا گمراه‌کننده نشود.

> Scope: this file documents the **`specialist_clinic/` Flask app** specifically. For repo-wide vision/strategy and the other trees (`webapp/` accounting, `platform/` Django SaaS, `ai_service/` knowledge pipeline), see the root [`../CLAUDE.md`](../CLAUDE.md) and [`../docs/`](../docs/README.md). When the two disagree about *this app*, this file wins.

## What this app is

Standalone chronic-disease management app (diabetes / hypertension): vitals tracking, ADA clinical decision support, appointments, a follow-up worklist, and SMS campaigns. Flask + SQLite desktop app, **port 8090**, own database `specialist.db`. It reads patient demographics + revenue **live and read-only** from the accounting app's `clinic_new.db` through `src/adapters/accounting_bridge.py` (linked by `national_id`). UI is RTL/Jalali, strings mostly Persian.

## Run / seed / build

Use the known-good venv (Python 3.13) — it is the interpreter `.claude/launch.json` points at.

```powershell
.\.venv\Scripts\python.exe start.py          # http://127.0.0.1:8090 — login admin/admin
.\.venv\Scripts\python.exe seed_demo_data.py # idempotent: 10 demo patients TEST0001..TEST0010 (use these for all dev/testing)
```

- **Default admin** (`admin`/`admin`, manager) is auto-created on first DB connection if the `users` table is empty (`core._ensure_default_admin`).
- **Env overrides:** `ACCOUNTING_DB_PATH` (default `../webapp/clinic_new.db`), `SPECIALIST_DB_PATH`, `PORT` (8090), `SECRET_KEY`.
- **No test suite exists.** Verify changes by running the app against the demo patients. The factory accepts `create_app({"TESTING": True, ...})` and `TestConfig` uses `DATABASE_PATH=':memory:'` (this disables the background scheduler).
- **Build .exe:** the PyInstaller command lives in `README.md` — it must bundle `src/templates`, `src/static`, and `src/adapters/sqlite/schema.sql`. If you add a bundled template/static/data file, update that command or it will be missing from the frozen build.

`start.py` and `create_app` both detect frozen mode via `sys.frozen`/`sys._MEIPASS` and resolve `templates/`, `static/`, and `schema.sql` accordingly — keep that dual source/frozen path handling intact when touching bootstrap or adding bundled files.

## Layering (respect it when adding features)

```
src/api/        Flask Blueprints — routes, request/response, auth decorators only
src/services/   Business logic — the only place rules/calculations live (incl. the clinical engines)
src/adapters/sqlite/   Repositories — ALL SQL lives here, one repo per aggregate
src/adapters/accounting_bridge.py   Read-only bridge to the accounting DB
src/common/     jalali.py, utils.py, validators.py (cross-cutting)
src/config/settings.py   Config (DB paths, port, backup folder)
```

A route calls a service; a service calls a repository. **Do not put SQL in routes or services** — add/extend a repo in `src/adapters/sqlite/`. (Some thin route handlers run trivial `get_db().execute(...)` for read-only lookups, e.g. `suggestion_log` status — but new state-changing SQL belongs in a repo.)

## Database lifecycle (no migration framework)

`src/adapters/sqlite/core.py` `get_db()` returns the per-request connection and, **once per process** (`_initialized` module flag), does all bootstrap:
- Applies `src/adapters/sqlite/schema.sql` (the source of truth; idempotent via `IF NOT EXISTS` / `INSERT OR IGNORE`).
- Runs `_run_migrations(db)` — additive only: add an `_ensure_column(table, col, decl)` call for new columns on existing DBs (must be safe to re-run; never assume a fresh DB).
- Re-seeds the ADA rule catalog idempotently via `clinical_rules_seed.seed_clinical_rules` (manager edits to rules are preserved — seeding is `INSERT OR IGNORE` by `rule_code`).
- Ensures the default admin.

**Because bootstrap is gated on a module-level `_initialized` flag, Python code changes require a full server restart** (stop + start) to take effect. Templates auto-reload in source mode; Python does not.

**The patient table is `patient_links`, not `patients`.** Throughout services/repos, a `pid` argument means `patient_links.id`, and every per-patient table FKs to it via `patient_link_id`. (`patients` is the *accounting* app's table, reachable only through the read-only bridge.) `patient_links` is a local mirror keyed by `national_id` with an optional `accounting_patient_id` link.

## The clinical engine (this app's differentiator — ADA decision support)

Decision support is **suggestion-only**: "پیشنهاد — تأیید با پزشک". The engine surfaces suggestions; the physician decides; the decision is logged. Red-flags surface immediately.

**Data (all editable by the manager, seeded with ADA defaults):**
- `clinical_indicators` (seeded in `schema.sql`) — indicator metadata: `warn`/`danger` thresholds, `target`/`goal_low`/`goal_high`, `direction` (high|low = which way is worse), `category`, `conditions` (which diseases it applies to), `risk_weight`. Edited at `/manager/rules`. **This is the live source of truth for thresholds.**
- `clinical_rules` (seeded by `clinical_rules_seed.py`) — the full ADA If/Then catalog across every section (diagnosis, targets, medication, drug-safety, insulin, monitoring, screening, red-flags, hypo, lifestyle, vaccination). The `trigger_json` column is a small **all/any/not + leaf DSL**. Edited at `/manager/decision-rules`.
- `flag_catalog` + `patient_flags` — categorical/boolean ADA decision inputs (ascvd, hf, ckd_stage_g/a, hypo_risk, frailty, masld, pregnancy, smoking, …).
- `drug_classes` — maps medications to a pharmacologic class (`patient_medications.drug_class`); drives the treatment/safety/risk rules.

**Code (`src/services/`):**
- `rule_engine.py` `RuleEngine`: `build_facts(pid)` assembles `{age, conditions, indicator{key:{latest,level}}, flag, med_classes}` → `_eval` walks the `trigger_json` DSL → `evaluate(pid)` returns fired rules (sorted by severity) → `grouped(pid)` buckets them into UI sections. Suggestion-only.
- `vitals_service.py`: `evaluate_reading(vtype, value)` → `'danger'|'warn'|'ok'`, reading thresholds from the editable `clinical_indicators` and falling back to the static `THRESHOLDS` map only if the indicator row is missing. `control_status(pid)` aggregates the latest readings.
- `analytics_service.py`: `patient_analytics(pid)` builds the per-disease dashboard (only indicators relevant to the patient's conditions), the weighted `_risk` score (clinical points + behavioral/adherence factors), and on-demand `medication_effect` (pre/post mean around a drug's start). Holds the static `TARGETS` fallback.
- `followup_engine.py`: turns fired monitoring/screening/vaccine rules into `followup_tasks` **only when actually due** (interval elapsed / never done) — keeps the worklist practical, not spammy.
- `suggestion_log` (table) + `patients.suggestion_action` route: records the physician's accept/dismiss per `(patient_link_id, rule_code)` — the accountability trail for the suggestion-only system.

**Threshold-sync rule:** clinical thresholds now live in the editable `clinical_indicators` table (seeded in `schema.sql`). The Python `vitals_service.THRESHOLDS` and `analytics_service.TARGETS` are **last-resort fallbacks**. When you change a threshold, update the `clinical_indicators` seed **and** keep those two fallbacks **and** the docs ([`docs/clinical_reference.md`](docs/clinical_reference.md), [`ada_t2_rules.md`](ada_t2_rules.md)) consistent. Treatment-engine design notes are in [`docs/treatment_engine_plan.md`](docs/treatment_engine_plan.md).

## Auth & roles

- Two roles: **`manager`** and **`staff`**. `g.user` is loaded in a `before_request` hook from `session['user_id']`.
- **Unlike the `webapp` accounting app, this app HAS a role decorator.** `src/api/auth.py` defines both `login_required` and `manager_required` — guard manager-only routes with `@manager_required` (used throughout `src/api/manager.py`), not an inline role check.
- Passwords use `bcrypt`; legacy `werkzeug` hashes are transparently migrated to bcrypt on first successful login (`auth_service.py`). **5 failed attempts → 15-minute lockout.**

## Cross-cutting conventions (do not break these)

- **Jalali everywhere.** Jinja filters registered in `app.py`: `jalali` (date+time → `format_jalali_datetime`), `jalali_date` (date only), `fa_num` (Persian digits + thousands separators). UI date inputs are Jalali (`YYYY/MM/DD`) and converted to Gregorian **server-side** with `common.utils.jalali_to_gregorian_str` before storage. Dates are stored as Gregorian `YYYY-MM-DD` strings.
- **Iran local time (UTC+3:30) for every timestamp.** Use `common.utils.iran_now()` (OS-timezone-independent `utcnow()+offset`) or SQLite `datetime('now','+3 hours','+30 minutes')`. Never introduce naive `datetime.now()` / UTC timestamps. Helpers: `today_str()`, `add_months()`, `format_jalali_date/datetime()`.
- **Activity logging.** Log new state-changing actions via `services/activity_logger.log_activity(action_type, description, patient_link_id=…)` into `activity_logs`.
- **Background scheduler** (`services/scheduler.py`): a daemon thread started from `create_app` (skipped when `TESTING`). After a 20s warmup it ticks every 2 min: appointment reminders (next 24h), due SMS campaigns, once-daily follow-up generation, and a weekly DB backup (Saturday ~03:00 Tehran, keeps the last 4 in `backups/`). Off-request DB access runs inside `app.app_context()`.
- **SMS via Mediana** (`services/sms/`): abstract `provider` + `mediana_provider.py` (stdlib `urllib`, header `X-API-KEY`, `POST https://api.mediana.ir/sms/v1/send/sms`). With **no API key** configured it falls back to a `NullProvider` (simulated send). Keys/sending-number/message-type live in the `settings` table (Manager → Settings). `compliance.py` rewrites banned promo words. Patient **wallet** credit (`wallet_repo.py`, `wallet_transactions`) is the lawful framing for "discount/free" — frame promotions as اعتبار, not تخفیف.
- **Offline by design.** Front-end libs (jQuery, persian-date, persian-datepicker, Chart.js) are vendored under `src/static/vendor/` — no CDNs. Inputs with class `.jdate` get the datepicker wired up in `base.html`.

## Accounting bridge — read-only, never write

`src/adapters/accounting_bridge.py` opens `clinic_new.db` with the sqlite3 URI `mode=ro`; any write attempt raises instead of mutating. **Never make this writable.** It returns empty/None gracefully when the accounting DB is absent (the specialist app must keep working standalone). Its revenue functions deliberately mirror the accounting app's definition (closed invoices; `visits.price + injections.total_price + procedures.price`; attributed by `invoices.work_date`) — keep them in sync if that definition changes in `webapp`.

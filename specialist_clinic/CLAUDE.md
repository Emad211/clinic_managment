# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⛳ دستور همیشگی — اول از همه بخوان · STANDING RULE: read before ANY task

**دستور اولِ کاربر (always, every task):** پیش از شروع هر کاری در این پروژه، ابتدا **هر ۳ منبع** را بخوان و مبنا قرار بده —
1. **مموری (Memory):** `~/.claude/projects/.../memory/MEMORY.md` و فایل‌های مموریِ مرتبط — چه‌کسی/چه/چرا که در کد نیست.
2. **CLAUDE.md:** همین فایل + ریشهٔ پروژه ([`../CLAUDE.md`](../CLAUDE.md)) — قوانین معماری و «کد چطور کار می‌کند».
3. **گراف دانشِ graphify:** [`graphify-out/GRAPH_REPORT.md`](graphify-out/GRAPH_REPORT.md) و `graphify-out/graph.json` — نقشهٔ نود/جامعه/god-node. برای پرسش، `/graphify query "…"` را اجرا کن.

فقط بعد از خواندن این سه شروع به کار کن. `MEMORY.md` و `CLAUDE.md` خودکار لود می‌شوند، اما `GRAPH_REPORT.md` را باید صریحاً Read کنی (خودکار لود نمی‌شود). اگر کد به‌طور معنادار تغییر کرد، گراف را با `/graphify --update` تازه کن.

> Scope: this file documents the **`specialist_clinic/` Flask app** specifically. The repo currently holds exactly two apps — `webapp/` (accounting) and `specialist_clinic/`. (Earlier `platform/`/`ai_service/`/root-`docs/` trees were removed and must not be resurrected.) For repo-wide vision/strategy see the root [`../CLAUDE.md`](../CLAUDE.md). When the two disagree about *this app*, this file wins.

## فاز جاری — بازطراحیِ پروندهٔ بیماری‌محور و «حلقهٔ مراقبت» (در حالِ اجرا)

> این بخش **جهتِ کار** را می‌گوید؛ بعضی موارد هنوز ساخته نشده‌اند — نقشهٔ کامل و وضعیت در [`docs/record_redesign_plan.md`](docs/record_redesign_plan.md).

دو مفهومِ کلان که شکلِ کد را تعیین می‌کنند:
1. **پروندهٔ بیماری‌محور (composable record):** هر بیماریِ مزمنِ ثبت‌شده، بخش‌ها/داده‌های مخصوصِ خود را به پرونده **اضافه** می‌کند — پایهٔ مشترک (هویت/حساسیت/جراحی/سبک‌زندگی) + ماژول‌های بیماری (داده، نه کدِ سخت؛ بیماری‌اگنوستیک).
2. **قیفِ پیگیری → ویزیت:** پیگیری باید به **نوبت** برسد. `تعریف(بیماری) → اندازه‌گیری(پرونده) → تشخیص(موتور) → اقدام(قیف) → ویزیت → تکرار`. دو مسیرِ بستن: **از‌راه‌دور** (تجدیدِ نسخه/آزمایشِ دوره‌ای → تأییدِ پزشک → یا **نسخهٔ آزادِ غیربیمه‌ای** که اپ می‌سازد، یا **نسخهٔ بیمه‌ای via «پل نسخه‌نویسی»**) و **حضوری** (مشاوره/معاینه → نوبتِ رزروشده). درآمد فقط از پلِ read-only حسابداری خوانده می‌شود.
   - **ترکِ موازیِ «پل نسخه‌نویسی»** (کدبیسِ جدا، اکستنشنِ مرورگرِ MV3): روی **لاگینِ خودِ پزشک** در پنل‌های وبِ بیمه (نمونه تأمین اجتماعی `ep.tamin.ir`، SPA) کار می‌کند → مجوزِ شرکتی لازم ندارد. چند سامانه = چند آداپتور؛ **اول capture بعد auto-fill**؛ چند پزشک (جدولِ `physicians`+توکن)؛ ثبتِ نهایی با کلیکِ پزشک. **بعد از فاز ۵/۶** آغاز می‌شود؛ seamهایش در فاز ۶. **⛔ بلاک‌شده تا مالک دسترسیِ زنده + ساختارِ صفحهٔ نسخهٔ نهاییِ پنل‌های بیمه را بدهد** (تنها تراکِ بلاک‌شدهٔ پروژه؛ جزئیات و گِیتِ E1 در [`docs/record_redesign_plan.md`](docs/record_redesign_plan.md) §«ترکِ موازی»).

اسنادِ مرتبط: [`docs/record_redesign_plan.md`](docs/record_redesign_plan.md) · [`docs/accounting_sync.md`](docs/accounting_sync.md) (کارهای سمتِ `webapp`) · [`docs/kavenegar_reference.md`](docs/kavenegar_reference.md) · [`docs/engagement_engine_plan.md`](docs/engagement_engine_plan.md).

## What this app is

Standalone chronic-disease management app (diabetes / hypertension / hyperlipidemia / CKD / thyroid). Flask + SQLite desktop app, **port 8090**, own database `specialist.db`. Features: per-disease vitals/labs, a **per-disease modular clinical engine** (suggestion-only decision support), appointments, an automated **engagement engine** (reminders/follow-ups/campaigns unified), a follow-up worklist, a prioritized **Control Room** (`/control-room`), and SMS (Kavenegar). It reads patient demographics + revenue **live and read-only** from the accounting app's `clinic_new.db` through `src/adapters/accounting_bridge.py` (linked by `national_id`). UI is RTL/Jalali, strings mostly Persian. The clinical engine is rooted in ADA Standards but the **"ADA" name is removed from the UI** (it remains in code comments and `T2-*` rule codes).

## Run / seed / build

Use the known-good venv (Python 3.13) — it is the interpreter `.claude/launch.json` points at.

```powershell
.\.venv\Scripts\python.exe start.py          # http://127.0.0.1:8090 — login admin/admin
.\.venv\Scripts\python.exe seed_demo_data.py # idempotent: 10 demo patients TEST0001..TEST0010 (use these for all dev/testing)
```

- **Default admin** (`admin`/`admin`, manager) is auto-created on first DB connection if the `users` table is empty (`core._ensure_default_admin`).
- **Env overrides:** `ACCOUNTING_DB_PATH` (default `../webapp/clinic_new.db`), `SPECIALIST_DB_PATH`, `PORT` (8090), `SECRET_KEY`.
- **A growing pytest suite lives in `tests/`** — run `PYTHONIOENCODING=utf-8 .\.venv\Scripts\python.exe -m pytest tests/ -q` (currently **96 tests, all green**: invoice-sync, outreach, doctor-queue, and the patient card — the latter includes an **architecture guard test** asserting the card surface stays GET-only + zero-write). Tests run on temp/copy DBs and never send real SMS or touch the accounting DB. Still verify UI/behavioural changes by running the app against the demo patients. The factory accepts `create_app({"TESTING": True, ...})` and `TestConfig` uses `DATABASE_PATH=':memory:'` (this disables the background scheduler). **Testing each phase is mandatory.**
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

A route calls a service; a service calls a repository. **Do not put SQL in routes or services** — add/extend a repo in `src/adapters/sqlite/`. (Some thin route handlers run trivial `get_db().execute(...)` for read-only lookups — but new state-changing SQL belongs in a repo.)

## Database lifecycle (no migration framework)

`src/adapters/sqlite/core.py` `get_db()` returns the per-request connection and, **once per process** (`_initialized` module flag), does all bootstrap:
- Applies `src/adapters/sqlite/schema.sql` (the source of truth; idempotent via `IF NOT EXISTS` / `INSERT OR IGNORE`).
- Runs `_run_migrations(db)` — additive only: add an `_ensure_column(table, col, decl)` call (or `CREATE TABLE IF NOT EXISTS`) for new columns/tables on existing DBs (must be safe to re-run; never assume a fresh DB).
- Re-seeds the clinical rule catalog idempotently via `clinical_rules_seed.seed_clinical_rules` (manager edits preserved — `INSERT OR IGNORE` by `rule_code`) and condition metadata via `_seed_condition_meta`.
- Ensures the default admin.

**Because bootstrap is gated on a module-level `_initialized` flag, Python code changes require a full server restart** (stop + start) to take effect. Templates auto-reload in source mode; Python does not.

**The patient table is `patient_links`, not `patients`.** Throughout services/repos, a `pid` argument means `patient_links.id`, and every per-patient table FKs to it via `patient_link_id`. (`patients` is the *accounting* app's table, reachable only through the read-only bridge.) `patient_links` is a local mirror keyed by `national_id` with an optional `accounting_patient_id` link.

## The clinical engine (this app's differentiator — per-disease, suggestion-only)

Decision support is **suggestion-only**: "پیشنهاد — تأیید با پزشک". The engine surfaces suggestions; the physician decides; the decision is logged. Red-flags surface immediately. It is **modular per disease**: each chronic disease is a *data module* (indicators + rules + flags + drug classes), gated by `condition_code` — adding a disease = adding data, not code.

**Data (all editable by the manager, seeded with clinical defaults):**
- `clinical_indicators` (seeded in `schema.sql`) — indicator metadata: `warn`/`danger` thresholds, `target`/`goal_low`/`goal_high`, `direction` (high|low), `category`, `conditions` (which diseases it applies to), `risk_weight`. **Live source of truth for thresholds.**
- `clinical_rules` (seeded by `clinical_rules_seed.py`) — the full If/Then catalog with a `condition_code` per rule (`all`=cross-disease, or a `conditions.code`). The `trigger_json` column is a small **all/any/not + leaf DSL**. Disease packs: diabetes/HTN/HLD/CKD/THY; non-diabetes drug rules are gated `{not: DM}` to avoid duplicate suggestions for diabetics.
- `flag_catalog` + `patient_flags` — categorical/boolean decision inputs (ascvd, hf, ckd_stage_g/a, hypo_risk, frailty, masld, pregnancy, smoking, …).
- `drug_classes` — maps medications to a pharmacologic class (`patient_medications.drug_class`); drives treatment/safety/risk rules.

**Manager UI:** a **per-disease page** `/manager/diseases/<code>` (one disease = one page, merging indicators + decision rules). The old `/manager/rules` and `/manager/decision-rules` pages are demoted to an "advanced view" (their handlers return via `request.referrer`).

**Code (`src/services/`):**
- `rule_engine.py` `RuleEngine`: `build_facts(pid)` → `_eval` walks `trigger_json` → `evaluate(pid)` fired rules → `grouped(pid)` buckets into UI sections.
- `vitals_service.py`: `evaluate_reading(vtype, value)` → `'danger'|'warn'|'ok'` from `clinical_indicators` (static `THRESHOLDS` only as fallback). `control_status(pid)` aggregates latest readings.
- `analytics_service.py`: `patient_analytics(pid)` per-disease dashboard, weighted `_risk` score, on-demand `medication_effect`. Static `TARGETS` fallback.
- `followup_engine.py`: `due_clinical_events(pid)` (shared "what's due" extractor used by both the worklist and the engagement dispatcher) → `followup_tasks` **only when actually due**.
- `engagement_service.py` / `engagement_repo.py`: the **event→channel engine** — `engagement_events` config (channel sms|worklist|both|off) + `engagement_dispatch` ledger (idempotency/cooldown/daily-cap) + guardrails (opt-out, quiet hours, daily cap). Runs from the scheduler.
- `control_room_service.py`: prioritized cohort targeting (`/control-room`) — clinical-first score + revenue (manager-only column).
- `suggestion_log` (table) + `patients.suggestion_action` route: records physician accept/dismiss per `(patient_link_id, rule_code)`.

**Threshold-sync rule:** thresholds live in the editable `clinical_indicators` table. `vitals_service.THRESHOLDS` and `analytics_service.TARGETS` are **last-resort fallbacks**. When you change a threshold, update the `clinical_indicators` seed **and** those two fallbacks **and** the docs ([`docs/clinical_reference.md`](docs/clinical_reference.md), [`ada_t2_rules.md`](ada_t2_rules.md)).

## Auth & roles

- Two roles: **`manager`** and **`staff`**. `g.user` is loaded in a `before_request` hook from `session['user_id']`.
- **Unlike the `webapp` accounting app, this app HAS a role decorator.** `src/api/auth.py` defines both `login_required` and `manager_required` — guard manager-only routes with `@manager_required`, not an inline role check.
- Passwords use `bcrypt`; legacy `werkzeug` hashes migrate to bcrypt on first successful login. **5 failed attempts → 15-minute lockout.**

## Cross-cutting conventions (do not break these)

- **Jalali everywhere.** Jinja filters in `app.py`: `jalali`, `jalali_date`, `fa_num`. UI date inputs are Jalali (`YYYY/MM/DD`) and converted to Gregorian **server-side** with `common.utils.jalali_to_gregorian_str` before storage. Dates stored as Gregorian `YYYY-MM-DD`.
- **Iran local time (UTC+3:30) for every timestamp.** Use `common.utils.iran_now()` or SQLite `datetime('now','+3 hours','+30 minutes')`. Never naive `datetime.now()` / UTC.
- **Activity logging.** Log new state-changing actions via `services/activity_logger.log_activity(...)` into `activity_logs`.
- **Background scheduler** (`services/scheduler.py`): a daemon thread from `create_app` (skipped when `TESTING`). After a 20s warmup it ticks every 2 min: **`EngagementService().run_all()`** (reminders/follow-ups/campaigns all flow through the engagement engine), due SMS campaigns, once-daily follow-up generation, and a weekly DB backup (Saturday ~03:00 Tehran, keeps last 4 in `backups/`). Off-request DB access runs inside `app.app_context()`.
- **SMS — Kavenegar (primary), Mediana (fallback).** `services/sms/`: abstract `provider.py` + `kavenegar_provider.py` (stdlib `urllib`; **API key is in the URL path**, not a header; `return.status==200`=ok; timeout→`pending`, not failed; `account/info` for balance) + `mediana_provider.py` (legacy, `X-API-KEY` header). `get_provider()` picks the panel from the `sms_provider` setting (`kavenegar|mediana`) with graceful fallback to `NullProvider` (simulated). Keys/sender/timeout live in the `settings` table (Manager → Settings). Full reference: [`docs/kavenegar_reference.md`](docs/kavenegar_reference.md). **Known gate:** the live key is valid but the Kavenegar account returns code **430 (احراز هویت/KYC not completed)** — no real sends until the owner finishes KYC. `compliance.py` rewrites banned promo words. Patient **wallet** credit (`wallet_repo.py`) is the lawful framing for "discount/free" — frame promotions as **اعتبار, not تخفیف** (this underpins the future offer engine, Phase 8 of the redesign).
- **Offline by design.** Front-end libs (jQuery, persian-date, persian-datepicker, Chart.js) are vendored under `src/static/vendor/` — no CDNs. Inputs with class `.jdate` get the datepicker wired up in `base.html`.

## Accounting bridge — read-only, never write

`src/adapters/accounting_bridge.py` opens `clinic_new.db` with the sqlite3 URI `mode=ro`; any write attempt raises instead of mutating. **Never make this writable.** It returns empty/None gracefully when the accounting DB is absent (the specialist app must keep working standalone). Its revenue functions deliberately mirror the accounting app's definition (closed invoices; `visits.price + injections.total_price + procedures.price`; attributed by `invoices.work_date`) — keep them in sync if that definition changes in `webapp`. Money-side actions (e.g. deferred-payment settlement) belong in `webapp`, tracked in [`docs/accounting_sync.md`](docs/accounting_sync.md).

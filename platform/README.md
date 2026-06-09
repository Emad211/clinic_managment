# platform/ — Cloud SaaS (Django + django-ninja + PostgreSQL)

This is the **Evolve-not-Rewrite destination** for the two Flask apps
(`webapp/`, `specialist_clinic/`). It is a **separate, additive** Django project:
building it does **not** touch the running Flask apps (ports 8080 / 8090). See
[`../docs/TECH_STACK.md`](../docs/TECH_STACK.md) and
[`../docs/DATA_MODEL.md`](../docs/DATA_MODEL.md) for the *why*.

> Status: **v0.10 scaffold — demoable** — all 8 modules from DATA_MODEL §2
> modelled (~40 models), RLS multi-tenancy, django-ninja API (session login +
> authz-guarded routers), bcrypt + 5-fail/15-min lockout, a **full ETL** (users +
> merged patients + per-patient vitals/meds/conditions/flags/followups) + a
> **clinical-catalog ETL** (real 57 ADA rules), the **ported rule engine** (live
> decision support), a **web frontend** (login → patient list → snapshot + grouped
> ADA suggestions), and the **accountability loop** (physician-acknowledge →
> append-only SuggestionLog). End-to-end verified on the **real** legacy data.
> `manage.py check` clean. Remaining: HTMX interactivity, accounting/sms ETL,
> production hardening.

## Layout (modular monolith)

```
platform/
  config/            # Django project: settings, urls, ninja api root, wsgi/asgi
    api.py           # NinjaAPI: /api/health + /api/auth + /api/patients + /api/chronic
  apps/
    common/          # base models (UUID/Tenant/Catalog), RLS middleware + RLS migrations
    identity/        # Clinic (tenant), AppUser, UserShift
    billing/         # Plan (global), Subscription, Payment (ZarinPal)
    patients/        # Patient (unified webapp.patients + specialist.patient_links) + api
    chronic/         # ADA catalogs + clinical records + wallet + rule_engine + api
    rx/              # Drug (global), Prescription/Item, InsurerLog (Epic 1, WebView->API)
    accounting/      # Invoice, Visit, Injection, Procedure, Consumable, Tariff, Payroll
    messaging/       # SmsTemplate, SmsCampaign, SmsMessage (Mediana + NullProvider)
    web/             # server-rendered frontend: login + patient list + detail (RTL)
  requirements.txt
  .env.example
```

Module boundaries mirror `docs/DATA_MODEL.md` §2. `plan` and `drug` are
platform-level global reference tables (no `clinic_id`, no RLS); everything else
is tenant-owned and RLS-protected.

## Multi-tenancy: PostgreSQL Row-Level Security

Every domain table has `clinic_id` and is protected by an RLS policy
(`apps/common/migrations/0001_rls.py`). The request flow:

1. `TenantMiddleware` (`apps/common/middleware.py`) resolves the user's clinic
   and runs `SELECT set_config('app.current_clinic', <uuid>, true)` inside the
   request transaction (`ATOMIC_REQUESTS=True`).
2. RLS policies filter every query to that clinic. **Deny-by-default**: if the
   GUC is unset, `current_setting(..., true)` is NULL → zero rows.
3. Background workers / commands use `with tenant_context(clinic_id):`
   (`apps/common/tenant.py`).

The DB role the app connects with **must not have `BYPASSRLS`**. Global catalog
rows (`clinic_id IS NULL`) are readable by all tenants but writable only as
per-clinic overrides.

## Setup & verify

```powershell
cd platform
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env          # then edit DATABASE_URL / secret
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py migrate        # needs a PostgreSQL DB
# Clinical catalogs — pick ONE (mutually exclusive):
.\.venv\Scripts\python.exe manage.py etl_catalog --specialist-db ..\specialist_clinic\specialist.db  # full real ADA set (preferred)
.\.venv\Scripts\python.exe manage.py seed_catalog    # OR minimal fresh-install fallback
.\.venv\Scripts\python.exe manage.py bootstrap_clinic --name "درمانگاه نمونه" --slug demo
# OR migrate the real legacy data into one tenant (idempotent, source DBs read-only):
.\.venv\Scripts\python.exe manage.py etl_import --clinic-slug main --clinic-name "درمانگاه اصلی" `
    --webapp-db ..\webapp\clinic_new.db --specialist-db ..\specialist_clinic\specialist.db
.\.venv\Scripts\python.exe manage.py runserver       # GET /api/health -> {"status":"ok"}
```

**Seeding & RLS:** `seed_catalog` writes GLOBAL catalog rows (`clinic_id NULL`)
and `bootstrap_clinic` writes the first `app_user` of a clinic. Both write rows
the per-request tenant RLS policies would reject, so on PostgreSQL **run them
under the platform owner / a `BYPASSRLS` ops role**, not the app's tenant role.
ADA thresholds in `seed_catalog` must stay in sync with `specialist_clinic`'s
`vitals_service.THRESHOLDS` / `analytics_service.TARGETS` (CLAUDE.md rule).

Migrations were smoke-tested end-to-end against throwaway SQLite (the RLS
migration no-ops off PostgreSQL by design). Real RLS enforcement requires a
PostgreSQL target — use a `pgvector/pgvector:pg16` image to match the stack.

## Resolved scaffold decisions

- **Auth integration → custom session auth** (`apps/identity/services.py` +
  `apps/identity/api.py`). `AppUser` stays a plain model (NOT `AUTH_USER_MODEL`):
  it preserves the Flask apps' bcrypt + 5-fail/15-min-lockout and legacy
  werkzeug→bcrypt upgrade-on-login. Login stores `clinic_id`/`user_id` in the
  session; `TenantMiddleware` reads `clinic_id` thereafter.
- **Login vs. RLS ordering → solved.** Login resolves `Clinic` by slug (clinic
  table is not RLS-protected), enters `tenant_context(clinic.id)`, THEN queries
  `app_user`. `apps/common/tenant.py` no-ops the GUC off PostgreSQL so the app
  also runs on SQLite for local dev/tests.

- **API authz guard → done.** `apps/common/auth.SessionAuth` (ninja dependency)
  401s when the session has no logged-in user; attached to the patients/chronic
  routers (auth router stays open). `require_role()` helper for endpoint RBAC.

## ETL (legacy SQLite -> one tenant)

`etl_import` opens `webapp/clinic_new.db` + `specialist_clinic/specialist.db`
**read-only** and merges them into one `clinic`: users (both apps, deduped by
username) + patients (webapp.patients ⋈ specialist.patient_links by national_id,
retiring the accounting_bridge) + wallet balance + **per-patient chronic records**
(vitals, medications, conditions, flags, follow-ups) linked via a
`patient_links.id → Patient` map built during the patient pass. Run **`etl_catalog`
first** so the global Condition/Flag/DrugClass/Indicator catalogs exist to link
against. Legacy timestamps are Gregorian ISO (verified) — no Jalali conversion
needed; birthdate→age is Jalali-aware in the engine. Idempotent (get_or_create
on natural keys).

`etl_catalog` ports the GLOBAL clinical catalogs from `specialist.db` (the
authoritative 57 ADA rules + 13 indicators + 18 flags + 19 drug classes +
5 conditions, with full trigger_json + recommendation + dosage/monitoring/
contraindications). The catalog models mirror the specialist schema 1:1 so
nothing is dropped. `etl_catalog` and `seed_catalog` are **mutually exclusive** —
run `etl_catalog` when `specialist.db` exists, `seed_catalog` only for a fresh
install with no legacy data.

Both verified idempotent against the real DBs. **TODO (later loops):** accounting
rows, SMS, tariffs, allergies/labs/appointments (empty in source); Tehran→UTC
normalisation of timestamps.

## Web frontend (`apps/web/`)

Minimal RTL, server-rendered Django templates — the demoable slice of the wedge:
`/login/` → `/patients/` (search) → `/patients/<id>/` (One-Page Snapshot of latest
indicators + grouped ADA suggestions with the "تأیید با پزشک" disclaimer). Login
follows the RLS-correct ordering and reuses the same session keys as the API.
Each suggestion has a **تأیید (acknowledge)** action: the physician confirms it
and an append-only `SuggestionLog` row is written (rule_code, severity, message,
acknowledged_by, acknowledged_at) — the safety/legal backbone ("suggests,
physician decides, logged"). Idempotent; the page then shows ✓ تأیید پزشک.
Verified end-to-end on real data (TEST0008 → 26 suggestions, ack logged). HTMX
interactivity (live search, inline ack without full reload) is the next polish.

## Clinical rule engine (`apps/chronic/rule_engine.py`)

Ported from `specialist_clinic/src/services/rule_engine.py`. A pure evaluator
(`_resolve`/`_leaf`/`_eval`) over the `trigger_json` DSL (all/any/not + leaf
`{var, op, value}`), decoupled from the DB: `evaluate(facts, rules)` /
`grouped(facts, rules)` take a facts dict + ClinicalRule iterable. `build_facts(
patient)` assembles the bundle from the ORM (age, conditions, latest vitals per
indicator, flags w/ values, active med classes). Surfaced at
**`GET /api/chronic/suggestions?patient_id=…`** — suggestion-only, physician
confirms. Verified against the real 57 rules (a poorly-controlled diabetic fires
25 grouped suggestions; a healthy person fires 0).

## Open scaffold decisions

- **CSRF** for cookie-session POSTs (login/logout) — hardening follow-up.
- **`drug` reference dataset** source (Epic 1) — see `docs/DATA_MODEL.md` §8.

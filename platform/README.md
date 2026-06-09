# platform/ — Cloud SaaS (Django + django-ninja + PostgreSQL)

This is the **Evolve-not-Rewrite destination** for the two Flask apps
(`webapp/`, `specialist_clinic/`). It is a **separate, additive** Django project:
building it does **not** touch the running Flask apps (ports 8080 / 8090). See
[`../docs/TECH_STACK.md`](../docs/TECH_STACK.md) and
[`../docs/DATA_MODEL.md`](../docs/DATA_MODEL.md) for the *why*.

> Status: **v0.5 scaffold** — all 8 modules from DATA_MODEL §2 modelled (~40
> models), RLS multi-tenancy across every tenant table, django-ninja API with
> session login + **authz-guarded** data routers, bcrypt + 5-fail/15-min lockout,
> idempotent catalog seed + clinic bootstrap, and a **SQLite->Postgres ETL**
> (clinic + users + merged patients) verified against the real legacy DBs.
> `manage.py check` clean. Remaining for a usable product: ETL long tail
> (chronic/accounting/sms), SPA, production hardening.

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
    chronic/         # ADA engine catalogs + per-patient clinical records + wallet + api
    rx/              # Drug (global), Prescription/Item, InsurerLog (Epic 1, WebView->API)
    accounting/      # Invoice, Visit, Injection, Procedure, Consumable, Tariff, Payroll
    messaging/       # SmsTemplate, SmsCampaign, SmsMessage (Mediana + NullProvider)
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
.\.venv\Scripts\python.exe manage.py seed_catalog    # global ADA catalogs (idempotent)
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
**read-only** and merges them into one `clinic`. v1 scope: clinic + users (both
apps, deduped by username) + patients (webapp.patients ⋈ specialist.patient_links
by national_id, retiring the accounting_bridge) + wallet balance. Verified
idempotent against the real DBs. **TODO (later loops):** chronic records,
accounting rows, SMS, tariffs; proper Jalali↔Gregorian + Tehran→UTC conversion.

## Open scaffold decisions

- **CSRF** for cookie-session POSTs (login/logout) — hardening follow-up.
- **`drug` reference dataset** source (Epic 1) — see `docs/DATA_MODEL.md` §8.

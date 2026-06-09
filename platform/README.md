# platform/ — Cloud SaaS (Django + django-ninja + PostgreSQL)

This is the **Evolve-not-Rewrite destination** for the two Flask apps
(`webapp/`, `specialist_clinic/`). It is a **separate, additive** Django project:
building it does **not** touch the running Flask apps (ports 8080 / 8090). See
[`../docs/TECH_STACK.md`](../docs/TECH_STACK.md) and
[`../docs/DATA_MODEL.md`](../docs/DATA_MODEL.md) for the *why*.

> Status: **v0.3 scaffold** — all 8 modules from DATA_MODEL §2 modelled (~40
> models), RLS multi-tenancy wired across every tenant table, django-ninja API
> root + patients/chronic routers, idempotent global-catalog seed + clinic
> bootstrap commands, `manage.py check` clean, all migrations apply.
> Not yet runnable as a product (no auth/login flow yet, no SQLite->Postgres ETL).

## Layout (modular monolith)

```
platform/
  config/            # Django project: settings, urls, ninja api root, wsgi/asgi
    api.py           # NinjaAPI: /api/health + /api/patients + /api/chronic
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

## Open scaffold decisions (resolve in upcoming loops)

- **Auth integration:** `AppUser` is currently a plain model preserving the
  existing bcrypt + 5-fail/15-min-lockout semantics. Decide whether to make it
  the Django `AUTH_USER_MODEL` (subclass `AbstractBaseUser`) or keep custom
  session auth. The middleware already reads `request.user.clinic_id` first,
  falling back to `session['clinic_id']`.
- **Login vs. RLS ordering:** login must resolve the clinic (by slug/subdomain)
  and set the tenant GUC *before* querying `app_user`, since `app_user` is itself
  RLS-protected.
- **`drug` reference dataset** source (Epic 1) — see `docs/DATA_MODEL.md` §8.

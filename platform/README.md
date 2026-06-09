# platform/ — Cloud SaaS (Django + django-ninja + PostgreSQL)

This is the **Evolve-not-Rewrite destination** for the two Flask apps
(`webapp/`, `specialist_clinic/`). It is a **separate, additive** Django project:
building it does **not** touch the running Flask apps (ports 8080 / 8090). See
[`../docs/TECH_STACK.md`](../docs/TECH_STACK.md) and
[`../docs/DATA_MODEL.md`](../docs/DATA_MODEL.md) for the *why*.

> Status: **v0.1 scaffold** — identity / patients / chronic modules modelled,
> RLS multi-tenancy wired, `manage.py check` clean, all migrations apply.
> Not yet runnable as a product (no auth flow, no API routers, no data ETL).

## Layout (modular monolith)

```
platform/
  config/            # Django project: settings, urls, ninja api root, wsgi/asgi
    api.py           # NinjaAPI instance (mount module routers here)
  apps/
    common/          # base models (UUID/Tenant/Catalog), RLS middleware + 0001_rls
    identity/        # Clinic (tenant), AppUser, UserShift
    patients/        # Patient (unified webapp.patients + specialist.patient_links)
    chronic/         # ADA engine catalogs + per-patient clinical records + wallet
  requirements.txt
  .env.example
```

Module boundaries mirror `docs/DATA_MODEL.md` §2. `billing`, `rx`, `accounting`,
`messaging` apps come in later loops.

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
.\.venv\Scripts\python.exe manage.py runserver       # GET /api/health -> {"status":"ok"}
```

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

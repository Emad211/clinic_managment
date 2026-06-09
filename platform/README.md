# platform/ — Cloud SaaS (Django + django-ninja + PostgreSQL)

This is the **Evolve-not-Rewrite destination** for the two Flask apps
(`webapp/`, `specialist_clinic/`). It is a **separate, additive** Django project:
building it does **not** touch the running Flask apps (ports 8080 / 8090). See
[`../docs/TECH_STACK.md`](../docs/TECH_STACK.md) and
[`../docs/DATA_MODEL.md`](../docs/DATA_MODEL.md) for the *why*.

> Status: **v0.12 scaffold — demoable** — all 8 modules from DATA_MODEL §2
> modelled (~40 models), RLS multi-tenancy, django-ninja API (session login +
> authz-guarded routers), bcrypt + 5-fail/15-min lockout, a **full ETL** (users +
> merged patients + per-patient vitals/meds/conditions/flags/followups) + a
> **clinical-catalog ETL** (real 57 ADA rules), the **ported rule engine** (live
> decision support), a **web frontend** with the three core chronic workflows
> (Snapshot / ADA suggestions+acknowledge / recall worklist), AND the
> **e-prescription WebView-bridge workflow** (Epic 1: compose → portal → register
> + InsurerLog audit). All verified end-to-end on **real** legacy data.
> `manage.py check` clean; **RLS isolation proven on real Postgres** (`verify_rls`);
> **Dockerfile + compose + RLS-correct DB-role split** + GitLab CI; **SMS reminders**
> (Mediana/NullProvider) closing the recall loop; and the **SaaS subscription/billing
> flow** (ZarinPal, simulated-gateway fallback). The full SaaS loop — onboard →
> subscribe → charge → deliver — is in place. Remaining: HTMX, accounting ETL,
> direct-API e-prescription (cert track).

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
per-clinic overrides. Policies use `nullif(current_setting('app.current_clinic',
true), '')::uuid` so an unset **or empty** GUC denies-by-default (a bare `::uuid`
cast on `''` would raise).

**`manage.py verify_rls`** proves isolation on real PostgreSQL: it creates a
non-superuser `rls_app` role + two throwaway clinics and asserts deny-by-default
(unset & empty GUC → 0 rows), A/B isolation, and cross-tenant write rejection.
Verified against `pgvector/pgvector:pg16`. No-op on SQLite. **Run it against the
production Postgres before launch.**

## Setup & verify

**Tests:** `python -m pytest` — 79 tests (auth/lockout, clinical-licensing gate,
audit trail, security-hardening regressions, accounting generalization + invoice
pricing service + reception desk UI + financial reports, rule engine + DSL,
billing + SMS providers, web flows + accountability, e-prescription workflow,
recall worklist + SMS reminder, wallet ledger, knowledge-pipeline client) on
in-memory SQLite via `config/settings_test`. Runs in CI alongside `verify_rls`.

**Security:** a multi-agent adversarial audit hardened the platform (10 fixes:
prescription-content license gate + state-machine, billing fail-closed in prod,
SECRET_KEY prod hard-fail, session-key rotation, web `is_active` revocation,
HSTS-on-by-default, login enumeration hardening, payment plan-binding + row-lock).
RLS/multi-tenancy and XSS surfaces held with zero findings. See
[`../docs/SECURITY.md`](../docs/SECURITY.md).

**Knowledge integration:** `apps/common/knowledge.py` calls the `ai_service`
knowledge pipeline (`/knowledge/*`) to enrich the patient page with ICD-11
crosswalk for conditions. Set `AI_SERVICE_URL` to enable; unset → graceful
no-op (the moat feeding the product, but the clinic app never depends on it).

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
.\.venv\Scripts\python.exe manage.py seed_plans      # subscription plans (free/clinic/multi)
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

## Deployment (`Dockerfile`, `docker-compose.yml`, `deploy/db-init.sql`)

Production image: `python:3.13-slim` + gunicorn, static served by WhiteNoise
(`collectstatic` at build). From inside Iran, pass mirrors (Docker Hub + PyPI are
often blocked):

```bash
docker build \
  --build-arg PY=docker.arvancloud.ir/python:3.13-slim \
  --build-arg PIP_INDEX_URL=https://mirror-pypi.runflare.com/simple \
  -t clinic-platform .
docker compose up        # local stack: pgvector + web on :8000
```

**RLS-correct DB-role split (critical — see `verify_rls`):** the app process
connects as `clinic_app` (NOSUPERUSER **NOBYPASSRLS**, created by
`deploy/db-init.sql`) so RLS actually applies; migrations + global seeding run as
the privileged `postgres` role. `entrypoint.sh` enforces this: it migrates/seeds
with `ADMIN_DATABASE_URL`, then starts gunicorn with the unprivileged
`DATABASE_URL`. In production use **managed Postgres** (Arvan/Liara) and create
the two roles there. `manage.py check --deploy` is clean apart from the expected
SECRET_KEY / TLS-redirect notes (set a strong key + `DJANGO_SSL_REDIRECT` in prod).

## Billing (`apps/billing/`)

SaaS subscription via ZarinPal (`services.py`): `subscribe()` creates a pending
`Payment` + a gateway URL; the user pays; the callback `confirm_payment()`
verifies and activates/extends the `Subscription`. Free plans activate instantly.
With no `ZARINPAL_MERCHANT_ID` a `SimulatedGateway` auto-approves (dev/CI), same
pattern as the SMS NullProvider; set the merchant id (+ `ZARINPAL_SANDBOX=1` for
testing) for the real API. `manage.py seed_plans` seeds free/clinic/multi. UI at
`/billing/`. Verified end-to-end (paid → paid+active; free → instant).

## Web frontend (`apps/web/`)

Minimal RTL, server-rendered Django templates — the demoable wedge. Login lands
on `/dashboard/` (clinic-at-a-glance KPIs: patients, open/overdue follow-ups,
registered prescriptions, SMS sent, acknowledged suggestions + an overdue
preview + subscription status). Then the three core chronic workflows:
`/patients/` (search) → `/patients/<id>/`
(One-Page Snapshot + grouped ADA suggestions w/ "تأیید با پزشک" disclaimer), and
`/worklist/` (recall/follow-up worklist split overdue/today/upcoming, mark-done **+
📲 SMS reminder** per row — Mediana with NullProvider fallback + a compliance
rewrite of banned promo words; `apps/messaging/services.py`). The patient page
also has a **wallet** panel (append-only credit/debit ledger — the lawful
substitute for discount/free; balance can't go negative). Plus the
**e-prescription** flow (Epic 1, EPRESCRIPTION.md path A): from a patient,
start a draft → `/rx/<id>/` composes items and shows the **WebView bridge** (opens
the official insurer portal `ep.tamin.ir` / `eservices.ihio.gov.ir`) → record the
returned tracking code to mark it registered. Every step writes an `InsurerLog`
audit row. (The literal portal embed is a browser concern; direct-API integration
is the parallel cert track.) Login follows the RLS-correct ordering and reuses the
same session keys as the API. RTL/Jalali presentation filters
(`apps/web/templatetags/web_extras.py`: `fa_num`, `jalali`, `rial`) render Persian
digits + Jalali dates throughout.
Each suggestion has a **تأیید (acknowledge)** action: the physician confirms it
and an append-only `SuggestionLog` row is written (rule_code, severity, message,
acknowledged_by, acknowledged_at) — the safety/legal backbone ("suggests,
physician decides, logged"). Idempotent; the page then shows ✓ تأیید پزشک.
Verified end-to-end on real data (TEST0008 → 26 suggestions, ack logged). HTMX
interactivity (live search, inline ack without full reload) is the next polish.

**Clinical-licensing gate (REGULATORY §1/§6).** The two "physician decides"
actions — acknowledging a suggestion and issuing an e-prescription — are gated to
a user who **holds a نظام‌پزشکی license**: `AppUser.can_practice_clinically()`
(active + non-empty `medical_license_no`), enforced by the `clinical_license_required`
web decorator and `common.auth.require_clinical_license` (ninja). Clinical-role
accounts (doctor/nurse) must record a license number (`AppUser.clean()`). The UI
locks the ack/rx controls for unlicensed users (🔒) and shows a banner if they
POST anyway. `bootstrap_clinic --license <no>` sets the owner-manager's license so
a small-clinic owner-physician can sign. Role doesn't further restrict — a
licensed manager-physician may sign; an unlicensed reception/manager may not.

**Audit trail (REGULATORY §6 — accountability / ممیزی).** Every state-changing
action writes an append-only row to `activity_log` via
`apps/common/activity.log_activity(clinic, actor, action, summary, …)`: suggestion
acknowledge, rx create/register, wallet credit/debit, followup done/remind. It's
**best-effort** — the insert is savepoint-isolated, so a logging failure never
rolls back the primary action. A **manager-only `/activity/`** page renders the
filterable trail. The table is RLS-protected like any tenant table (migration
`0004_activitylog_rls`, asserted by `verify_rls`). Wiring login/logout and the
accounting module into the trail is the remaining coverage.

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

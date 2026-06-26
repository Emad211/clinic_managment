# halqe — Unified Platform Vertical Slice 1

Django 6 + django-ninja + Postgres. Schema owned by SQL slices (managed=False throughout).

## Setup

```powershell
# From repo root — Python 3.13 required
cd halqe
"C:\Users\Emad Karimi\AppData\Local\Programs\Python\Python313\python.exe" -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Apply schema to a DB

```powershell
# Requires Docker container halqe_pg_validate running on localhost:55432
.\.venv\Scripts\python manage.py apply_schema
# Or create a throwaway DB first:
# docker exec halqe_pg_validate psql -U postgres -c "CREATE DATABASE halqe_app"
```

## Run tests

```powershell
# Docker container must be running
PYTHONIOENCODING=utf-8 .\.venv\Scripts\python -m pytest tests/ -v
```

## Endpoints

- `GET /api/v1/patients/{uuid}` — patient demographics (AccountingReadPort)
- `GET /api/v1/patients/{uuid}/vitals/latest` — latest VitalReading per type

## Architecture decisions

- `accounting` app_label → always reads via `accounting_read` alias; writes raise `PermissionError` (router + DB GRANT).
- `clinical` + `platform_core` → `default` alias.
- `accounting_port.port.get_patient_by_uuid` is the ONLY path from clinical into accounting.
- `managed=False` everywhere — `apply_schema` applies the SQL slices in numeric order.
- `USE_TZ=True`, `TIME_ZONE='Asia/Tehran'`.

## Project structure

```
config/
  api_base.py     NinjaAPI instance + JWT auth + Http404 handler (shared; imports no router)
  api.py          thin mount: imports every domain router + api.add_router(...) + test re-exports
  settings.py     SCHEMA_SLICE_DIR → db/schema/ (env-overridable)
clinical/
  api/            one ninja Router per domain (auth, patients, vitals, suggestions, worklist,
                  encounters, control_room, doctor_queue, engagement, manager, patient_card,
                  self_report) + _shared.py (cross-domain helpers/DTOs)
  *_service.py    business logic / engines (rule_engine, engagement, cohort_outcome, …)
  models.py       managed=False models (one per schema table)
platform_core/    auth, tenant GUC, onboarding, health, settings accessor
accounting_port/  the ONLY read-only path into the accounting schema
db/schema/        schema_pg_slice*.sql — the source-of-truth DDL (applied by apply_schema)
web/src/lib/api/  per-domain API client modules (_core + 12 domains); api.ts re-exports them (barrel)
```

> The API surface was decomposed from a single 4659-line `config/api.py` into per-domain
> routers (cleanup steps 3–7); `web/src/lib/api.ts` was likewise split into a barrel over
> `web/src/lib/api/` (step 8). Every URL/auth contract was preserved byte-for-byte.

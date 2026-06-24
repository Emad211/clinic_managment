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
- `managed=False` everywhere — `apply_schema` applies the 7 SQL slices.
- `USE_TZ=True`, `TIME_ZONE='Asia/Tehran'`.

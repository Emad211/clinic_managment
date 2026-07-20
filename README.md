# Clinic Management — Monorepo

Software for an Iranian clinic, RTL/Jalali throughout, Persian UI. The repository
holds two independent production Flask + SQLite desktop apps.

| Tree | What it is | Stack | Port | Status |
|------|-----------|-------|------|--------|
| [`webapp/`](webapp/) | **Hesabdari (Accounting)** — reception, invoicing, visits, injections, procedures, payroll, reports | Flask + SQLite (`clinic_new.db`) | 8080 | production |
| [`specialist_clinic/`](specialist_clinic/) | **Specialist Clinic** — chronic-disease management (diabetes / HTN / HLD / CKD / thyroid): vitals, the suggestion-only clinical engine, appointments, the engagement engine, Control Room, SMS | Flask + SQLite (`specialist.db`) | 8090 | production |

The two Flask apps are **independent processes** with separate databases, linked
only by patient `national_id`. `specialist_clinic` reads accounting demographics
and revenue **live and read-only** through `specialist_clinic/src/adapters/accounting_bridge.py`
(SQLite `mode=ro`). **The accounting DB is never written from the specialist app.**

## Where to look

- **Working agreements & architecture rules:** [`CLAUDE.md`](CLAUDE.md) (repo-wide) and the
  nearest per-app `CLAUDE.md` ([`specialist_clinic/CLAUDE.md`](specialist_clinic/CLAUDE.md)).
- **Specialist-clinic plans & references:** [`specialist_clinic/docs/`](specialist_clinic/docs/)
  (record redesign, engagement engine, clinical reference, Kavenegar reference, …).

## Running (quick pointers)

```powershell
# Accounting (webapp) — http://127.0.0.1:8080
cd webapp; python start.py

# Specialist Clinic — http://127.0.0.1:8090 (login admin/admin)
cd specialist_clinic; .\.venv\Scripts\python.exe start.py

```

See each app's `README.md` / `CLAUDE.md` for seeding, tests, and building. There is
**no shared dependency** between the apps — each runs and builds on its own.

## Conventions (shared across both apps)

Strict `api → services → adapters` layering · Jalali dates + Iran local time
(UTC+3:30) everywhere · suggestion-only clinical decision support
("پیشنهاد — تأیید با پزشک") · additive idempotent migrations · offline by design
(no CDNs) · `bcrypt` auth with lockout. The detail lives in the `CLAUDE.md` files.

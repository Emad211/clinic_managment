# سامانهٔ نرم‌افزار پزشکی — Clinic Co-pilot + Knowledge Platform

An Iranian medical-software startup: a **chronic-disease co-pilot** for clinics
(diabetes/hypertension) with e-prescription, evolving into a **clinical-knowledge
platform**. The product is RTL/Jalali throughout; most domain language is Persian.

> **Strategy, market research, and roadmap live in [`docs/`](docs/README.md)** —
> start at [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md). For *how the code works*,
> see [`CLAUDE.md`](CLAUDE.md).

## The 3-rung ladder (strategy)

1. **Revenue wedge** — a sellable chronic-disease co-pilot + e-prescription
   (the market gap no Iranian clinic-software competitor fills).
2. **Differentiation** — a physician-facing **clinical-intelligence layer** (the
   ADA rule engine generalised).
3. **Long-term moat** — a **clinical-knowledge platform** fed by a multi-agent
   **knowledge-extraction pipeline** (Phase-0), built in parallel.

Safety principle in every clinical feature: **the system suggests, it does not
decide** ("پیشنهاد — تأیید با پزشک"), gated to licensed users, logged.

## Repository map (four trees)

| Path | What | Stack | Status |
|---|---|---|---|
| [`webapp/`](webapp/) | **Accounting** desktop app (reception, invoicing, payroll) | Flask + SQLite | in production (legacy) |
| [`specialist_clinic/`](specialist_clinic/) | **Chronic-disease** desktop app (vitals, ADA decision support, SMS) | Flask + SQLite | in production (legacy) |
| [`platform/`](platform/README.md) | **Cloud SaaS** — the Evolve target unifying both apps | Django + django-ninja + PostgreSQL | feature-complete scaffold |
| [`ai_service/`](ai_service/README.md) | **Knowledge-extraction pipeline** (the moat) | FastAPI + SQLModel (+ arq/pgvector) | all 9 layers, end-to-end |
| [`docs/`](docs/README.md) | Strategy, market, tech-stack, data-model, pipeline, features | — | living |

The two **Flask apps** are the *current* production state (desktop, SQLite). The
**platform** is the *target* — a cloud, multi-tenant SaaS reached by **evolving**
the layered code (keep `services/`+`domain/`, swap SQLite→Postgres, Flask→Django),
**not** rewriting. `ai_service` is the separate Phase-0 pipeline.

## What's built (platform + pipeline)

**`platform/`** — unified multi-tenant SaaS, verified end-to-end on the real
migrated data:
- **PostgreSQL Row-Level Security** multi-tenancy — *proven* on real Postgres
  (`manage.py verify_rls`: deny-by-default, A/B isolation, cross-tenant write
  rejection).
- Auth (bcrypt + 5-fail/15-min lockout) + authz-guarded django-ninja API.
- The **chronic co-pilot**: One-Page Snapshot · ADA **rule engine** (57 rules,
  ported) → live suggestions + physician acknowledgement (logged) · recall
  worklist · SMS reminders.
- **Clinical-licensing gate** (REGULATORY §1/§6): signing a clinical decision
  (acknowledge a suggestion, e-prescribe) requires a نظام‌پزشکی license number.
- **Append-only audit trail** (`ActivityLog` + manager-only `/activity/` page):
  every state-changing action is logged for accountability (REGULATORY §6).
- **Hardened by a multi-agent adversarial security audit** — 10 fixes across
  auth, payments, the license gate and config; RLS/multi-tenancy + XSS held with
  zero findings (`docs/SECURITY.md`).
- **E-prescription** (Epic 1) WebView-bridge workflow + insurer audit log.
- **SaaS billing** (ZarinPal) — subscribe → pay → activate.
- Wallet ledger, manager dashboard, Persian/Jalali UI.
- **Docker + GitLab CI** with the RLS-correct DB-role split.

**`ai_service/`** — the knowledge pipeline, all 9 layers as a tested vertical
slice: Model Gateway (AvalAI + NullModel) → ingestion (hash dedup) → PyMuPDF
parsing → extraction (anchored claims) → the **critical verification gate**
(ungrounded/hallucinated claims → human review) → ontology (ICD-11/MeSH/INN/ATC)
→ graph → MCP-style serving, with a Gold-Set benchmark harness. The platform calls
it to enrich the clinical UI (moat → product), degrading gracefully when absent.

## Quickstart

```powershell
# Legacy chronic-disease app (known-good venv, Python 3.13)
cd specialist_clinic; .\.venv\Scripts\python.exe start.py    # http://127.0.0.1:8090  admin/admin

# Cloud platform (Django) — see platform/README.md
cd platform; .\.venv\Scripts\python.exe manage.py migrate; .\.venv\Scripts\python.exe manage.py runserver

# Knowledge pipeline (FastAPI) — see ai_service/README.md
cd ai_service; .\.venv\Scripts\uvicorn.exe app.main:app --reload   # GET /health
```

## Tests

`platform/` (58) + `ai_service/` (22) = **80 automated tests**, plus the Postgres
RLS proof (`verify_rls`). All run in CI (`.gitlab-ci.yml`).

```powershell
cd platform   ; .\.venv\Scripts\python.exe -m pytest
cd ai_service ; .\.venv\Scripts\python.exe -m pytest
```

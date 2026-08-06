# Specialist Clinic Frontend — Execution Memory

**Purpose:** persistent handoff memory for every implementation turn  
**Must be updated together with:** `SPECIALIST_CLINIC_FRONTEND_PLAN.md`  
**Last updated:** 2026-08-06 19:11 +03:30

## Non-negotiable product intent

The product exists to improve exactly five outcomes:

- follow-up;
- automation;
- revenue;
- patient growth;
- accuracy.

The user explicitly does **not** want product effort spent on security ceremony, signatures, commitments, pledges or similar administrative friction.

## Repository and branch

- Repository: `Emad211/clinic_managment`
- Active branch: `feat/specialist-clinic-growth-automation-v1`
- Parent branch: `feat/frontend-automation-v2-patient-workspace`
- Accounting application/database must remain unchanged and read-only from specialist-clinic code.

## Proven parent foundations

### Work Center

The parent chain already contains:

- real start-next;
- claim and auto-next;
- defer and appointment booking;
- administrative and evidence-based completion;
- safe templated message queue;
- progressive drawer/full-page fallback;
- Control Room absorption.

Last broad checkpoint before the current no-broad-test policy: 884 Specialist tests and Accounting success. Do not rerun broad suites.

### Appointment automation

The parent chain already contains:

- Today/List views;
- suggested time;
- invalid-form preservation;
- patient context and safe return;
- Work Center continuity.

Last broad checkpoint before the current policy: 891 Specialist tests and Accounting success. Do not rerun broad suites.

## Current branch implementation

### Stage 1 — Patient 360

Implemented:

- native five-tab server-rendered Workspace;
- canonical `/patients/<pid>/workspace?tab=...` route;
- `legacy=1` fallback;
- catalog-backed medication route and enhancement JS;
- catalog-backed lab route with canonical unit/reference range;
- 422 re-render with submitted values preserved;
- active/inactive medication history;
- last contact, recent message, no-show, next appointment and open-work summaries;
- source-backed specialist billed/collected/outstanding summary;
- converted Lead source/referrer in Patient 360;
- UX language shifted from signature/document ceremony to visit/service outcomes.

Focused tests written:

- `tests/test_frontend_growth_patient_workspace.py`
- `tests/test_frontend_growth_patient_workspace_catalogs.py`

These tests have **not been run** in this execution.

### Stage 2 — Lead pipeline

Implemented:

- additive tables `growth_leads` and `growth_lead_events`;
- leads remain separate from patients until conversion;
- source/referrer/interest/owner/status/next-action fields;
- lifecycle `NEW → CONTACTED → APPOINTMENT_BOOKED → ATTENDED → CONVERTED` or `LOST`;
- structured lost reason;
- duplicate open-phone suppression;
- list, quick-create and one-page action Workspace;
- explicit conversion to existing/new patient;
- converted appointment preserved as scheduled or done depending on attendance evidence;
- source/referrer retained for Patient 360 and revenue attribution.

Key files:

- `src/adapters/sqlite/lead_pipeline_schema.py`
- `src/adapters/sqlite/leads_repo.py`
- `src/services/lead_pipeline_service.py`
- `src/api/leads.py`
- `src/templates/leads/index.html`
- `src/templates/leads/detail.html`
- `src/static/css/leads-growth-v1.css`

Focused test written and **not run**:

- `tests/test_frontend_growth_lead_pipeline.py`

### Stage 3 — Growth/revenue cockpit

Implemented:

- manager route `/growth/`;
- today and month billed/collected/outstanding specialist values;
- lead and specialist financial funnels;
- no-show/cancellation opportunity counts;
- collected revenue grouped by converted Lead source;
- existing patients separated from known Lead sources;
- no historical accounting revenue without explicit specialist lineage;
- forecast withheld when priced pipeline evidence is missing.

Key files:

- `src/services/growth_revenue_cockpit_service.py`
- `src/api/growth.py`
- `src/templates/growth/cockpit.html`
- `src/static/css/growth-cockpit-v1.css`

Focused test written and **not run**:

- `tests/test_frontend_growth_revenue_cockpit.py`

### Stage 4 — Growth automations

Implemented:

- idempotent No-show recovery;
- cancellation recovery when no replacement appointment exists;
- inactive-patient recall with configurable threshold;
- exclusion of patients with a future appointment;
- preview-first `/growth/automation` page;
- generated work linked to source and appointment and sent to Work Center.

Key file:

- `src/services/growth_automation_service.py`

Focused test written and **not run**:

- `tests/test_frontend_growth_automation.py`

### Stage 5 — Closed loop

Implemented explicit rules only; no generic workflow engine:

- recovery/recall task closes on valid future replacement appointment;
- recovery/recall task closes on completed visit after task creation;
- stale past scheduled appointment is not accepted as evidence;
- missing specialist financial observation creates a Work Center exception;
- observation arrival closes that exception;
- unpaid/partial collection creates a collection task;
- collected/no-billable evidence closes collection task;
- preview and manual reconciliation on the automation page.

Key file:

- `src/services/growth_closed_loop_service.py`

Focused test written and **not run**:

- `tests/test_frontend_growth_closed_loop.py`

## Registration and navigation state

`src/api/ext.py` currently registers:

- Work Center outcome routes;
- Patient Workspace and catalog-backed mutations;
- Lead pipeline and sidebar context counts;
- Growth/revenue/automation routes.

Current direct access:

- Leads: `/leads/`
- Growth cockpit: `/growth/`
- Growth automation/closed loop: `/growth/automation`

Stable sidebar/Home integration is still pending Stage 7. Patient Workspace Actions already links to Leads.

## Test policy and current evidence

- All new focused tests were written.
- **No new focused tests have been executed yet.**
- **No broad/full Specialist or Accounting suite was executed.**
- No PR was opened to trigger broad CI.
- Do not claim runtime success for the new growth branch until focused tests or local browser smoke run.

## Known remaining risks/gaps

- focused tests may expose route/schema/template mismatches because they are currently unexecuted;
- some advanced Patient Workspace forms still depend on legacy page;
- lead due items are not yet merged into Home/Unified exception view;
- waitlist/empty-slot fill is not implemented;
- referral loop and campaign automation are not implemented;
- messaging playbooks and automatic stop conditions are not implemented;
- service/referral catalogs and data-quality queue remain;
- sidebar/Home integration and mobile browser smoke remain.

## Current exact work order

1. Implement waitlist/empty-slot fill and referral loop.
2. Add governed No-show/recall message playbooks with stop conditions.
3. Add point-of-use data quality/reconciliation exceptions.
4. Integrate Leads/Growth/Automation into sidebar and manager Home.
5. Run only the smallest focused tests/browser smoke needed to resolve concrete runtime errors; never run broad suites.
6. Update both this file and the plan again in the next turn.

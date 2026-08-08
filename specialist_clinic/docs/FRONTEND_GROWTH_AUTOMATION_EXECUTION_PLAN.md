# Frontend Growth Automation — Execution Plan

**Status:** active — Stage 3 hardening, catalog accuracy restored; focused proof still pending  
**Branch:** `feat/frontend-automation-v2-patient-workspace`  
**Last verified:** 2026-08-08  
**Primary product goals:** follow-up, automation, revenue growth, patient growth, accuracy.

## Product rules

1. Every frontend change must improve at least one of the five product goals above.
2. Do not spend product time on signatures, commitments, policy ceremony or security UX unless an existing runtime path is broken by the current frontend work.
3. Prefer existing repositories, services and mutation endpoints. Add a backend seam only when required for a real server-authoritative workflow.
4. Do not fake persistence or business outcomes in the browser.
5. Write focused tests for touched behavior. **Do not run broad/full Specialist Clinic or Accounting suites during implementation.** Broad suites are reserved for an explicitly requested final checkpoint.
6. Preserve progressive enhancement, 360px usability, keyboard access and role-aware actions.
7. Keep technical evidence, internal IDs and architecture vocabulary out of the primary staff workflow.

## Proven baseline

### Stage 1 — Work Center

- Branch: `feat/frontend-automation-v2-work-center`
- Proven SHA: `d4797288ac1d11035982b8a6cd7ca122b28f1b9f`
- Proven checkpoint from prior work: Specialist `884 passed`, Accounting passed.
- Result: Handle/claim orchestration, drawer with full-page fallback, structured contact, deferral, booking, message queueing, definitive completion, auto-next and Control Room absorption.

### Stage 2 — Appointment Automation

- Branch: `feat/frontend-automation-v2-appointments`
- Proven SHA: `c57bf1b874b467cefbfea1e63fce17e1a72c9b5e`
- Proven checkpoint from prior work: Specialist `891 passed`, Accounting passed.
- Result: Today/List, conservative time default, invalid-form preservation, patient context, safe return URL and Work Center continuity.

### Stage 3 — Native Patient Workspace

Active branch:

`feat/frontend-automation-v2-patient-workspace`

Current branch state verified after this development turn:

- Branch remains ahead-only of the Stage 2 proven SHA and is 0 behind.
- Native five-tab server-rendered Workspace remains canonical.
- Legacy `/patients/<pid>` compatibility redirect and mutation return-to-tab behavior remain in place.
- The pre-existing Stage-2-era file `tests/test_frontend_automation_patient_workspace_v2.py` was found to test an obsolete JavaScript-composed Workspace. It has now been replaced with native runtime tests for canonical redirect, all five tabs, catalog controls and mutation continuity.
- Medication entry now selects the drug name from `drug_catalog`; class is required; a progressive class → drug → standard-dose helper uses the catalog while the base select remains usable without JavaScript.
- Lab entry now posts `catalog_test_key`; the existing `/vitals/<pid>/lab/add` endpoint resolves canonical test name, unit and reference range on the server before persistence. Existing batch and legacy contracts remain available.
- Visit-document count was removed from the primary patient header KPI.
- Messaging-consent controls were moved under advanced details rather than being shown as normal daily work.
- Final visit documents were demoted to a collapsed secondary section; appointment, visit, open follow-up and service facts are primary.
- `FRONTEND_AUTOMATION_V2_EXECUTION_ROADMAP.md` is now aligned with Stage 2 proven / Stage 3 active status and points post-Stage-3 sequencing to this growth plan.

Stage 3 still needs:

- focused execution of `tests/test_frontend_automation_patient_workspace_v2.py` in a runnable checkout;
- fixes for any real failures from that focused test only;
- recent contact/outcome and return/retention context in Summary/Actions using existing data where available;
- minimal decoupling of Patient Workspace registration from `src/api/ext.py`;
- focused browser acceptance for desktop, 360px and keyboard.

## Seven implementation stages

### 1. Stage 3 hardening — accuracy and action completeness

Goal: finish Patient Workspace without introducing growth scope prematurely.

Completed in current implementation:

- native five-tab route and Jinja structure;
- focused native test coverage written;
- catalog-aware medication identity and progressive dose guidance;
- server-authoritative lab catalog identity;
- document/signature ceremony demoted from primary patient KPIs;
- messaging-consent controls demoted from the normal action flow;
- old V2 roadmap corrected.

Remaining:

- execute focused Stage 3 tests and repair only observed failures;
- improve Summary/Actions with recent contact, clearer return context and next-action evidence;
- decouple Patient Workspace registration from the prescription-extension blueprint;
- perform focused visual/browser verification.

Exit: Stage 3 is focused-test green, browser-smoke verified, and does not reduce clinical data accuracy compared with the legacy patient page.

### 2. Revenue Cockpit and operational value visibility

Goal: make revenue visible and actionable without creating a second accounting system.

- Build manager-facing revenue/growth summary from existing specialist financial lineage/funnel and read-only accounting data.
- Show collected/attributed value where provable, upcoming appointment value where provable, and lost opportunity counts for cancellation/no-show where data exists.
- Separate proven revenue from estimates; never present booking-rate as revenue conversion.
- Add drill-down to the patient/work item that generated the number.

Exit: manager can see which operational work is producing appointments, visits and provable revenue.

### 3. Patient lifecycle and acquisition source

Goal: support patient growth rather than only managing already-enrolled patients.

- Reuse existing patient/campaign structures where possible and add the smallest lead/source seam only if absent.
- Track source/referrer, lifecycle state and lost reason.
- Present a lightweight pipeline: new lead → contacted → booked → arrived → converted/returned/lost.
- Keep the patient record as the canonical identity once a lead becomes a patient.

Exit: new-patient acquisition can be measured through booking and arrival instead of disappearing before registration.

### 4. Outcome attribution loop

Goal: connect work to business outcome.

- Link follow-up/contact/campaign actions to appointment, attendance, service lineage and provable financial outcome when existing identifiers support it.
- Add staff/playbook/source outcome reporting without inventing causal attribution.
- Make successful/failed outcomes visible in Work Center and manager views.

Exit: the product can answer which work produced booking, attendance and revenue, with explicit evidence boundaries.

### 5. Automation playbooks

Goal: move from click reduction to routine work being performed automatically.

Priority playbooks:

- lapsed-patient recall;
- no-show follow-up;
- cancellation/waitlist refill when schedule data supports it;
- pre/post-visit reminder chains;
- refill/lab follow-up from existing authoritative tasks;
- automatic stop conditions after booking/attendance/definitive completion.

Each playbook must use existing consent/provider/business rules as backend truth, while the frontend shows exceptions rather than policy ceremony.

Exit: staff mostly handle exceptions and high-value conversations, not repetitive queue creation.

### 6. Patient 360 business context and retention

Goal: turn Patient Workspace into a retention and return cockpit.

Add, where provable:

- last contact + outcome;
- exact next action + due time;
- last visit and next appointment;
- no-show/cancellation history;
- referral/source;
- repeat-visit/retention signal;
- provable patient value / outstanding balance summaries;
- recent messages/responses;
- current opportunity to return or complete care.

Exit: staff can understand clinical context and commercial/retention context without leaving the patient workspace.

### 7. Integration proof and browser acceptance

Goal: verify the product as used, not only as rendered templates.

- Run only focused tests throughout implementation.
- At final integration, perform explicit browser acceptance for Work Center, Patient Workspace, Appointments, Doctor Queue/Encounter, manager growth/revenue surfaces and mobile navigation.
- Verify 360px layout, keyboard journeys, console/network failures and representative click budgets.
- Run broad suites only when the owner explicitly authorizes the final checkpoint.

Exit: no high-severity browser defect remains and the five product goals are supported by real workflows and measured evidence.

## Immediate continuation order

1. Run only `tests/test_frontend_automation_patient_workspace_v2.py` in a runnable checkout; do not run a broad suite.
2. Fix only failures observed in that focused file and directly related code.
3. Add recent contact/outcome and stronger return/retention context to Patient Workspace Summary/Actions from existing authoritative data.
4. Decouple Patient Workspace registration from `src/api/ext.py` with the smallest app-factory change.
5. Perform focused desktop/360px/keyboard browser verification when a browser-capable checkout is available.
6. Once Stage 3 is focused-test green, start Revenue Cockpit work; do not jump to Encounter Autosave first.

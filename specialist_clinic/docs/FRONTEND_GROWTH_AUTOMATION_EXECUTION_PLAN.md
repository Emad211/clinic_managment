# Frontend Growth Automation — Execution Plan

**Status:** active, Stage 3 hardening before growth expansion  
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

- Active branch: `feat/frontend-automation-v2-patient-workspace`
- Verified delta from Stage 2: 15 commits ahead, 10 product files changed, no Stage 3 runtime test file committed yet.
- Implemented: canonical `/patients/<pid>/workspace`, five server-rendered tabs, legacy compatibility redirect, mutation redirect-to-tab behavior, read-only `PatientWorkspaceService`, sticky patient header, responsive CSS, medication history and contextual links.
- Known gaps:
  - `lab_catalog` and `drug_catalog` are loaded but new lab/medication forms still accept key identity fields as free text.
  - Legacy medication UI already had class → drug → dose catalog cascade; Stage 3 currently regresses that accuracy.
  - Patient Workspace still emphasizes encounter documents and technical care artifacts more than return/revenue/business context.
  - Actions still eject the user to several external surfaces instead of completing enough work in patient context.
  - Workspace registration is coupled to the extension blueprint via `ext.py`.
  - `FRONTEND_AUTOMATION_V2_EXECUTION_ROADMAP.md` is stale and still describes Stage 2 as active.

## Seven implementation stages

### 1. Stage 3 hardening — accuracy and action completeness

Goal: finish Patient Workspace without introducing growth scope prematurely.

- Add focused runtime tests for all five tabs, legacy redirect, mutation redirect continuity and role-aware actions.
- Restore catalog-aware medication entry using the existing `drug_catalog` and existing canonical drug identity behavior.
- Restore catalog-aware lab entry using the existing `lab_catalog`, including canonical name/unit defaults where supported by current endpoints.
- Remove or demote document/signature-oriented copy from primary patient KPIs.
- Improve Actions/Summary so next action, recent contact, open work and booking are more directly actionable.
- Decouple Patient Workspace registration from the prescription-extension blueprint when a minimal app-registration seam is available.

Exit: Stage 3 has focused runtime coverage and does not reduce clinical data accuracy compared with the legacy patient page.

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

1. Create Stage 3 focused runtime tests (do not run broad suites).
2. Restore medication catalog cascade/identity.
3. Restore lab catalog selection/defaults.
4. Tighten Patient Workspace summary/actions around return, open work and next action; demote document-oriented KPIs.
5. Run only the new Stage 3 focused test file(s) and directly related existing tests.
6. Update `FRONTEND_AUTOMATION_V2_EXECUTION_ROADMAP.md` to mark Stage 2 proven and Stage 3 active.
7. Only after Stage 3 is focused-test green, begin Revenue Cockpit work.

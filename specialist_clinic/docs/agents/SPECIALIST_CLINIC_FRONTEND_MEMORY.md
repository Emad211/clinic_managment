# Specialist Clinic Frontend — Execution Memory

**Purpose:** persistent handoff memory for every implementation turn  
**Must be updated together with:** `SPECIALIST_CLINIC_FRONTEND_PLAN.md`  
**Last updated:** 2026-08-06 17:53 +03:30

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

## Proven completed foundations

### Stage A — Work Center foundation

On the parent chain, Work Center includes:

- real start-next;
- claim and auto-next;
- defer;
- appointment booking;
- administrative completion;
- evidence-based clinical/plan completion;
- safe templated message queue;
- progressive drawer with full-page fallback;
- Control Room absorption.

The last recorded focused/full checkpoint before the user prohibited broad test runs reported 884 Specialist tests and Accounting success. Do not repeat broad suites during current implementation.

### Stage B — Appointment automation

On the parent chain, appointments include:

- Today/List views;
- suggested times;
- form preservation on validation failure;
- patient context and safe return URL;
- Work Center appointment continuity.

The last recorded checkpoint reported 891 Specialist tests and Accounting success. Do not rerun broad suites.

### Stage C — Patient Workspace in progress

Implemented on parent branch:

- native route `/patients/<pid>/workspace?tab=...`;
- five server-rendered tabs;
- summary, actions, clinical, medications and encounters partials;
- canonical redirect from legacy patient detail;
- explicit `legacy=1` fallback;
- responsive CSS;
- mutation redirect rewriting to preserve the relevant tab;
- active and inactive medication history.

Still incomplete/unproven:

- focused runtime test file was not created because the connector returned a file-create error;
- catalog-backed lab and medication entry must be restored fully;
- all five tabs need focused render/mutation tests;
- Patient 360 still lacks compact last-contact, message, referral/source and attributable value summaries;
- some advanced forms still rely on the legacy page.

## Current exact work order

1. Write focused Patient Workspace runtime tests.
2. Fix failures from those tests only.
3. Restore catalog-aware drug and lab forms.
4. Add Patient 360 contact/referral/value summaries using existing authoritative sources.
5. Update both plan and memory files.
6. Begin lead pipeline only after Stage 1 focused tests pass.

## Test policy

- Write tests for every changed behavior.
- Run only focused tests.
- Never run broad/full Specialist or Accounting suites during this implementation.
- Do not open PRs merely to trigger broad CI.
- Record test commands/results here when available.

## Last action in this turn

- Created the seven-stage growth/automation plan.
- Created this persistent execution memory.
- Created branch `feat/specialist-clinic-growth-automation-v1` from the current Patient Workspace branch.
- Next code action: create focused Patient Workspace tests and repair the native workspace based on actual failures.

# Frontend Growth Automation — Working Memory

**Last updated:** 2026-08-08  
**Active branch:** `feat/frontend-automation-v2-patient-workspace`

## Owner intent

The frontend work is judged against five outcomes:

1. better patient follow-up;
2. more real automation;
3. more revenue;
4. more patients;
5. higher data/clinical workflow accuracy.

Do not optimize the product around signatures, commitments, policy ceremony or security UX. Do not spend implementation cycles on those areas unless a current product flow is directly broken by them.

## Test discipline

- Write tests for new/touched behavior.
- Run focused tests only during implementation.
- Do **not** run broad/full Specialist Clinic or Accounting suites unless the owner explicitly asks for a final checkpoint.
- Prefer shipping code and focused verification over repeatedly running the entire suite.

## Proven development history

### Stage 1 — Work Center

- Branch: `feat/frontend-automation-v2-work-center`
- Proven SHA: `d4797288ac1d11035982b8a6cd7ca122b28f1b9f`
- Prior checkpoint evidence: Specialist 884 passed; Accounting passed.

### Stage 2 — Appointment Automation

- Branch: `feat/frontend-automation-v2-appointments`
- Proven SHA: `c57bf1b874b467cefbfea1e63fce17e1a72c9b5e`
- Prior checkpoint evidence: Specialist 891 passed; Accounting passed.

### Stage 3 — Patient Workspace

- Active branch is 15 commits ahead of Stage 2 before this memory/plan documentation commit series.
- Verified Stage 3 product delta contained 10 files and no committed Stage 3 runtime tests.
- Current implementation has:
  - canonical `/patients/<pid>/workspace` route;
  - five Jinja/server-rendered tabs;
  - legacy detail redirect with `?legacy=1` escape hatch;
  - mutation redirect rewriting back to the relevant workspace tab;
  - read-only `PatientWorkspaceService` using existing repositories/facade;
  - Summary / Actions / Clinical / Meds / Encounters partials;
  - sticky responsive header and 360px-oriented CSS;
  - medication active/inactive history and medication events;
  - patient appointment context and Work Center links.

## Verified gaps

### Accuracy regression

`PatientWorkspaceService` already supplies `lab_catalog` and `drug_catalog`, but the new workspace forms do not consume them for canonical entry.

- New lab entry uses free-text `test_name` and `unit`.
- New medication entry uses free-text `drug_name`, `dose` and schedule.
- Legacy patient page already embeds the drug catalog and supports a class → drug → dose cascade.

Therefore the first product fix is to restore existing catalog-aware behavior, not invent a new subsystem.

### Patient 360 / business context gap

The workspace still overweights technical/encounter artifacts:

- header KPI includes visit-document count;
- Encounters tab foregrounds signed documents and Encounter vocabulary;
- Summary lacks recent contact outcome, acquisition source, cancellation/no-show history, retention signal and provable patient value context;
- several Actions still redirect to other pages instead of finishing the task in patient context.

### Architecture debt

Patient Workspace registration is currently performed from `src/api/ext.py` inside the extension blueprint's `record_once` hook. This is a coupling smell. Fix only with a small registration move; do not start an application-bootstrap rewrite.

### Documentation debt

`docs/FRONTEND_AUTOMATION_V2_EXECUTION_ROADMAP.md` is stale:

- it still says Stage 2 is active;
- its Current continuation section still points to Stage 2;
- Stage 2 is actually proven and Stage 3 is active.

### Browser state

Doctor Queue code currently renders a safe unavailable state instead of crashing when its read-only source fails, and its template contains current / waiting / completed-today sections. Sidebar is role-aware and matches the automation IA. However final visual/browser acceptance is still pending, so do not claim the historical browser defect is fully proven fixed until browser verification is performed.

## Exact next action

1. Add Stage 3 focused runtime tests.
2. Restore catalog-aware medication entry.
3. Restore catalog-aware lab entry/defaults.
4. Tighten Summary/Actions around patient return and open work; demote document-centric copy.
5. Run only focused Stage 3 and directly related tests.
6. Update the old V2 roadmap status.
7. Then start the Revenue Cockpit stage from `FRONTEND_GROWTH_AUTOMATION_EXECUTION_PLAN.md`.

## Persistent guardrails for future turns

- Read this file and `FRONTEND_GROWTH_AUTOMATION_EXECUTION_PLAN.md` before making the next product change.
- Update both files in every development turn with what actually changed, what was verified and the new exact continuation point.
- Never state that a file/test/commit exists until it has been verified in the repository.
- Do not run broad suites by default.
- Keep the five owner outcomes visible in UX decisions: follow-up, automation, revenue, patient growth, accuracy.

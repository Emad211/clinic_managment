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

Verified native implementation:

- canonical `/patients/<pid>/workspace` route;
- five Jinja/server-rendered tabs;
- legacy detail redirect with `?legacy=1` escape hatch;
- mutation redirect rewriting back to the relevant workspace tab;
- read-only `PatientWorkspaceService` using existing repositories/facade;
- Summary / Actions / Clinical / Meds / Encounters partials;
- sticky responsive header and 360px-oriented CSS;
- medication active/inactive history and medication events;
- patient appointment context and Work Center links.

Important historical correction discovered on 2026-08-08:

- `tests/test_frontend_automation_patient_workspace_v2.py` already existed at the Stage 2 SHA.
- It was not valid coverage for the current native Workspace; it asserted an obsolete JavaScript-composed five-tab implementation and assets that the native Stage 3 no longer uses.
- The prior Connector `422: "sha" wasn't supplied` happened because the path existed and needed an update with its real blob SHA, not a create call.
- The stale file has now been replaced with native runtime tests covering canonical redirect, five tabs, catalog-bound forms, server-canonical lab persistence and medication return continuity.

## Changes completed in the 2026-08-08 development turn

### Catalog accuracy

Medication:

- Added `src/static/js/patient-workspace-catalogs-v2.js`.
- New medication entry uses a server-rendered catalog select for canonical `drug_name` rather than a free-text identity field.
- Drug class is required.
- JavaScript progressively filters class → drug and provides standard-dose choices from `drug_catalog`.
- The base medication select remains usable without JavaScript; the script does not persist data or call a parallel API.

Lab:

- Patient Workspace now posts `catalog_test_key` rather than free-text test identity/unit.
- `src/api/vitals.py` resolves the catalog row on the server.
- Canonical `name_fa`, `test_key`, `unit`, `ref_low` and `ref_high` are persisted from `lab_test_catalog`.
- The existing batch form and historical single-row fallback remain intact.

### UX de-emphasis of non-goal ceremony

- Primary patient header KPI changed from visit-document count to recorded-visit count.
- SMS consent/settings remain accessible but moved under collapsed advanced details in Actions.
- Encounter document count was removed from the primary visit summary.
- Final visit documents remain accessible only as a collapsed secondary section; normal visit, appointment, follow-up and service facts are primary.
- Technical `Encounter` wording was removed from the primary service summary copy.

### Documentation

- Added and then updated `FRONTEND_GROWTH_AUTOMATION_EXECUTION_PLAN.md`.
- Added and then updated this working-memory file.
- Updated `FRONTEND_AUTOMATION_V2_EXECUTION_ROADMAP.md` so Stage 2 is proven, Stage 3 is active, broad suites are not run during implementation, and post-Stage-3 sequencing follows the growth plan instead of jumping to Encounter Autosave.

### Commits created during this turn

Key product/test commits:

- `ade195b4efe6a9bd7252673b1870b6e1c4a1d28c` — medication catalog cascade JS
- `c3573479f7232ecb56d6129005f4028a910f5b4f` — catalog medication entry
- `55a28767150ccada81fd1557e8c881c7f53b5566` — load Workspace catalog enhancement
- `5051a26f22e5d29212bbcb8cbe990d3da64481bc` — server-canonical lab identity
- `1a6aff3539fd935733d38d2aeeee94b5c8e107ae` — catalog-authoritative lab form
- `fd2dceb9e0843f3ecab73e30c8ce0ad46218bd16` — replace stale Workspace tests with native runtime coverage
- `2fbf9627504dc5ebea16ebd10cb1b56c23036213` — remove document KPI from patient header
- `07e13fa5dcecc3f102b797f7c73b004115623a66` — demote messaging consent controls
- `356a5bcca66c6b3fb04c3fac0785140e2d81b863` — demote document ceremony in visit history
- `896c6252d3cf2d2b962e1584d159355853d2e84f` — align old V2 roadmap with active Stage 3 and growth sequencing

## Verification state

Repository state was re-compared to the Stage 2 proven SHA after product/test changes. At that checkpoint the branch was 26 commits ahead and 0 behind, and the diff included the native Workspace files, the new catalog JS, the lab API change and the rewritten Patient Workspace test file.

No broad suite was run. No test execution is being claimed in this turn. The focused Stage 3 test file is written but still needs execution in a runnable checkout.

Doctor Queue code currently renders a safe unavailable state instead of crashing when its read-only source fails, and its template contains current / waiting / completed-today sections. Sidebar is role-aware and matches the automation IA. Final visual/browser acceptance is still pending, so do not claim the historical browser defect is fully proven fixed until browser verification is performed.

## Remaining verified gaps

1. Run only `tests/test_frontend_automation_patient_workspace_v2.py` and repair real failures.
2. Patient Workspace still needs recent contact/outcome, clearer return/retention context, acquisition/source and other business facts where authoritative data already exists.
3. Some actions still leave the Workspace instead of completing in patient context.
4. Patient Workspace registration remains coupled to the extension blueprint via `src/api/ext.py`; fix with a small registration move only.
5. Browser acceptance for desktop, 360px, keyboard, Doctor Queue and sidebar remains pending.
6. Revenue Cockpit, lifecycle/acquisition, outcome attribution and automation playbooks have not started yet.

## Exact next action

1. Execute only the focused Stage 3 test file in a runnable checkout; do not run broad suites.
2. Fix any observed Stage 3 failures.
3. Read the existing repositories/services for contact outcomes, appointment status history and financial lineage, then add recent-contact/return context to Patient Workspace without inventing parallel data.
4. Decouple Patient Workspace registration from `src/api/ext.py` minimally.
5. Perform focused browser verification when browser execution is available.
6. Then start Revenue Cockpit work from `FRONTEND_GROWTH_AUTOMATION_EXECUTION_PLAN.md`.

## Persistent guardrails for future turns

- Read this file and `FRONTEND_GROWTH_AUTOMATION_EXECUTION_PLAN.md` before making the next product change.
- Update both files in every development turn with what actually changed, what was verified and the new exact continuation point.
- Never state that a file/test/commit exists until it has been verified in the repository.
- Never interpret a Connector create error as proof that a path is missing; fetch the path and use its real SHA if it already exists.
- Do not run broad suites by default.
- Keep the five owner outcomes visible in UX decisions: follow-up, automation, revenue, patient growth, accuracy.

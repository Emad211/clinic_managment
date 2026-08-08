# Frontend Automation V2 — Execution Roadmap

**Status:** Stage 1 and Stage 2 proven; Stage 3 native Patient Workspace active  
**Scope:** finish the approved automation frontend while aligning the next product work with follow-up, automation, revenue, patient growth and accuracy  
**Parent baseline:** `fix/frontend-automation-v1-browser-acceptance`  
**Primary objective:** routine work should be automatic, frequent work should be one click, and only sensitive or irreversible work should require confirmation.

> Product sequencing after Stage 3 is governed by `FRONTEND_GROWTH_AUTOMATION_EXECUTION_PLAN.md`. The older Stage 4–6 items below remain useful backlog, but they no longer outrank revenue, patient-growth, attribution and automation-playbook work.

## Operating constraints

- Follow the active roadmap; do not add unrelated product scope.
- Prefer existing endpoints and services.
- Add only the smallest backend seam required to make an approved frontend workflow real and server-authoritative.
- Do not create a generic workflow engine, rewrite the frontend framework or simulate persistence in the browser.
- Use focused tests while a stage is in progress.
- **Do not run the complete Specialist Clinic or Accounting suites during implementation.** A broad run is allowed only at an explicitly requested final checkpoint.
- A frontend action is considered automated only after a successful server response.
- Do not spend primary UX effort on signatures, commitments, policy ceremony or security settings; keep those controls available only where the existing backend contract requires them.

## Stage 1 — Complete Work Center end to end

- Keep one `Handle` entry point with claim/start orchestration.
- Make the list-to-workspace transition drawer-like without losing a full-page fallback.
- Add the approved actions inside the same work context:
  - record contact outcome;
  - defer or set callback time;
  - create an appointment;
  - send or queue an allowed patient message;
  - record a definitive outcome and complete the work when the authoritative backend workflow permits it.
- Preserve current tab, filters and search.
- Continue to the next eligible item only after successful mutation.
- Absorb the remaining operational Control Room destination into manager Work Center context.

**Exit:** one task can be handled from start to definitive outcome without manually returning to the list or visiting unrelated pages.

### Stage 1 proof

Stage 1 branch:

`feat/frontend-automation-v2-work-center`

Proven head:

`d4797288ac1d11035982b8a6cd7ca122b28f1b9f`

Prior checkpoint result:

- Specialist Clinic: `884 passed`
- Accounting: passed

The implementation includes real Start Next, claim-safe action selection, progressive drawer with full-page fallback, structured contact, authoritative deferral, atomic appointment booking, administrative completion, contract-governed clinical Outcome completion, commitment-specific evidence completion, policy-aware atomic message approval queueing, auto-next after successful mutation, Control Room absorption and focused desktop/mobile/keyboard contracts.

## Stage 2 — Appointment automation and task continuity

- Add Today/List presentation without duplicating appointment storage.
- Prefill patient, visit type and relevant context.
- Preserve submitted form values after validation errors.
- Allow booking from Work Center and Patient Workspace context.
- Link the appointment to the current task or episode where the current domain model supports it.
- Automatically complete the task only when appointment creation is its definitive outcome.

**Exit:** a task that requires booking can be resolved with time selection and one successful submit.

### Stage 2 proof

Stage 2 branch:

`feat/frontend-automation-v2-appointments`

Proven head:

`c57bf1b874b467cefbfea1e63fce17e1a72c9b5e`

Prior checkpoint result:

- Specialist Clinic: `891 passed`
- Accounting: passed

Implemented behavior includes Today/List, conservative next-quarter-hour default, patient and visit-type context, preservation of invalid submitted values, safe return targets and continuity with the authoritative Work Center booking seam.

## Stage 3 — Native Patient Workspace

- Render the approved five-tab structure in Jinja, not by reconstructing legacy DOM in JavaScript.
- Keep progressive enhancement for keyboard-friendly controls and small-screen usability.
- Integrate patient card, reconciliation, appointments and patient work actions contextually.
- Preserve role-aware actions, tab state and original mutation endpoints.
- Keep technical evidence collapsed.
- Do not regress canonical clinical-data entry compared with the legacy patient page.

**Exit:** the five-tab information architecture and critical content remain understandable if JavaScript fails, and normal medication/lab entry preserves canonical identity.

### Stage 3 verified implementation state

Active branch:

`feat/frontend-automation-v2-patient-workspace`

Implemented:

- canonical `/patients/<pid>/workspace?tab=...` route;
- five server-rendered tabs with real links;
- legacy patient-detail compatibility redirect plus `?legacy=1` escape hatch;
- redirect rewriting from existing mutation endpoints back to the relevant workspace tab;
- read-only `PatientWorkspaceService` reusing existing repositories and the governed clinical facade;
- responsive native Workspace CSS;
- medication history, appointment context, work links and care timeline;
- catalog-backed medication selector with progressive class → drug → standard-dose filtering;
- server-authoritative lab catalog entry: the browser posts a catalog key and the server resolves canonical name, unit and reference range;
- visit/document ceremony demoted from primary patient KPIs and messaging-consent controls collapsed out of the normal action flow;
- the stale Stage-2-era Patient Workspace test file replaced with focused runtime coverage for the native route, five tabs, catalog entry and mutation return continuity.

Not yet proven:

- the new focused Stage 3 test file has been written but has not been executed in this connector-only work session;
- final browser acceptance at desktop/360px/keyboard remains pending;
- Patient Workspace registration is still coupled to the extension blueprint and should be moved with a minimal app-registration change;
- Patient 360 still lacks several business/retention facts such as recent contact outcome, acquisition source, no-show/cancellation history and provable patient value.

## Original Stage 4 — Safe Encounter autosave and queue continuation

This remains backlog, but is **not the next product stage** after the growth-direction update.

- Add a versioned, idempotent draft-save contract suitable for debounced autosave.
- Show Saving, Saved and Save failed states only from server responses.
- Retry without clearing form state.
- Warn about leaving only while a save is pending or failed.
- Keep one final encounter confirmation.
- Return to and focus the next patient without starting the visit automatically.

## Original Stage 5 — Messaging automation, split settings and rollout gates

This remains backlog. Routine-message automation should be implemented through the growth automation playbooks rather than by expanding approval ceremony in the primary UI.

## Original Stage 6 — Final integration and proof

- Audit confirmations, smart defaults, permissions and legacy paths.
- Measure representative click budgets for Work Center, appointment booking, patient measurement, encounter and messaging.
- Verify desktop, 360px mobile and keyboard journeys.
- Record console/network defects and visual evidence.
- Run broad suites only if the owner explicitly requests the final checkpoint.

## Current continuation point

Continue **Stage 3 hardening** on:

`feat/frontend-automation-v2-patient-workspace`

Exact order:

1. Run only `tests/test_frontend_automation_patient_workspace_v2.py` (and directly related focused tests if a failure requires them); never trigger the broad suites during implementation.
2. Fix only real failures from that focused coverage.
3. Finish the remaining Patient Workspace business context: recent contact/outcome, clearer next action and return/retention context using existing data where available.
4. Decouple Patient Workspace registration from `src/api/ext.py` with the smallest app-registration change.
5. Perform focused browser verification when a browser-capable checkout is available.
6. When Stage 3 is focused-test green, continue with Stage 2 of `FRONTEND_GROWTH_AUTOMATION_EXECUTION_PLAN.md`: Revenue Cockpit and operational value visibility, **not** Encounter Autosave.

# Frontend Automation V2 — Execution Roadmap

**Status:** Stage 1 automated implementation proven; Stage 2 active  
**Scope:** finish the remaining logical gaps in the specialist-clinic frontend  
**Parent baseline:** `fix/frontend-automation-v1-browser-acceptance`  
**Primary objective:** routine work should be automatic, frequent work should be one click, and only sensitive or irreversible work should require confirmation.

## Operating constraints

- Follow this roadmap exactly; do not add unrelated product scope.
- Prefer existing endpoints and services.
- Add only the smallest backend seam required to make an approved frontend workflow real and server-authoritative.
- Do not create a generic workflow engine, rewrite the frontend framework or simulate persistence in the browser.
- Use focused tests while a stage is in progress.
- Run the complete Specialist Clinic and Accounting suites only at a meaningful stage checkpoint, before merge, or after a broad integration change.
- A frontend action is considered automated only after a successful server response.

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

CI result:

- Specialist Clinic: `884 passed`
- Accounting: passed

The implementation includes real Start Next, claim-safe action selection, progressive drawer with full-page fallback, structured contact, authoritative deferral, atomic appointment booking, administrative completion, contract-governed clinical Outcome completion, commitment-specific evidence completion, policy-aware atomic message approval queueing, auto-next after successful mutation, Control Room absorption and focused desktop/mobile/keyboard contracts.

Actual visual browser acceptance remains intentionally pending until the final integration stage; automated browser-facing contracts do not replace local visual review.

## Stage 2 — Appointment automation and task continuity

- Add Today/List presentation without duplicating appointment storage.
- Prefill patient, visit type and relevant context.
- Preserve submitted form values after validation errors.
- Allow booking from Work Center and Patient Workspace context.
- Link the appointment to the current task or episode where the current domain model supports it.
- Automatically complete the task only when appointment creation is its definitive outcome.

**Exit:** a task that requires booking can be resolved with time selection and one successful submit.

## Stage 3 — Native Patient Workspace

- Render the approved five-tab structure in Jinja, not by reconstructing legacy DOM in JavaScript.
- Keep progressive enhancement for keyboard tabs, sticky header and drawers.
- Integrate patient card, reconciliation, appointments and patient work actions contextually.
- Preserve role-aware actions, tab state, scroll and original mutation endpoints.
- Keep technical evidence collapsed.

**Exit:** the five-tab information architecture and critical content remain understandable if JavaScript fails.

## Stage 4 — Safe Encounter autosave and queue continuation

- Add a versioned, idempotent draft-save contract suitable for debounced autosave.
- Show Saving, Saved and Save failed states only from server responses.
- Retry without clearing form state.
- Warn about leaving only while a save is pending or failed.
- Keep one final encounter confirmation.
- Return to and focus the next patient without starting the visit automatically.

**Exit:** normal encounter documentation does not require a manual draft-save click and never falsely claims persistence.

## Stage 5 — Messaging automation, split settings and rollout gates

- Automatically process predefined CARE reminders only when consent, policy and provider conditions are satisfied.
- Keep free-text, campaigns, overrides and sensitive messages approval-gated.
- Surface failures as exceptions with bounded retry.
- Make Advanced Message Center cover automation guard, policy and delivery exceptions.
- Split settings writes by approved surface using minimal authoritative endpoints.
- Enable completed low-risk capabilities in normal operation; keep sensitive automation behind health and rollout gates.

**Exit:** staff review exceptions rather than approving routine permitted messages.

## Stage 6 — Final integration and proof

- Audit all confirmations, smart defaults, permissions and legacy paths.
- Measure representative click budgets for Work Center, appointment booking, patient measurement, encounter and messaging.
- Verify desktop, 360px mobile and keyboard journeys.
- Record console/network defects and visual evidence.
- Merge in order and run final CI on `main`.

**Exit:** browser acceptance is complete, no high-severity defect remains, and the automation claims are supported by measured workflows.

## Current continuation point

Continue **Stage 2 — Appointment automation and task continuity** on branch:

`feat/frontend-automation-v2-appointments`

Exact order:

1. Add explicit Today/List views while preserving the current appointment repository.
2. Make invalid submissions render with all entered values and a clear field-level summary; never redirect and erase work.
3. Add a conservative next-quarter-hour default plus patient and visit-type context.
4. Preserve a safe return target so Patient Workspace booking returns to the same patient.
5. Keep Work Center booking on its existing authoritative Task/Episode path; do not create a duplicate booking workflow.
6. Remove misleading contact copy that implies an Appointment exists when only a patient-reported contact outcome was recorded.
7. Add focused runtime tests, then one Stage 2 checkpoint CI run.

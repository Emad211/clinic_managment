# Frontend Automation V2 — Evidence-Based Gap Audit

**Audit date:** 2026-08-05  
**Execution branch:** `feat/frontend-automation-v2-work-center`  
**Checkpoint code SHA:** `afc13184da7bda31ec66c85031e6019789f0fbd1`  
**Checkpoint proof:** Specialist Clinic `868 passed`; Accounting CI passed  
**PR:** `#121` remains draft/closed during continued development to avoid a full CI run for every focused commit.

## Audit rule

A gap is listed only when the current repository contradicts an explicit roadmap outcome or leaves an automated workflow incomplete. Future ideas that are not required by `FRONTEND_AUTOMATION_V2_EXECUTION_ROADMAP.md` are not included.

## Capabilities already proven — do not rebuild

- Work Center has one `Handle` entry point and can claim eligible work before opening it.
- Current view, query, state, role, SLA, page and page size are carried into the workspace and next-item navigation.
- Structured contact outcome can continue to the next eligible item after a successful server mutation.
- Administrative deferral and completion are authoritative and retry-safe.
- Clinical deferral uses the append-only clinical lifecycle.
- Encounter-plan deferral and completion use the append-only commitment lifecycle.
- Appointment booking is authoritative, idempotent and links the appointment to the task and Episode in the booking transaction.
- Clinical completion requires a contract-valid Outcome and links the Outcome to the Episode.
- Encounter-plan completion requires valid evidence.
- A visit invitation is queued for approval rather than sent as free text from Work Center.
- Projection refresh is scoped to the current Episode; a committed source mutation is not reported as failed merely because the disposable projection refresh fails.
- Feature flags and effective permissions gate the current Work Center mutation surfaces.

# Stage 1 — Remaining gaps

## P0 — Start-work controls do not start work

### Evidence

`dashboard_v1.html` and `unified_worklist.html` link to `unified_followups.index(..., focus='first')`, but the Work Center index route does not read or act on `focus`.

### Effect

The labels “شروع کارهای امروز” and “شروع رسیدگی” currently open or reload the list. They do not select, claim or open the first eligible item.

### Required correction

Create one server-authoritative start-next seam that resolves the first eligible item under the current filters and invokes the same `Handle`/claim path. A GET query parameter must not mutate ownership.

---

## P0 — Work Center message eligibility is weaker than the message policy

### Evidence

- The Work Center action is displayed and authorized with `sms.view`.
- `queue_visit_invite()` also checks only `SMS_VIEW`.
- `EngagementService.enqueue_invite()` can fall back to a hard-coded template and does not require the `visit_invite` event to be present, active and routed to an SMS-capable channel.
- The stricter `enqueue_event_for_patient()` path does check event activity, channel, consent, dispatch history and cooldown.

### Effect

A user with read-only message access can request a new approval candidate, and an invitation may be queued even when the configurable event is absent, disabled or set to `off`.

### Required correction

- Use a mutation-capable existing permission such as `sms.approval.review` for queuing an approval candidate.
- Queue only through an active configured CARE event whose channel permits SMS.
- Preserve consent, cooldown and duplicate checks.
- Do not silently substitute a fallback template when the governed event is disabled or unavailable.

---

## P0 — Message approval creation and Episode linkage are not one truthful outcome

### Evidence

The approval row is created by `EngagementService.enqueue_invite()` and committed before Work Center starts a second transaction to link it to the Episode. Link exceptions are caught broadly and returned as `episode_linked=False`; the route can still report success and continue to the next item.

### Effect

The user may leave the work item after an approval was queued but the Work Center Episode failed to record the communication source.

### Required correction

Use one caller-owned transaction or a narrow orchestration seam covering approval creation, Episode link and `SMS_QUEUED` event. If the source was committed but the link cannot be committed, report a partial authoritative success and remain on the same item; do not auto-next.

---

## P1 — Clinical completion form is not task-contract aware

### Evidence

The current clinical form renders every Outcome type and a generic Fact key field. The server correctly validates `allowed_outcome_types`, `required_fact_keys`, minimum verification and canonical ingestion, but the UI does not derive its choices and required fields from the immutable task contract.

### Effect

Operators can select combinations that are guaranteed to fail on submit, and required canonical facts are not prefilled or clearly required.

### Required correction

Pass the current task contract to the workspace and render only permitted Outcome types. Render required Fact keys as explicit choices, mark value/unit requirements and explain canonical ingestion before submit.

---

## P1 — Plan evidence form is not commitment-type aware

### Evidence

The Work Center form lists every evidence type for every plan commitment while `EncounterPlanCommitmentService` permits evidence by commitment type.

### Effect

The UI offers invalid combinations that the authoritative service must reject.

### Required correction

Expose the allowed evidence set for the current commitment type and render only valid options. Prefer existing in-scope evidence records when a reliable identifier is already available.

---

## P1 — Control Room remains a separate operational destination

### Evidence

- `dashboard_v1.html` still links to `control_room.index` as “نمای مدیریتی عملیات”.
- The Control Room blueprint and template remain active and registered.
- The Stage 1 roadmap requires the remaining operational Control Room destination to be absorbed into the manager Work Center context.

### Effect

Managers still have two operational destinations with overlapping intent and different interaction models.

### Required correction

Move the remaining manager-only operational summary/actions into the Work Center manager view. Keep the historical URL as a permission-preserving redirect until legacy links are retired. The descriptive `ControlRoomService` may remain as a read source if useful.

---

## P1 — List-to-workspace transition is not drawer-like

### Evidence

The list posts `Handle` and redirects to a separate full-page detail template. There is no progressive list-side drawer or fragment-loading path. Full-page fallback exists, but the drawer enhancement required by the roadmap is absent.

### Effect

Context is preserved in query parameters, but visual list context and scroll position are lost during every task transition.

### Required correction

Add a progressively enhanced drawer over the list for desktop and a full-screen drawer for mobile. Keep the current detail URL as the no-JavaScript fallback and canonical deep link.

---

## P2 — Work Center implementation cleanup

- `work_center_action_service.py` contains multiple unrelated orchestration concerns and should be split only after Stage 1 behavior is stable.
- `work_center_outcomes` is registered indirectly through the extension blueprint’s `record_once` hook; it should be registered explicitly by the app factory or a follow-up module registrar.
- The legacy `followups.worklist` and Unified Work Center remain parallel operational surfaces. Legacy routes should become compatibility-only after the new browser journey is proven.
- `_work_action_failure()` in `followups.py` renders raw exception text, unlike the safer outcome route; normalize operator-safe errors and retain technical details in logs.
- Administrative completion currently relies on a deterministic service fallback rather than forwarding the form’s idempotency key and actor user ID. It is retry-safe, but the route should pass the explicit request identity for consistent audit semantics.

# Stage 2 — Appointment automation gaps

## Confirmed

- The appointment page has a combined date-range list and KPI for today, not distinct Today/List work modes.
- Validation failure redirects to a blank form, so submitted patient, date, time, type, notes and recurrence are lost.
- Only `patient_link_id` is accepted as prefill context; visit type, current task/Episode, return destination and definitive-outcome intent are not preserved.
- No nearest-slot suggestions or explicit collision feedback are rendered.
- Patient Workspace booking navigates to a separate page; it is not an in-context drawer.
- Work Center booking is already authoritative and must be reused rather than duplicated.

## Stage 2 continuation

Build a context object for appointment creation, preserve invalid submissions server-side, add Today/List presentation and reusable nearest-slot selection, and return to the initiating task or patient workspace after a successful booking.

# Stage 3 — Native Patient Workspace gaps

## Confirmed

- The current patient page exposes four tabs: overview, trends, medications and record. The approved structure requires five: Summary, Actions, Clinical Data, Medications/Prescriptions and Encounters/Documents.
- The page is one very large Jinja template with extensive embedded JavaScript and CSS.
- Non-default panes use the HTML `hidden` attribute; without JavaScript, medication, trend and record content is not directly reachable through working tab navigation.
- Patient “next action” and open-followup links still target the legacy worklist instead of opening the relevant Unified Work Center item or patient-filtered work context.
- Appointment and several patient actions navigate away instead of opening contextual drawers.

## Stage 3 continuation

Split the page into native Jinja tab partials, make each tab addressable by URL/hash without requiring JavaScript, add the missing Actions and Encounters/Documents groupings, and point patient work actions at the Unified Work Center.

# Stage 4 — Encounter autosave and queue continuation gaps

## Confirmed

- The authoritative draft-save endpoint already exists and is idempotent.
- The UI still requires the “ذخیره پیش‌نویس” button or keyboard shortcut.
- There are no server-confirmed Saving, Saved or Save failed states.
- There is no debounced versioned autosave request contract or retry state in the browser.
- There is no leave warning limited to pending/failed saves.
- After signing, the route redirects to `doctor_queue.index(focus='next')`, but the queue route does not consume `focus`; next-patient focus is therefore not implemented.

## Stage 4 continuation

Add a version/revision field to draft-save requests, implement debounced server-confirmed autosave, keep form data on failure, warn only for pending/failed writes and add a real focus-next queue route that never starts the next visit automatically.

# Stage 5 — Messaging automation and settings gaps

## Confirmed

- Message Center navigation already groups approvals, campaigns, automation, delivery report and advanced settings.
- Routine CARE candidates still primarily enter an approval queue; the roadmap’s low-risk automatic processing and exception-only operator workflow are not complete.
- Advanced Message Center is still a link to the broad manager settings section rather than a dedicated exceptions/policy/delivery workspace.
- Manager settings uses a large multi-setting POST route; writes are not split by approved surface.
- Work Center currently queues a visit invitation candidate, but that path needs the Stage 1 governance and transaction corrections above before broader automation.

## Stage 5 continuation

Define the exact low-risk CARE event allowlist, process only policy/consent/provider-healthy events automatically, surface bounded failures as exceptions, preserve approval for free text/campaigns/overrides and split settings mutations into narrow authoritative endpoints.

# Stage 6 — Proof gaps

Not yet performed for Automation V2:

- Browser journey proof on desktop and 360 px mobile.
- Keyboard-only Work Center, patient and encounter journeys.
- Measured click budgets.
- Console/network error capture.
- Browser proof of failure retention and retry.
- Visual proof of drawer behavior and no-JavaScript fallbacks.

# Exact continuation order

## Checkpoint 3 — Stage 1 critical closure

1. Implement a real server-authoritative Start Next action.
2. Correct message queue permission and active-event policy.
3. Make approval creation + Episode link truthful and transactionally coordinated.
4. Render clinical and plan completion forms from their authoritative contracts.

## Checkpoint 4 — Stage 1 UX closure

1. Absorb the operational Control Room destination into manager Work Center.
2. Add progressive drawer behavior with full-page fallback.
3. Normalize errors and remove compatibility-only duplicate paths from normal navigation.
4. Run focused tests, then one full CI checkpoint and browser smoke.

**Stage 1 is not merge-ready until Checkpoints 3 and 4 are complete.**

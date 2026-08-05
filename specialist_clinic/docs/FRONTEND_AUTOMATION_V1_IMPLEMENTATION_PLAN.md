# Frontend Automation V1 — Implementation Plan

**Status:** approved implementation baseline  
**Scope:** `specialist_clinic` frontend only  
**Target branch:** `main` after CI and visual/behavioural verification  
**Principle:** the system performs routine work; people handle exceptions and clinical decisions.

## 1. Product outcome

Transform the current page-heavy administration UI into an automation-first clinical workspace.

Target interaction distribution:

- **80%** routine actions: automatic or zero-click.
- **15%** frequent actions: one click.
- **5%** irreversible or clinically sensitive actions: one explicit confirmation.

This phase changes templates, shared components, CSS, JavaScript, navigation, copy and interaction orchestration. It does **not** create new clinical, accounting or messaging business rules. Existing endpoints remain the source of truth.

## 2. Non-negotiable UX rules

1. Every page has one primary purpose and at most one primary action.
2. Every table row exposes one main action; secondary actions live in a three-dot menu or task drawer.
3. Routine reversible actions use immediate feedback and Undo where technically possible, not confirmation dialogs.
4. Confirmation remains only for:
   - finalising an encounter;
   - stopping an active medication;
   - invalidating a final document;
   - sending a large campaign;
   - reversing a financial operation;
   - activating or rolling back a clinical ruleset;
   - disabling a user;
   - changing patient messaging consent.
5. Repeated commitment checkboxes, policy acknowledgements and multi-signature flows are removed from routine UI.
6. Hashes, internal IDs, snapshots, raw policy codes, provider payloads and audit internals are hidden under **Technical details** and are never primary content.
7. The first visible content answers: what happened, what needs attention, and what the next action is.
8. All primary workflows must work at 360px width, with keyboard navigation and visible focus.

## 3. Final information architecture

### Daily work

- Home
- Work Center
- Patients
- Appointments
- Doctor Queue

### Communication

- Message Center

### Management

- Finance
- Clinical Engine
- Users
- Settings

Navigation is role-aware. Technical and advanced pages remain reachable only through contextual links or advanced sections.

### Consolidations

**Work Center** absorbs:

- Control Room
- legacy Follow-up Worklist
- Unified Follow-up list/detail
- Clinical Alerts
- unavailable/error fragments for task loading

**Message Center** absorbs:

- Approval Queue
- Campaigns
- Delivery Report
- Automated Engagement
- Auto Guard as an advanced manager-only surface

**Patient Workspace** absorbs:

- Patient Card administration
- CARE and marketing consent
- clinical reconciliation
- clinical suggestions
- medications, indicators, follow-ups and documents

**Clinical Engine** absorbs:

- protocols
- validation
- onboarding
- shadow monitor/reviews
- retired indicators

Legacy routes may remain for compatibility but must redirect or link into the consolidated surface and must not remain primary navigation destinations.

## 4. Shared frontend foundation

Implement or standardise these reusable components before broad page edits:

- design tokens: spacing, typography, radii, shadows, semantic colours;
- page header and breadcrumb;
- role-aware desktop sidebar and mobile bottom navigation;
- global search trigger;
- primary/secondary/ghost/danger/icon buttons;
- status badge vocabulary;
- summary card;
- filter bar;
- accessible data table and mobile card list;
- drawer and single confirm dialog;
- three-dot action menu;
- toast with optional Undo;
- loading skeleton, empty state and error state;
- form section and inline validation;
- sticky patient header;
- task card and task action drawer;
- timeline;
- collapsed technical details;
- unsaved-changes guard.

No modal-on-modal. Large forms use a page or full-height drawer. Icon-only controls require an accessible label and tooltip.

## 5. Automation interaction layer

### Smart defaults

Use existing context to preselect the current clinician, task owner, likely visit type, current date, usual follow-up interval, previous filter, last active tab and available message template. Suggestions must remain editable.

### Autosave

Enable debounced draft saving only where an existing safe draft endpoint exists: encounter drafts, task/contact notes, campaign drafts and non-sensitive settings. Show one of: `Saving`, `Saved`, `Save failed — retry`.

Never simulate autosave locally when the server has not persisted the data.

### Auto-claim

Opening a task via **Handle** should call the existing claim/start action when required, then open the action drawer. The separate Claim button disappears from normal UI.

### Auto-complete

When an existing endpoint records the definitive outcome—contact outcome, booked appointment, required message, final task outcome or encounter completion—the frontend should not require a second manual completion click when the current backend workflow already allows completion.

### Auto-next

After a successful queue or work-center action, keep the user in context and offer/open the next eligible item. Never auto-open an item after an error or destructive action.

### Quick actions

Expose one-click choices for common outcomes such as:

- no answer;
- invalid number;
- call later;
- appointment booked;
- clinician review required;
- follow-up completed;
- patient arrived;
- no-show;
- patient cancelled;
- send reminder;
- retry eligible message.

### Progressive disclosure

Show summaries first. Forms, history, audit, policies and raw technical data open only on demand.

## 6. Page-specific target state

### Home

Role-specific action dashboard. Show the next action, urgent work, waiting patients, upcoming appointment and automation exceptions. Management charts appear only for managers.

### Work Center

Tabs: My work, Unassigned, All, Completed; plus Manager view for managers. Each item shows patient, reason, owner, due time, last event and one **Handle** action. Contact, assign, defer, book, message and complete live in one drawer.

### Patient Workspace

Sticky patient header with identity, clinician, allergy warning, next appointment and next best action. Tabs:

1. Summary
2. Actions
3. Clinical data
4. Medications and prescriptions
5. Encounters and documents

Quick actions occur without leaving the patient context. Clinical-engine technical evidence is collapsed.

### Appointments

Today/list views, compact filters and one primary row action. Patient/clinician/context fields are prefilled. Routine status changes are one click. Booking related to a task closes that task when the existing workflow supports it.

### Doctor Queue

Current visit, waiting, completed today. Start in one click, preload the patient brief, continue drafts, and move to the next patient after finalisation.

### Encounter

Three sections: history/exam, assessment/plan, prescription/follow-up. Drafts autosave through existing endpoints. Remove repeated signatures, commitments and per-section confirmations. Keep one final encounter confirmation.

### Message Center

Tabs: Needs approval, Campaigns, Automations, Delivery, Advanced. Routine approved CARE reminders should not be presented as manual approval work. Provider payloads and policy internals remain advanced-only.

### Finance

Summary plus review list. Ordinary review and correction flows do not require signatures. Reversal remains confirmed. Accounting snapshot internals are collapsed.

### Clinical Engine

Default view shows active version, state, current problem, next action and last validation. Advanced view contains hashes, snapshots, shadow data and low-level rule metadata. Activation and rollback remain confirmed.

### Settings

Split into General, Messaging providers, SMS costs, Patient card, Prescription/print and Network/accounting. Each surface saves independently; ordinary saves have no second confirmation.

## 7. Copy and policy cleanup

- Replace internal status codes with consistent Persian labels.
- Replace Claim/Resolve/Adjudicate/Reconcile/Commit with user-oriented action verbs.
- Keep one global clinical disclaimer near clinical suggestions; remove repeated copies.
- Replace long policy blocks with a short reason and a next action.
- Remove routine responsibility/commitment checkboxes.
- Preserve audit capture in the backend without presenting it as user ceremony.

## 8. Delivery phases

### Phase 1 — Foundation

Shared tokens/components, shell, navigation, mobile navigation, action menus, drawer, toast, loading/empty/error states.

### Phase 2 — Information architecture

Role-aware menu, consolidated destinations, legacy-route demotion, human status vocabulary.

### Phase 3 — Work Center

Unified list, filters, task drawer, quick outcomes, claim/start orchestration, completion and next-item flow.

### Phase 4 — Patient Workspace

Sticky header, five-tab structure, contextual quick actions, consent/reconciliation/suggestion simplification and mobile layout.

### Phase 5 — Queue and Encounter

One-click start, patient brief, autosave, simplified finalisation and next-patient flow.

### Phase 6 — Appointments

Smart defaults, compact booking, quick statuses and task-context continuity.

### Phase 7 — Message Center

Unified tabs, approval simplification, campaign preview, delivery exceptions and advanced automation controls.

### Phase 8 — Management

Finance, users, split settings and simple/advanced clinical-engine views.

### Phase 9 — Polish

Accessibility, responsive QA, performance, Persian/Jalali consistency, keyboard use and visual regression.

## 9. Acceptance criteria

A surface is complete only when:

- it has one clear purpose and one primary action;
- routine work requires zero or one click where current endpoints permit;
- no unnecessary signature, commitment checkbox or confirmation remains;
- internal IDs and policy metadata are absent from the normal view;
- loading, empty, error and success states are present;
- the 360px layout is usable without global horizontal scrolling;
- keyboard focus and accessible names are correct;
- form data is preserved after validation errors;
- filters/tab context survive normal navigation where technically possible;
- role-inappropriate actions are not rendered;
- legacy duplicate surfaces are no longer primary navigation destinations;
- automated UI behaviour always reflects a successful server response and never fakes persistence.

## 10. Verification gates

For every implementation slice:

1. run focused tests for touched routes/templates;
2. run `tests/test_ui_information_architecture.py` and related architecture guards;
3. run the complete specialist-clinic suite before merge;
4. verify core journeys with demo patients `TEST0001..TEST0010`;
5. inspect desktop and 360px mobile states;
6. verify no accounting write path was introduced;
7. merge only when CI is green or a pre-existing infrastructure failure is proven and documented.

## 11. Immediate implementation order

1. shared shell and automation-ready design primitives;
2. role-aware simplified navigation;
3. Work Center first vertical slice;
4. Patient Workspace shell;
5. Doctor Queue and Encounter simplification;
6. remaining surfaces by the phases above.

This document is the frontend implementation source of truth. If implementation constraints require deviation, update this file in the same pull request and record the reason.
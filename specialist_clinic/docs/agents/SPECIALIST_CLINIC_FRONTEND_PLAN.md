# Specialist Clinic Frontend — Growth Automation Plan

**Status:** active implementation plan  
**Branch:** `feat/specialist-clinic-growth-automation-v1`  
**Last updated:** 2026-08-06 17:53 +03:30

## Product objectives

Every frontend change must directly improve at least one of these five goals:

1. **Follow-up:** no patient, task, result, appointment or missed visit is lost.
2. **Automation:** routine low-risk work happens automatically; frequent work is one click.
3. **Revenue:** follow-up, appointment, attendance, service and collected revenue are connected.
4. **Patient growth:** leads, referrals, recall and campaigns create measurable new patients and repeat visits.
5. **Accuracy:** structured catalogs, reconciliation and source-backed facts prevent dirty clinical and business data.

## Explicit exclusions

- Do not spend product time on signature, commitment, pledge or contract ceremony.
- Do not expand security/governance UI unless it blocks a core workflow.
- Do not rewrite the frontend framework.
- Do not change the accounting application or write to its database.
- Do not report historical accounting visits as specialist-clinic revenue without explicit lineage.
- Do not create a generic workflow engine.
- Do not run broad/full test suites during normal implementation. Write and run focused tests only; broad CI is reserved for final integration outside this execution policy.

## Stage 1 — Finish the native Patient 360 workspace

- Complete the five server-rendered tabs and runtime tests.
- Restore catalog-backed drug and lab entry.
- Show last contact, next action, upcoming appointment, no-show history, recent messages, source/referrer and value summary.
- Keep legacy page only as a temporary fallback.
- Ensure every mutation returns to the originating tab with user input preserved when validation fails.

**Exit:** the new workspace is the default reliable Patient 360 surface and no accuracy regression remains.

## Stage 2 — Patient lifecycle and lead pipeline

- Add lead/prospect records without pretending they are enrolled patients.
- Track source, referrer, owner, interest, status and next action.
- Lifecycle: `NEW → CONTACTED → APPOINTMENT_BOOKED → ATTENDED → CONVERTED` or `LOST`.
- Add lost reason and next follow-up.
- Convert a lead to a patient only through an explicit server action.
- Surface leads and follow-up exceptions in the existing Work Center.

**Exit:** every incoming prospect has an owner, next action and measurable conversion state.

## Stage 3 — Revenue cockpit and attribution

- Add a manager cockpit for today, month-to-date and forecast.
- Show booked value, attended value, invoiced value and collected value separately.
- Attribute revenue only through explicit patient/journey/encounter/service/invoice lineage.
- Show revenue from follow-up, recall, campaign, referral, clinician, service and staff owner.
- Show no-show and cancellation opportunity loss.
- Keep historical accounting activity visible but outside specialist revenue unless attributable.

**Exit:** management can identify which actions and channels produce collected specialist revenue.

## Stage 4 — Growth automations

- Recall inactive patients based on configurable clinical/business cohorts.
- No-show recovery sequence.
- Cancellation waitlist and empty-slot fill.
- Referral tracking and patient-to-patient referral loop.
- Campaign audience, outcome and revenue attribution.
- Stop automation automatically when booking, attendance, opt-out or ineligibility occurs.
- Show only automation exceptions to staff.

**Exit:** the system actively creates appointments and repeat visits instead of only recording work.

## Stage 5 — Closed-loop follow-up automation

- Complete the chain:
  `trigger → task → contact/message → appointment → attendance → service → invoice → collection`.
- Automatically complete or advance work only after authoritative evidence.
- Create next work when evidence is missing, a result is abnormal, a patient does not attend or payment remains incomplete.
- Add outcome-based playbooks for common clinic workflows.

**Exit:** every important follow-up reaches a terminal business/clinical result or a visible exception.

## Stage 6 — Accuracy and data quality

- Enforce drug, lab, service, campaign source and referral catalogs in the frontend.
- Detect duplicates, missing units, incompatible values and stale patient identity.
- Put reconciliation at the point of use, not in a separate technical page only.
- Show confidence/source for derived clinical and revenue summaries.
- Remove free-text fields where a canonical option exists.

**Exit:** analytics and automation use normalized, source-backed data.

## Stage 7 — Operational integration and measured UX

- Consolidate manager home around follow-up, growth, revenue and exceptions.
- Remove or demote technical/legacy destinations.
- Measure click budgets for lead capture, follow-up, booking, attendance, service and payment review.
- Verify desktop, 360px mobile and keyboard use with focused browser smoke tests.
- Update handoff and merge sequencing only after focused acceptance evidence.

**Exit:** the frontend behaves as one clinic operating system rather than disconnected administrative pages.

## Test policy

For each stage:

1. Write focused repository/service/route/template tests for changed behavior.
2. Run only the focused tests related to that stage.
3. Do not run the full Specialist Clinic or Accounting suites during implementation.
4. Preserve accounting read-only boundaries with focused contract tests.
5. Record unrun broad tests explicitly in the execution memory.

## Current continuation point

1. Finish Stage 1 on `feat/specialist-clinic-growth-automation-v1`.
2. Add the missing focused Patient Workspace runtime tests.
3. Fix catalog-backed medication/lab entry and mutation-return behavior.
4. Add the minimal patient value/contact/referral summary needed for Patient 360.
5. Then begin Stage 2 lead pipeline.

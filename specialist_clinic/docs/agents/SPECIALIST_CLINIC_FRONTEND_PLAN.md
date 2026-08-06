# Specialist Clinic Frontend — Growth Automation Plan

**Status:** active implementation plan  
**Branch:** `feat/specialist-clinic-growth-automation-v1`  
**Last updated:** 2026-08-06 19:11 +03:30

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
- Do not run broad/full test suites during normal implementation. Write focused tests; broad CI is outside this execution policy.

## Stage 1 — Native Patient 360 workspace

**Implementation status: substantially implemented; focused tests written, not run.**

Implemented:

- five server-rendered tabs with canonical routing and legacy fallback;
- catalog-backed medication entry with server-authoritative name, class and standard dose;
- catalog-backed lab entry with server-authoritative name, unit and reference range;
- form-state preservation and 422 rendering for invalid catalog submissions;
- last contact, recent message, next appointment, no-show count and open work summary;
- source-backed specialist billed/collected/outstanding value;
- converted Lead source/referrer shown in Patient 360;
- operational language centred on visits and services rather than signature/document ceremony;
- focused route/template/catalog tests written.

Remaining:

- remove the final advanced-form dependencies on the legacy patient page;
- surface compact reconciliation/data-quality exceptions directly in relevant tabs;
- execute only the focused Patient Workspace tests when runtime capacity permits.

**Exit:** the new workspace is the default reliable Patient 360 surface and no accuracy regression remains.

## Stage 2 — Patient lifecycle and lead pipeline

**Implementation status: core pipeline implemented; focused tests written, not run.**

Implemented:

- leads remain separate from enrolled patients until explicit conversion;
- canonical source, referrer, owner, interest, status and next action;
- lifecycle: `NEW → CONTACTED → APPOINTMENT_BOOKED → ATTENDED → CONVERTED` or `LOST`;
- structured lost reason;
- duplicate open-phone suppression;
- one-page operational Lead Workspace;
- explicit patient conversion with source/referrer retention;
- appointment/historical attendance transfer during conversion;
- lead event timeline and manager counts;
- focused lifecycle/conversion tests written.

Remaining:

- surface due leads in the unified daily exception view/Home;
- add referral-loop actions after a patient becomes an advocate/referrer;
- add bulk import only if an actual acquisition source requires it.

**Exit:** every incoming prospect has an owner, next action and measurable conversion state.

## Stage 3 — Revenue cockpit and attribution

**Implementation status: first source-backed cockpit implemented; focused tests written, not run.**

Implemented:

- today and month-to-date billed/collected/outstanding specialist value;
- lead funnel and specialist financial funnel;
- no-show and cancellation opportunity counts;
- revenue grouped by converted Lead source;
- existing/legacy patients kept separate from known acquisition sources;
- historical accounting activity excluded without explicit specialist lineage;
- forecast deliberately withheld when priced pipeline evidence is missing;
- focused attribution/no-fabrication tests written.

Remaining:

- attributed results by staff owner, clinician, service and follow-up source;
- priced booking pipeline needed for a defensible forecast;
- campaign/referral cohort economics in the same cockpit.

**Exit:** management can identify which actions and channels produce collected specialist revenue.

## Stage 4 — Growth automations

**Implementation status: recovery/recall core implemented; broader growth playbooks remain.**

Implemented:

- idempotent No-show recovery tasks;
- cancellation recovery only when no replacement appointment exists;
- inactive-patient recall with configurable threshold;
- patients with future appointments excluded from recall;
- preview-before-run page;
- tasks enter the existing Work Center with source and appointment linkage;
- focused automation tests written, not run.

Remaining:

- cancellation waitlist and empty-slot fill;
- referral tracking and patient-to-patient referral loop;
- campaign audience/outcome/revenue attribution integration;
- automatic stop conditions for booking, attendance, opt-out and ineligibility;
- exception-only automatic scheduling instead of manual run for mature playbooks.

**Exit:** the system actively creates appointments and repeat visits instead of only recording work.

## Stage 5 — Closed-loop follow-up automation

**Implementation status: appointment and financial evidence loop implemented; messaging/clinical playbooks remain.**

Implemented:

- recovery/recall task closes after a valid future replacement appointment or a completed visit;
- stale past scheduled appointments do not close work;
- eligible specialist invoice without observation creates a Work Center exception;
- unpaid/partially collected specialist invoice creates a collection task;
- financial-observation task closes when observation arrives;
- collection task closes when later evidence shows full collection/no billable items;
- preview and one-click reconciliation on the growth automation page;
- focused closed-loop tests written, not run.

Remaining:

- governed message sequence for No-show, recall and appointment reminders;
- automatic stop of message/work sequence after booking, attendance or opt-out;
- explicit abnormal-result and missing-clinical-evidence playbooks;
- service/invoice delay exceptions where authoritative evidence is absent;
- scheduled execution after focused acceptance.

**Exit:** every important follow-up reaches a terminal business/clinical result or a visible exception.

## Stage 6 — Accuracy and data quality

**Implementation status: medication/lab/source identity partially implemented.**

Implemented:

- medication and lab catalog identity enforced in native Workspace routes;
- canonical unit/reference range populated from server catalogs;
- lead source, interest and lost reason use controlled vocabularies;
- active duplicate lead phone is suppressed;
- patient conversion reuses existing patient by national ID or phone;
- source-backed Patient 360 and revenue summaries show missing data instead of guessing.

Remaining:

- service and referral catalogs;
- point-of-use duplicate/stale-identity warnings;
- compact reconciliation exceptions in each Patient Workspace tab;
- normalized source mapping for old/manual patient records;
- data-quality queue for legacy free-text medications/labs.

**Exit:** analytics and automation use normalized, source-backed data.

## Stage 7 — Operational integration and measured UX

**Implementation status: not yet completed.**

- consolidate manager Home around follow-up, growth, revenue and exceptions;
- add stable navigation for Leads, Growth Cockpit and Automation;
- remove or demote technical/legacy destinations;
- measure click budgets for lead capture, follow-up, booking, attendance, service and payment review;
- verify desktop, 360px mobile and keyboard use with focused browser smoke tests;
- update handoff and merge sequencing after focused acceptance evidence.

**Exit:** the frontend behaves as one clinic operating system rather than disconnected administrative pages.

## Test policy

For each stage:

1. Write focused repository/service/route/template tests for changed behaviour.
2. Run only focused tests when runtime validation is required.
3. Never run the full Specialist Clinic or Accounting suites during this implementation.
4. Preserve accounting read-only boundaries with focused contract tests.
5. Record all unrun tests explicitly in the execution memory.

## Current continuation point

1. Continue Stage 4 with waitlist/empty-slot fill and referral loop.
2. Continue Stage 5 with governed messaging and automatic stop conditions.
3. Implement Stage 6 point-of-use quality exceptions.
4. Finish Stage 7 navigation/Home integration and focused browser smoke tests.
5. Do not run broad test suites; all new focused test files are currently written but unexecuted.

# Hypoglycemia Shadow Vertical Slice v1

## Purpose

This tranche converts the frozen ADA 6.19 research into one small, testable
workflow without creating a clinical Rule.

```text
candidate source record
→ append-only candidate event
→ clinician confirm / reject / conflict
→ clinician-owned shadow review
→ clinician-authored disposition record
```

## Deliberate non-goals

This tranche does **not**:

- infer a medication responsible for an event;
- reduce, stop, switch, prescribe, or order medication;
- create a Clinical Engine recommendation;
- create a normal follow-up task or patient message;
- merge duplicates automatically;
- activate production or visible clinical behavior;
- implement the entire 43-field research data contract.

## Minimal event contract

A candidate is identified by:

- patient;
- stable source system and source record identity;
- occurrence time when known;
- Level 2, Level 3, or unknown classification;
- glucose and unit when available;
- external-assistance and altered-function tri-state evidence;
- reporter type;
- verification state;
- append-only versions and content hashes.

Confirmation is fail-closed:

- Level 2 requires an occurrence time and measured glucose below 54 mg/dL;
- Level 3 requires an occurrence time, external assistance, and altered function;
- only `CONFIRMED` evidence can open a review;
- stale-head writes fail;
- update and delete are forbidden.

## Review boundary

The review is tied to the exact current confirmed event version. A disposition
is a record of an independently authored clinician decision.
`MEDICATION_CHANGE_RECORDED` records that a clinician made a decision; it does
not execute, recommend, or communicate a medication change.

## Executable synthetic coverage

The first tranche covers:

1. candidate idempotency;
2. cross-patient source mismatch;
3. Level 2 confirmation threshold;
4. Level 3 assistance/function evidence;
5. immutable event history;
6. stale-head rejection;
7. confirmed-only review creation;
8. no medication/task/recommendation side effect;
9. entered-in-error exclusion.

## Rollout boundary

The module is not wired to routes, UI, Clinical Engine evaluation, scheduler,
or normal startup migrations. Storage is installed only when the isolated
service is invoked. This keeps the tranche shadow-only while tests validate its
data integrity.

Research PR #60 remains frozen at v0.9.4. New evidence work resumes only when a
material source can change the current evidence boundary.
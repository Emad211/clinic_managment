# Hypoglycemia Shadow Observability v1

## Purpose

This tranche adds a read-only aggregate snapshot for the isolated hypoglycemia
shadow workflow merged in PR #62.

It answers only operational questions:

- how many current event heads are candidate, confirmed, conflicting, rejected,
  or entered in error;
- how many current events are Level 2, Level 3, or unknown;
- how many clinician reviews are open or have a recorded disposition;
- how much candidate/confirmed backlog exists;
- whether an active review points to an event version that is no longer the
  current confirmed source.

## Privacy boundary

The snapshot contains no:

- patient identifier;
- event or review identifier;
- source record identity;
- actor/owner name;
- glucose value;
- note or rationale.

Only fixed aggregate counts and system states are returned.

## Read-only boundary

The read model:

- does not install or repair storage;
- does not write, update, or delete any row;
- returns a zero snapshot with `NOT_INSTALLED` when the shadow slice has never
  been explicitly used;
- returns `INCOMPLETE / ATTENTION_REQUIRED` when only part of the required
  storage exists;
- has no route, UI, scheduler, notification, clinical task, or Clinical Engine
  integration.

## Safety indicators

`review_source_no_longer_current_confirmed` counts current review heads whose
source event version was superseded, rejected, conflicted, or entered in error.
Such a review cannot receive a new disposition in the write service and must be
visible for data-quality follow-up.

`confirmed_without_active_review` is backlog, not a treatment recommendation.
No SLA, alert, patient message, medication action, or urgency is inferred.

## Rollout boundary

This tranche is internal observability only. A future manager-only screen or
scheduled metric export requires its own privacy, authorization, workload, and
UI review. The current PR intentionally stops at a tested read model.

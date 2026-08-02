# Specialist Clinic — Agent Instructions

This file is the nearest mandatory instruction source for every change under `specialist_clinic/`.

## Mandatory read order

Before editing code, schema, UI, tests or documentation in this tree, read and reconcile:

1. repository `PROJECT_STATE.md` and `PROJECT_STATE.json`;
2. root `AGENTS.md`;
3. this file;
4. `graphify-out/GRAPH_REPORT.md` when available;
5. the code-adjacent contract for the stream being changed.

For Follow-up, Worklist, Task, SMS, Contact, Appointment or operational automation work:

```text
docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md
docs/FOLLOWUP_ORCHESTRATION_UX_V1_BASELINE.md
```

Conversation memory, old branches and historical PR bodies never override current `main`, `PROJECT_STATE.*` or the canonical plan.

## Current data environment

```text
specialist.db = TEST_ONLY / SYNTHETIC_OR_RESETTABLE
source        = owner attestation, 2026-08-03
```

This permits reset/reseed and migration rehearsal on current data, but it does not remove security or clinical guardrails. Before real patient data is entered, production-readiness and privacy review are mandatory. Never encode a `TEST_ONLY` shortcut in runtime logic.

## Current FOUX-V1 gate

Program: `FOUX-V1 — Follow-up Orchestration & UX v1`

```text
FO-0 = VALIDATED
FO-1 = AUTHORIZED
FO-2 and later = BLOCKED pending FO-1 exit gate
```

Current permitted tranche:

```text
FO-1 — Episode Identity & Append-only Links
```

FO-1 may add only:

- additive/idempotent Episode, Link and Event storage;
- deterministic/versioned identity builder;
- source adapters/linker and explicit orphan reasons;
- dry-run/backfill/rebuild/audit for supported test sources;
- focused tests and CLI/reporting needed to prove correctness.

FO-1 must not add:

- Unified Worklist UI or change existing Worklist behavior;
- Projection/next-action/routing/SLA runtime;
- new SMS automation or approval behavior;
- appointment/SMS cross-channel reactions;
- automatic closure or escalation;
- Clinical Evidence Assist;
- new Clinical Rule or Hypoglycemia Shadow behavior;
- Write to `clinic_new.db`;
- fabricated relation, event, outcome or evidence.

## FOUX-V1 feature flags

```text
FOLLOWUP_EPISODES_ENABLED
FOLLOWUP_PROJECTION_SHADOW
FOLLOWUP_UNIFIED_WORKLIST_READONLY
FOLLOWUP_UNIFIED_WORKLIST_ACTIONS
FOLLOWUP_AUTO_ROUTING
FOLLOWUP_STRUCTURED_CONTACT
FOLLOWUP_SMS_AUTO_GUARDED
FOLLOWUP_APPOINTMENT_SYNC
FOLLOWUP_EVIDENCE_ASSIST
FOLLOWUP_AUTOMATION_HEALTH
```

All default OFF. In FO-1, only `FOLLOWUP_EPISODES_ENABLED` may be consumed, solely to gate Episode infrastructure. Default-OFF startup must preserve existing runtime behavior exactly.

## Permanent safety boundaries

- `webapp/clinic_new.db` is read-only from Specialist Clinic.
- Existing source truths remain authoritative.
- Episode is operational linkage, not clinical truth.
- Clinical Task completion requires governed outcome evidence.
- Appointment booking does not complete a Clinical Task.
- No medication, diagnosis, referral or dose action is automated.
- SMS consent, quiet hours, cap, cooldown, idempotency and provider guards remain mandatory.
- Clinical Rule content and Hypoglycemia Shadow are outside FOUX-V1.
- Append-only event tables are never updated or deleted.
- Backfill only creates relations that can be proven from current source rows.
- Unsupported/ambiguous rows receive an orphan reason; they do not receive guessed links.

## FO-1 required tests

- migration on fresh DB, copied/existing DB and rerun;
- UPDATE/DELETE rejection for append-only events;
- immutable Episode identity;
- deterministic identity and content hashes;
- duplicate source link idempotency;
- source/patient mismatch rejection;
- dry-run and real backfill parity;
- repeated backfill creates no duplicates;
- source truth hashes/rows unchanged;
- feature default OFF changes no existing route/UI/Scheduler behavior;
- full Specialist Clinic suite;
- Accounting suite when governance/shared files change.

## PR contract

Every FOUX-V1 PR must state:

- tranche and Requirement IDs;
- exact scope and anti-scope;
- schema/data impact;
- feature flag and default;
- focused/full test evidence;
- rollback path;
- UX effect;
- proof that clinical safety and accounting read-only boundaries remain intact.

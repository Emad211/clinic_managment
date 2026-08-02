# Specialist Clinic — Agent Instructions

This file is the nearest mandatory instruction source for every change under
`specialist_clinic/`.

## Mandatory read order

Before editing code, schema, UI, tests or documentation in this tree, read and reconcile:

1. repository `PROJECT_STATE.md` and `PROJECT_STATE.json`;
2. root `AGENTS.md`;
3. this file;
4. `graphify-out/GRAPH_REPORT.md` when available;
5. the code-adjacent contract for the stream being changed.

For Follow-up, Worklist, Task, SMS, Contact, Appointment or operational automation work,
the code-adjacent canonical sources are:

```text
docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md
docs/FOLLOWUP_ORCHESTRATION_UX_V1_BASELINE.md
```

Conversation memory, old branches and historical PR bodies never override current
`main`, `PROJECT_STATE.*` or the canonical plan.

## Current FOUX-V1 gate

Program: `FOUX-V1 — Follow-up Orchestration & UX v1`

Current permitted tranche:

```text
FO-0 — Governance, Baseline & Registration
```

Current state:

```text
repository baseline recorded
live operational counts pending read-only operator capture
FO-1 and later blocked
```

Until the FO-0 exit gate is explicitly closed, do not add:

- `followup_episodes`, links, events or projection schema;
- backfill or source-link mutations;
- new Scheduler jobs;
- next-action/routing runtime services;
- unified Worklist behavior;
- automatic routine SMS;
- appointment/SMS cross-channel transitions;
- Clinical Evidence Assist;
- any runtime consumer of a registered FOUX-V1 feature flag.

## FOUX-V1 feature flags

All flags below must default to OFF in FO-0:

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

A later tranche may consume only its declared flag and must include focused tests,
rollback, Project State update and explicit requirement IDs.

## Permanent safety boundaries

- `webapp/clinic_new.db` is read-only from Specialist Clinic.
- Existing source truths remain authoritative; orchestration never rewrites clinical
  facts, recommendations, decisions or evidence.
- Clinical Task completion requires governed outcome evidence.
- Appointment booking does not complete a Clinical Task.
- No medication, diagnosis, referral or dose action is automated.
- Consent, quiet hours, daily cap, cooldown, idempotency and provider guardrails remain
  mandatory for SMS.
- Clinical Rule content and Hypoglycemia Shadow are outside FOUX-V1 scope.
- Append-only event tables are never updated or deleted.

## FO-0 validation

Focused test:

```bash
cd specialist_clinic
python -m pytest tests/test_followup_orchestration_fo0.py -q --tb=short
```

Full suite:

```bash
cd specialist_clinic
python -m pytest tests -q --tb=short --junitxml=pytest-specialist.xml
```

The read-only live baseline command is documented in
`docs/FOLLOWUP_ORCHESTRATION_UX_V1_BASELINE.md`. Never commit invented operational
counts or raw PHI.

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

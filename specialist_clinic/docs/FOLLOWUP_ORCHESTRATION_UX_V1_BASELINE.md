# Follow-up Orchestration & UX v1 — FO-0 Baseline & Attestation

> **Program:** `FOUX-V1`
>
> **Tranche:** `FO-0 — Governance, Baseline & Registration`
>
> **Canonical plan:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **Tracking issue:** `#71`
>
> **Implementation PR:** `#72`
>
> **Merge commit:** `901dbfdf9c358ecc09d2a60a0680f6a4a8370d17`
>
> **Status:** `VALIDATED`
>
> **Environment data classification:** `TEST_ONLY / RESETTABLE`

---

## 1. Baseline decision

FO-0 was originally designed to separate repository facts from live production metrics. The owner has now explicitly attested that the current Specialist Clinic database contains test data only. There is no production patient cohort whose operational counts must be preserved as a business baseline.

Therefore the correct FO-0 evidence is:

```text
repository and UI baseline
+ deterministic aggregate fixture coverage
+ database read-only capture utility
+ owner test-only attestation
+ no FOUX runtime/schema behavior
+ full CI green
```

A numeric snapshot of one resettable local test database is not treated as product evidence because it changes after reset, seed and manual test operations. Production-volume and usability metrics are deferred to the controlled Pilot in FO-10.

This decision does not weaken privacy or safety controls. Before any real patient data is entered, the environment classification must be changed and a production-readiness review must be performed.

---

## 2. Current source-of-truth map

| Concern | Current source | Mutation contract |
|---|---|---|
| Administrative follow-up | `followup_tasks` excluding governed engines | compact mutable lifecycle |
| Clinical task identity | `followup_tasks` with `source_engine='clinical_v2'` | immutable identity |
| Clinical task state | `clinical_task_events` | append-only linear stream |
| Clinical completion evidence | `clinical_outcome_events` | append-only and required |
| Encounter commitment identity | `care_plan_commitments` | immutable |
| Encounter commitment state | `care_plan_commitment_events` | append-only |
| Contact history | `followup_contact_events` | append-only |
| Appointment | `appointments` | existing appointment workflow |
| Engagement candidate | `engagement_approvals` | approval state machine |
| Engagement dedupe | `engagement_dispatch` | idempotent ledger |
| SMS state | `sms_messages` | submission and delivery reconciliation |
| Scheduler ownership | `operational_leases` | lease and fencing |
| Scheduler result | `operational_job_runs` | durable idempotent job key |

FO-0 introduced no Episode, Link, Projection or Outbox table.

---

## 3. Existing UX baseline

Current staff path is split across:

```text
/followups/
/sms/approvals
SMS delivery report
appointment pages
patient record
clinical task lifecycle forms
encounter commitment forms
```

Observed repository-level UX facts:

- administrative, clinical and encounter-plan work appear in one Worklist but have different lifecycle contracts;
- one unified `next_action` field does not exist;
- assignment is not consistently automatic;
- SMS approval and Worklist task are separate screens;
- message delivery, appointment and task do not share one Episode timeline;
- technical states are often exposed directly;
- callback and closure still need manual coordination;
- Scheduler health is primarily log-based.

These facts are stable code/UI evidence and remain the comparison baseline for FO-2 and FO-3.

---

## 4. Deterministic test evidence

`tests/test_followup_orchestration_fo0.py` creates a synthetic SQLite fixture and proves:

- all ten feature flags default to OFF;
- no runtime source consumes the flags;
- no FOUX table is declared;
- the aggregate capture utility uses `mode=ro` and `PRAGMA query_only=ON`;
- database hash is unchanged after capture;
- output contains aggregate values only and no patient name or phone;
- Project State, plan, baseline and nearest Agent instructions are consistent.

The aggregate utility remains available for any local test database:

```powershell
python .\specialist_clinic\scripts\capture_followup_fo0_baseline.py `
  --database "C:\path\to\specialist.db" `
  --output ".\followup_fo0_test_baseline.json"
```

Its output is diagnostic test evidence, not a production KPI baseline.

---

## 5. Feature flags at FO-0 exit

All default OFF and have no runtime consumer:

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

---

## 6. CI evidence

Final successful run for PR #72:

```text
GitHub Actions run = 30770326953
Specialist Clinic  = 731 passed in 320.50s
Accounting         = 54 passed in 3.05s
Total              = 785 passed
```

The first run found a false-positive in the schema guard; the PR was not merged. The guard was corrected to detect actual `CREATE TABLE` declarations rather than matching a feature-flag name, and the full suite was rerun successfully.

---

## 7. No-change attestation

FO-0 made no changes to:

```text
clinical rule content
clinical activation
Hypoglycemia Shadow
SMS sending behavior
Worklist behavior
Scheduler jobs
SQLite schema
migration/backfill
data records
webapp/
clinic_new.db
```

Only governance, default-off flags, documentation, a read-only capture utility and tests were added.

---

## 8. Exit gate

| Gate | Result |
|---|---|
| Canonical plan merged | PASS |
| Stream registered | PASS |
| Repository/UI baseline stored | PASS |
| Test-only classification attested | PASS |
| Deterministic aggregate baseline tested | PASS |
| All flags OFF | PASS |
| No runtime consumer | PASS |
| No FOUX schema | PASS |
| Full Specialist and Accounting CI | PASS |
| FO-0 final status | VALIDATED |
| FO-1 | AUTHORIZED |

---

## 9. Production transition warning

Before first real patient data or real clinic rollout:

1. remove the `TEST_ONLY` environment assumption from Project State;
2. run privacy/security and backup/restore review;
3. capture a pre-pilot production baseline without PHI;
4. verify role and consent configuration;
5. keep all automation flags OFF until the relevant tranche gates are satisfied.

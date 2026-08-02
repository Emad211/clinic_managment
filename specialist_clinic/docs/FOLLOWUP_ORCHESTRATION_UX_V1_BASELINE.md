# Follow-up Orchestration & UX v1 — FO-0 Baseline

> **Program:** `FOUX-V1`
>
> **Tranche:** `FO-0 — Governance, Baseline & Registration`
>
> **Canonical plan:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **Tracking issue:** `#71`
>
> **Repository baseline:** `main@86981354e48c06667b115b2c854a39e3f611e733`
>
> **Captured:** `2026-08-03` (Tehran)
>
> **Status:** `REPOSITORY_BASELINE_RECORDED / LIVE_OPERATIONAL_COUNTS_PENDING`

---

## 1. Purpose and evidence boundary

This document records the state that exists **before** any FOUX-V1 schema,
projection, routing, SMS automation, cross-channel transition or new Worklist action is
implemented.

FO-0 has two distinct baseline classes:

1. **Repository baseline** — code, UI paths, source-of-truth contracts, feature flags
   and known manual interactions. This is reproducible from Git.
2. **Operational baseline** — aggregate counts from the actual deployment
   `specialist.db`. The production database is not committed to the repository and is
   not accessible through GitHub, so those values must be captured by an operator using
   the committed read-only utility. Values are never guessed or copied from seed data.

The live capture remains a formal gate. FO-1 must not start while the stream status is
`LIVE_BASELINE_PENDING`.

---

## 2. Scope

Included:

- existing Worklist and follow-up paths;
- administrative tasks;
- Clinical Engine v2 task projection and lifecycle;
- encounter-plan commitments;
- contact events;
- engagement approvals and dispatch ledger;
- SMS submission and delivery state;
- appointments and booking from Worklist;
- scheduler durable job state;
- current manual interaction count;
- default-off FOUX-V1 feature gates.

Excluded:

- clinical Rule changes or approval claims;
- Hypoglycemia Shadow expansion;
- writes to `webapp/` or `clinic_new.db`;
- migration or creation of FOUX-V1 tables;
- production PHI, patient rows, message bodies, clinical values or free-text notes;
- claims about live operational volumes before the read-only capture is run.

---

## 3. Current source-of-truth map

| Concern | Current source of truth | Current mutation model |
|---|---|---|
| Administrative follow-up | `followup_tasks` excluding governed engines | compact mutable status workflow |
| Clinical task identity | `followup_tasks` with `source_engine='clinical_v2'` | identity immutable |
| Clinical task state | head of append-only `clinical_task_events` | governed append-only transitions |
| Clinical completion evidence | `clinical_outcome_events` | append-only; required for completion |
| Encounter commitment identity | `care_plan_commitments` + task link | immutable |
| Encounter commitment state | head of `care_plan_commitment_events` | append-only |
| Contact history | `followup_contact_events` | append-only |
| Appointment | `appointments` | current appointment workflow |
| Engagement candidate | `engagement_approvals` | approval state machine |
| Engagement dedupe/cooldown | `engagement_dispatch` | idempotent ledger |
| SMS submission/delivery | `sms_messages` | provider submission + reconciliation |
| Campaign execution | campaign lifecycle/audience/message records | governed execution |
| Scheduler ownership | `operational_leases` | lease + fencing token |
| Scheduler durable job result | `operational_job_runs` | idempotent job key lifecycle |

The following FOUX-V1 stores **do not exist in FO-0**:

```text
followup_episodes
followup_episode_links
followup_episode_events
followup_work_item_projection
contact_attempt_events (FOUX-specific replacement/extension)
automation_decision_events
operational_outbox
```

Existing `followup_contact_events` remains authoritative until a later tranche defines
an additive migration or adapter. FO-0 does not rename or replace it.

---

## 4. Current orchestration flow

### 4.1 Administrative engagement

```text
Scheduler tick
→ EngagementService.collect_due_events
→ appointment_reminder / refill_due / lapsed
→ manager-configured channel: worklist / sms / both / off
→ administrative followup task and/or engagement approval
→ physician/authorized user approves SMS
→ provider submission
→ delivery reconciliation
→ operator records contact, books appointment or closes administrative task
```

The Worklist task and the SMS approval are related through event/period data and
ledgers, but the current UI does not present them as one unified episode with one owner,
one waiting reason and one next action.

### 4.2 Clinical task

```text
exact current Clinical Engine v2 run
→ audited FIRED recommendation
→ optional clinician acceptance
→ immutable task identity
→ append-only lifecycle
→ outcome evidence
→ explicit governed completion
```

Clinical safety is intentionally stricter than administrative follow-up. Appointment
booking only records `SCHEDULED`; it never completes a clinical task.

### 4.3 Encounter-plan commitment

```text
signed encounter document
→ immutable commitment
→ linked Worklist identity
→ append-only commitment events
→ evidence-backed completion or explicit cancellation
```

### 4.4 Scheduler

The in-process Scheduler starts with the application, waits before its first tick and
then runs periodic jobs behind a SQLite lease, fencing token and durable job keys.
FO-0 does not add a new job, modify cadence or consume any new feature flag.

---

## 5. Static UX interaction baseline

### 5.1 Measurement method

- starting point is an authenticated user with the current Worklist already open;
- one interaction means one deliberate click/tap, selection or form submission;
- typing characters is not counted, but focusing/choosing a required date or option is;
- browser back/forward is not assumed;
- counts are the **minimum** path visible in current templates, not usability-test
  medians;
- the target KPI from the canonical plan is a primary action in at most two
  interactions and next-action comprehension in at most five seconds.

### 5.2 Current minimum paths

| Scenario | Current minimum interactions | Current screen transitions | Baseline observation |
|---|---:|---:|---|
| Close a visible administrative task as done | 1 | 0 | Fast, but closure is disconnected from SMS/appointment outcome |
| Reject a visible administrative task | 1 | 0 | No unified disposition timeline |
| Record a simple contact outcome | 3 | 0 | expand form → choose outcome → submit |
| Record callback requested with date | 4 | 0 | expand → choose outcome → set date → submit |
| Approve a pending routine SMS from Worklist | 3 | 1 | approval tab → expand patient → approve/send |
| Approve SMS, inspect delivery, return and close task | 6 | 3 | approval → delivery report → Worklist → manual close |
| Add a follow-up SMS candidate from a patient group | 1 | 0 | candidate still requires separate approval screen |
| Book an appointment for existing task(s) | at least 3 | 0 | select/confirm tasks → select date → submit; time may add one interaction |
| Complete a clinical task without an existing outcome | at least 4 plus data entry | 0 | open management → record outcome → submit → complete with evidence |
| Understand one patient across task, approval and delivery | at least 2 navigation actions | at least 2 | state is distributed across Worklist, approval queue and delivery report |

### 5.3 Current information architecture

The shared Messaging Hub exposes separate tabs for:

```text
campaigns
approval queue
delivery report
engagement configuration
clinical alerts
contact worklist
```

This gives access to each subsystem, but the user must reconstruct the relationship
between a task, an approval, an SMS delivery, a contact and an appointment.

### 5.4 Current ownership and next-action limitations

- administrative automatic task creation may leave `assigned_to` blank;
- clinical and encounter-plan assignment live in current event heads;
- no unified `owner_role` exists;
- no central `next_action_code`, `waiting_reason` or `blocked_reason` exists;
- Worklist ordering is driven mainly by current due value and ID;
- `action_due_at` and source target time are not consistently separate;
- technical state labels and multiple independent forms remain visible;
- a single patient can have several task rows but no episode-level summary of SMS,
  contact, appointment and outcome state.

---

## 6. Operational count baseline

### 6.1 Current status

```text
LIVE_OPERATIONAL_COUNTS = PENDING_DEPLOYMENT_CAPTURE
```

Reason: no production `specialist.db` is stored in Git and this environment has no
access to the deployed database. Recording zero, seed counts or inferred values would
be misleading.

### 6.2 Canonical read-only command

From the repository root:

```bash
python specialist_clinic/scripts/capture_followup_fo0_baseline.py \
  --database /absolute/path/to/specialist.db \
  --output specialist_clinic/docs/evidence/followup_fo0_live_baseline.json
```

Windows PowerShell:

```powershell
python .\specialist_clinic\scripts\capture_followup_fo0_baseline.py `
  --database "C:\path\to\specialist.db" `
  --output ".\specialist_clinic\docs\evidence\followup_fo0_live_baseline.json"
```

The utility:

- opens SQLite with URI `mode=ro`;
- enables `PRAGMA query_only=ON`;
- selects aggregate counts only;
- emits no PHI;
- records file SHA-256, size and `quick_check`;
- hashes the file before and after capture and fails if it changed.

### 6.3 Required live metrics

```text
active_patients
open_admin_tasks
unassigned_open_admin_tasks
overdue_open_admin_tasks
current_nonterminal_clinical_tasks
unassigned_current_clinical_tasks
current_nonterminal_plan_commitments
unassigned_current_plan_commitments
current_open_work_items_total
current_unassigned_work_items_total
unassigned_open_work_item_percent
pending_engagement_approvals
failed_or_unknown_engagement_approvals
engagement_dispatch_rows
sms_delivered
sms_inflight_or_unknown
sms_failed
due_scheduled_campaigns
scheduled_appointments
no_show_appointments
contact_events
callbacks_due_from_latest_contact
scheduler_failed_job_keys
scheduler_running_job_keys
```

A missing table is represented by `null`, not zero. This distinguishes a schema not
installed from an installed table with no rows.

### 6.4 Evidence handling

The JSON output may be committed only after confirming it contains aggregate values and
no deployment path beyond the database file name. If local policy treats database hash
as sensitive, store it in a restricted release artifact and commit a redacted attestation
with the same capture timestamp and metric values.

---

## 7. FO-0 feature-flag baseline

The following names are registered in `src/config/settings.py` and default to `False`:

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

FO-0 rule:

> A registered flag may be parsed from the environment, but no runtime service, route,
> template, schema installer, scheduler job or JavaScript path may consume it.

Later tranches must change the corresponding guard test explicitly and state which flag
became active, in which mode, with what rollback.

---

## 8. Invariants frozen by FO-0

1. `PROJECT_STATE.*` remains superior to this report and the implementation plan.
2. `main` remains product authority.
3. Specialist Clinic has read-only access to `clinic_new.db`.
4. No FOUX-V1 table is installed in FO-0.
5. No existing task, approval, SMS, appointment or contact row is backfilled in FO-0.
6. All ten flags are OFF by default.
7. No registered flag changes runtime behavior in FO-0.
8. Administrative and clinical source truths remain separate and authoritative.
9. Clinical Task completion still requires governed evidence.
10. Appointment booking never completes a Clinical Task.
11. Clinical recommendation acceptance remains human-controlled.
12. Consent, quiet hours, cap, cooldown and idempotency remain mandatory.
13. Rule content and Hypoglycemia Shadow remain outside this stream.
14. The capture utility must remain aggregate-only and read-only.
15. FO-1 is blocked until live operational counts and CI evidence are attached.

---

## 9. Known baseline risks

| ID | Risk | Current evidence | FO tranche expected to address |
|---|---|---|---|
| B-01 | User reconstructs one journey across several tabs | Worklist, approval and delivery are separate | FO-2/FO-3 |
| B-02 | No central next action/wait/block contract | no unified projection | FO-2 |
| B-03 | Automatic administrative tasks may be unassigned | `assigned_to` may be blank | FO-4 |
| B-04 | Routine SMS requires manual approval | approval queue contract | FO-6 |
| B-05 | Approval can become stale relative to source | no FOUX freshness contract | FO-6 |
| B-06 | SMS/appointment state does not drive one episode | no operational outbox | FO-7 |
| B-07 | Contact outcome still requires manual next-step interpretation | append-only event exists, policy automation does not | FO-5 |
| B-08 | Scheduler failures are primarily log/data oriented | no unified health UI | FO-9 |
| B-09 | Existing reason-level task dedupe can hide multiple source items | administrative task identity is coarse | FO-1/FO-2 |
| B-10 | Production count baseline is not yet attached | deployment DB unavailable to GitHub | FO-0 gate |

---

## 10. Test and CI evidence required for FO-0

Focused guards must prove:

- Project State registers the same program, plan and baseline paths;
- all expected flags exist and are false in a clean environment;
- flag names are not referenced outside settings/tests/docs;
- no FOUX-V1 schema tables are installed by current runtime code;
- read-only capture returns expected aggregate counts on a synthetic database;
- the synthetic database hash is unchanged;
- output does not include sample names or phone numbers;
- canonical plan and baseline documents remain discoverable.

Before merge:

```text
focused FO-0 tests = green
full specialist tests = green
accounting tests = green if shared files changed
CI status = green
schema/runtime behavior diff = none
```

---

## 11. Exit-gate ledger

| Gate | State at registration | Evidence |
|---|---|---|
| Canonical plan on `main` | PASS | PR #70 / merge `86981354...` |
| Tracking issue and owner | PASS | Issue #71 / `Emad211` |
| Repository baseline report stored | PASS | this file |
| Source truths and invariants listed | PASS | sections 3 and 8 |
| Static flow/click baseline stored | PASS | section 5 |
| Ten feature flags registered OFF | PENDING_PR | settings change in FO-0 branch |
| Runtime does not consume flags | PENDING_CI | governance guard |
| No FOUX schema/runtime behavior change | PENDING_CI | governance guard + diff review |
| Live operational counts captured | **PENDING_OPERATOR_CAPTURE** | read-only JSON required |
| Full CI green | PENDING_PR_CI | GitHub Actions |
| FO-0 complete | **BLOCKED** | live capture and CI required |
| FO-1 allowed | **NO** | explicit next-tranche authorization required |

---

## 12. Rollback

FO-0 rollback removes:

- stream registration in `PROJECT_STATE.md/json`;
- the ten unused settings flags;
- this baseline report;
- the read-only capture utility;
- FO-0 governance tests.

There is no database rollback because FO-0 creates no table, migration, row, scheduler
job or runtime branch.

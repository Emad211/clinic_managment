# FOUX-V1 FO-5 — Local Owner UX Acceptance

> **Gate:** `FO-5 TECHNICALLY_VALIDATED / OWNER_UX_PENDING`
>
> **Acceptance Issue:** `#107`
>
> **Reviewed runtime merge:** `94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852`
>
> **Environment:** `TEST_ONLY / SYNTHETIC_OR_RESETTABLE`
>
> **Real patient data:** `FORBIDDEN`

---

## 1. Technical evidence already passed

```text
Implementation Issue = #105
Implementation PR    = #106
Final head           = 2ab1cb1ec956bb9534dea7dd383b76bbf5fb3f5c
Merge commit         = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
Final CI             = 30865955479
Specialist           = 801 passed
Accounting           = 54 passed
Review threads       = all resolved
```

Technical validation proves the following contracts, but it does not replace owner UX acceptance:

- append-only authoritative contact occurrence in `followup_contact_events`;
- contact link to the Episode and PHI-minimized Episode events;
- deterministic outcome → next-action policy;
- future callback validation;
- bounded retry and one-time escalation;
- threshold escalation leaves no due callback in Source Truth;
- routing kill switch is a prerequisite for FO-5;
- Jalali callback date plus a separate time field;
- exact replay idempotency;
- stale, terminal, permission and ownership fail-closed behavior;
- no automatic SMS, Appointment mutation, clinical completion/decision or Accounting write.

---

## 2. Fast local start on Windows

From the repository root:

```powershell
cd .\specialist_clinic
.\scripts\start_fo5_local_review.ps1
```

The launcher:

1. requires the local `.venv` Python and `specialist.db`;
2. creates a timestamped backup under `specialist_clinic/backups/`;
3. enables only FO-1 through FO-5 prerequisites for the child process;
4. explicitly prepares Episodes and the Unified projection;
5. starts `start.py`, which opens the local browser;
6. restores the caller's previous environment-variable values after the server exits.

To use another resettable database:

```powershell
.\scripts\start_fo5_local_review.ps1 -Database .\path\to\resettable-specialist.db
```

To keep an already-prepared projection:

```powershell
.\scripts\start_fo5_local_review.ps1 -SkipPrepare
```

Do not point the review launcher at a database containing real patient data.

---

## 3. Manual start equivalent

```powershell
cd .\specialist_clinic

$env:FOLLOWUP_EPISODES_ENABLED = "1"
$env:FOLLOWUP_PROJECTION_SHADOW = "1"
$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
$env:FOLLOWUP_UNIFIED_WORKLIST_ACTIONS = "1"
$env:FOLLOWUP_AUTO_ROUTING = "1"
$env:FOLLOWUP_STRUCTURED_CONTACT = "1"

.\.venv\Scripts\python.exe scripts\prepare_seeded_followup_view.py `
  --database specialist.db

.\.venv\Scripts\python.exe start.py
```

The following flags must remain OFF during FO-5 review:

```text
FOLLOWUP_SMS_AUTO_GUARDED
FOLLOWUP_APPOINTMENT_SYNC
FOLLOWUP_EVIDENCE_ASSIST
FOLLOWUP_AUTOMATION_HEALTH
```

---

## 4. Review path

After login, open the Follow-up hub and enter the Unified Worklist. The review is performed only on seeded/resettable records.

### A. List comprehension

Confirm that an operator can understand, without opening multiple screens:

- patient and reason;
- current state and SLA;
- queue and actual owner as separate concepts;
- last contact outcome;
- operational next action;
- callback time when present.

### B. Detail and contact form

Confirm that the form clearly communicates:

- result of contact;
- optional Jalali callback date and separate time;
- callback requirement for `CALLBACK_REQUESTED`;
- note is required only for `OTHER`;
- contact recording does not send SMS;
- contact recording does not create or change an Appointment;
- contact recording does not create a clinical decision or complete clinical work.

### C. Timeline privacy

Record a short, obviously recognizable TEST note. Confirm:

- the result and operational next action are visible;
- the free note itself is not shown in the Unified Timeline;
- the Timeline does not expose SMS body or clinical values.

---

## 5. Required scenario matrix

### Scenario 1 — Successful contact

Use `REACHED`.

Expected:

- result is visible in list/detail;
- next action is continuation of the current path;
- no callback remains;
- no queue change is implied.

### Scenario 2 — Requested callback

Use `CALLBACK_REQUESTED` with a future Jalali date and time.

Expected:

- missing date/time is rejected clearly;
- past time is rejected clearly;
- accepted callback is visible in list/detail/Timeline;
- no SMS or Appointment mutation occurs.

### Scenario 3 — Retry before threshold

Use `NO_ANSWER` or `BUSY` once or twice.

Expected:

- a future callback is retained;
- failed-attempt count is understandable;
- the item is not escalated prematurely.

### Scenario 4 — Unreachable threshold

Record the third consecutive `NO_ANSWER`/`BUSY`.

Expected:

- exactly one escalation is represented;
- route changes to Manager;
- no future callback remains in the current authoritative contact row;
- repeating/reloading does not create duplicate escalation.

### Scenario 5 — Invalid phone

Use `PHONE_INVALID`.

Expected:

- retry/callback stops;
- next action is contact-data repair;
- route changes to Reception;
- no message is sent.

### Scenario 6 — Patient reports an appointment

Use `APPOINTMENT_BOOKED`.

Expected:

- UI says to wait/check through the governed Appointment path;
- no Appointment is created, modified or cancelled;
- no Clinical Task is completed.

### Scenario 7 — Physician review

Use `ESCALATED_TO_PHYSICIAN`.

Expected:

- route changes to Physician review;
- copy states that this is operational escalation only;
- no diagnosis, treatment or clinical outcome is generated.

### Scenario 8 — Other result

Use `OTHER`.

Expected:

- note is required;
- the item is routed for manager review;
- free note stays outside the Unified Timeline.

### Scenario 9 — Kill switch

Stop the server, set:

```powershell
$env:FOLLOWUP_STRUCTURED_CONTACT = "0"
```

Start again with FO-3/FO-4 flags still enabled.

Expected:

- FO-5 form and contact summary are hidden;
- FO-5 POST route returns 404;
- Unified read-only and ownership features remain usable.

Also verify that setting `FOLLOWUP_AUTO_ROUTING=0` disables FO-5, because FO-5 is not allowed to bypass the routing kill switch.

---

## 6. Acceptance criteria

Owner acceptance may be true only when all are satisfied:

```text
critical UX defects                         = 0
structured outcomes understandable         = PASS
Jalali callback entry understandable       = PASS
callback/error copy understandable         = PASS
retry and escalation behavior understandable = PASS
queue changes understandable               = PASS
SMS/Appointment/clinical non-actions clear = PASS
free-note privacy clear                     = PASS
feature-off rollback understandable        = PASS
```

Minor non-blocking defects may be recorded, but they must not hide or misrepresent the next action, owner, callback, escalation, or safety boundary.

---

## 7. Acceptance record

Post the following in Issue #107 after review:

```text
FO5_UX_ACCEPTED = true|false
reviewer = Emad211
reviewed_commit = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
reviewed_on_test_data = true
critical_ux_defects = <number>
notes = <review notes>
```

FO-6 remains blocked until `FO5_UX_ACCEPTED = true` is recorded and a separate FO-6 governance authorization passes full CI.

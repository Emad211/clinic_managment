# وضعیت حاکم پروژه — Clinic Management

> **Source of Truth مدیریتی مخزن.** پیش از هر توسعه، وضعیت واقعی GitHub، این فایل و `PROJECT_STATE.json` باید خوانده شوند. حافظهٔ گفتگو یا branch قدیمی به‌تنهایی معتبر نیست.

- آخرین ممیزی: `2026-08-03 18:59 +03:30`
- شاخهٔ مرجع: `main`
- head مرجع: `020803868e1c2755f7669d52da92cb8050a46018`
- وضعیت کلی: `PRODUCT_OPERATIONAL / PRE_PRODUCTION_TEST_DATA / CLINICAL_CONTENT_NOT_APPROVED / GOVERNANCE_RECONCILIATION_REQUIRED`

---

## 1. جریان‌های مستقل

1. `webapp/` — حسابداری Flask + SQLite؛
2. `specialist_clinic/` — محصول مدیریت بیماری مزمن؛
3. Clinical Engine v2؛
4. Clinical Rule Research؛
5. Hypoglycemia Shadow؛
6. Follow-up Orchestration & UX v1؛
7. Release Engineering؛
8. Halqe Migration.

هیچ جریان، اختیار ضمنی برای تغییر جریان دیگر ندارد.

---

## 2. طبقه‌بندی محیط

```text
specialist.db data class = TEST_ONLY / SYNTHETIC_OR_RESETTABLE
real patient PHI         = NOT EXPECTED
reset/reseed             = ALLOWED
```

این attestation فقط برای محیط فعلی است. پیش از دادهٔ واقعی، production-readiness، privacy، backup/restore، consent/role review و baseline بدون PHI اجباری است.

---

## 3. ماتریس جریان‌ها

| جریان | وضعیت | اختیار فعلی | ممنوعیت |
|---|---|---|---|
| محصول عملیاتی | `ACTIVE_PRODUCT_PRE_PRODUCTION` | رفتار واقعی main | تغییر بالینی بدون گیت |
| FOUX-V1 | `FO_0/1/2_VALIDATED / FO_3_RUNTIME_AND_COPY_REPAIRS_TECHNICALLY_VALIDATED / UX_REVIEW_PENDING` | مرور لوکال یا focused FO-3 defect fix | FO-4، mutation، claim، SMS یا routing |
| Clinical Engine v2 | `INFRASTRUCTURE_IMPLEMENTED / ACTIVATION_GATED` | runtime/audit | activation بدون approval |
| Rule package | `LEGACY_DRAFT_QUARANTINED` | provenance/test | clinical use |
| ADA research | `FROZEN_V0_9_4` | evidence draft | runtime authority |
| Hypoglycemia Shadow | `PAUSED_FOR_RECONCILIATION` | experiment | expansion/Rule/Task/Alert |
| Shadow disposition | `PAUSED_DO_NOT_MERGE` | ندارد | merge/development |
| Release A15 | `STALE_DIVERGED_DRAFT` | requirement reference | direct merge |
| Halqe | `SEPARATE_STRATEGIC_STREAM` | design/rehearsal | automatic cutover |

---

## 4. FOUX-V1

### منابع حاکم

```text
Plan:
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md

Baseline:
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_BASELINE.md
```

Plan version: `1.4.4`

### FO-0 — VALIDATED

```text
Issue #71 / PR #72/#73
merge 901dbfdf9c358ecc09d2a60a0680f6a4a8370d17
731 Specialist + 54 Accounting
```

### FO-1 — VALIDATED

```text
Issue #74 / PR #75
merge 15ef1585c069a74c26fbc0ce859e03906e5f475a
736 Specialist + 54 Accounting
4 Episodes / 12 Links / idempotent
```

```text
followup_episodes              immutable identity
followup_episode_links         immutable patient-safe links
followup_episode_events        append-only linear lineage
```

### FO-2 — VALIDATED

```text
Issue #77 / PR #78
merge 6c6e33203376a32165418e0d3c6f2a4a48253e7b
CI 30773195914
747 Specialist + 54 Accounting
100% legacy coverage / 0 hidden / deterministic rebuild
```

```text
followup_work_item_projection   rebuildable disposable cache
source-state readers            read-only
FOUX-NEXT-ACTION-V1             fail-closed policy
state classes                   ACTION_REQUIRED / WAITING / BLOCKED / TERMINAL
role                            proposal only
```

### FO-3 — TECHNICALLY VALIDATED

```text
Issue #80 / PR #81
merge afed3545c0a90a1ed7ff7e0a892df89fffac00c2
Governance merge 527b9c981e742d0cbd796766535044414580ab14
CI 30775348057
754 Specialist + 54 Accounting
```

```text
GET /followups/unified/
GET /followups/unified/<episode_id>
feature flag: FOLLOWUP_UNIFIED_WORKLIST_READONLY
```

مرزهای فنی:

- GET-only و POST=405؛
- flag OFF → 404/navigation hidden؛
- pagination/search/filter whitelist؛
- query count محدود و batch links؛
- Timeline deterministic و PHI-minimized؛
- Source Truth/Projection digest بعد از GET بدون تغییر؛
- Worklist قدیمی authority اقدام؛
- هیچ SMS، Appointment، Scheduler، Rule، Shadow یا Accounting behavior تغییر نکرد.

### FO3_UI_500 — RESOLVED TECHNICALLY

```text
Issue #84 / PR #85
Final head 8809252b2ca25fb55f200d783016d30ec10134d7
Merge 8f851c90da5a81f4b7ffce43eaa5bf6010d58fa2
Root-cause CI 30808217800
Final CI 30809363219
761 Specialist + 54 Accounting
```

علت قطعی:

```text
JINJA_DICT_METHOD_COLLISION_ON_ITEMS_KEY
model.items → dict.items method
```

اصلاح:

```jinja2
model['items']
timeline['items']
```

Hardening ثانویه:

- required-column preflight؛
- recreate فقط برای Projection cache ناسازگار؛
- cache خالی و rebuild صریح؛
- ثابت‌ماندن Source Truth و Episode digest؛
- controlled Persian error state؛
- real Flask/Jinja list and Timeline tests.

### FO3_OPERATOR_PROJECTION_JARGON — RESOLVED TECHNICALLY

```text
Issue #87 / PR #88
Final head 39ebef3b70470f39292faaa7d986e2f1a90a0e80
Merge 020803868e1c2755f7669d52da92cb8050a46018
Final CI 30827033618
762 Specialist + 54 Accounting
```

تغییر فقط در کپی عملیاتی و regression test بود:

- `Projection قدیمی` → `اطلاعات نما قدیمی است`؛
- `سن Projection` → `آخرین بازسازی نما`؛
- readiness stateهای قابل‌مشاهده با متن فارسی عملیاتی؛
- machine readiness codeها و audit فنی حفظ شدند؛
- route، query، schema، cache behavior، Source Truth، workflow و feature defaults تغییر نکردند.

---

## 5. قدم مجاز فعلی

```text
Issue #83 — Post-fix local UX acceptance
```

دستور اجرا:

```powershell
git checkout main
git pull origin main
cd specialist_clinic
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe start.py
```

پس از اجرای یک‌باره و توقف برنامه:

```powershell
$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\rebuild_followup_projection.py `
  --database specialist.db `
  --as-of "2026-08-03 12:00:00" `
  --apply

$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
.\.venv\Scripts\python.exe start.py
```

Attestation:

```text
FO3_UX_ACCEPTED = true|false
reviewer = Emad211
reviewed_commit = 020803868e1c2755f7669d52da92cb8050a46018
reviewed_on_test_data = true
critical_ux_defects = <number>
notes = <observations or defects>
```

---

## 6. Feature Flagها

همه default OFF:

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

در مرور فعلی فقط Read-only flag مصرف می‌شود. Action flags ممنوع‌اند.

---

## 7. Exit Gate برای FO-4

```text
PR #85 runtime repair merged         = PASS
PR #88 operator copy repair merged   = PASS
Final CI 30827033618 green           = PASS
FO3_UX_ACCEPTED=true                 = PENDING
critical_ux_defects=0                = PENDING
governance authorization PR merged   = PENDING
```

تا آن زمان Claim، Assignment، Routing/SLA، Structured Contact automation، SMS automation، Appointment reaction، Outbox/Retry/Auto-close و Evidence Assist مسدودند.

---

## 8. Clinical Engine و Ruleها

```text
Engine infrastructure       = IMPLEMENTED
Clinical content approval   = NOT COMPLETED
Visible clinical activation = BLOCKED
```

Ruleهای `2026.1-draft.3` quarantined هستند و باید `REVALIDATE / REPLACE / RETIRE` شوند. تست فنی معادل clinical approval نیست.

---

## 9. Freeze فعلی

```text
FOUX post-fix local UX review       = ALLOWED
FOUX focused FO-3 defect fix        = ALLOWED IF NEW DEFECT FOUND
FOUX FO-4 and later                 = BLOCKED
New clinical rules                  = PAUSED
Hypoglycemia Shadow expansion       = PAUSED
Disposition branch                  = DO NOT MERGE
Focused bug/security fixes          = ALLOWED
```

---

## 10. قواعد ادامه

1. GitHub، Issue #83، PRهای #85/#88 و plan v1.4.4 خوانده شوند؛
2. فقط post-fix UX review یا focused FO-3 defect fix انجام شود؛
3. علت Incident 500 همان Jinja collision ثبت‌شده است؛
4. schema hardening علت screenshot معرفی نشود؛
5. repair #87 copy-only و technically validated است؛
6. Source Truthها تغییر نکنند؛
7. هر fix جدید full CI و owner re-review می‌خواهد؛
8. بدون owner attestation وارد FO-4 نشوید.

---

## 11. تصمیم فعلی

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 RUNTIME REPAIR = TECHNICALLY VALIDATED
FO-3 OPERATOR COPY REPAIR = TECHNICALLY VALIDATED
FO-3 POST-FIX LOCAL UX ACCEPTANCE = PENDING
FO-4 AND LATER = BLOCKED
```

# وضعیت حاکم پروژه — Clinic Management

> **Source of Truth مدیریتی مخزن.** پیش از هر توسعه، وضعیت واقعی GitHub، این فایل و `PROJECT_STATE.json` باید خوانده شوند. حافظهٔ گفتگو یا branch قدیمی به‌تنهایی معتبر نیست.

- آخرین ممیزی: `2026-08-03 14:12 +03:30`
- شاخهٔ مرجع: `main`
- head مرجع هنگام شروع repair: `527b9c981e742d0cbd796766535044414580ab14`
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

این attestation فقط برای محیط فعلی است. پیش از ورود دادهٔ واقعی، production-readiness، privacy، backup/restore، consent/role review و baseline بدون PHI اجباری است. هیچ shortcut مبتنی بر `TEST_ONLY` وارد runtime نمی‌شود.

---

## 3. ماتریس جریان‌ها

| جریان | وضعیت | اختیار فعلی | ممنوعیت |
|---|---|---|---|
| محصول عملیاتی | `ACTIVE_PRODUCT_PRE_PRODUCTION` | رفتار واقعی main | تغییر بالینی بدون گیت |
| FOUX-V1 | `FO_0/1/2_VALIDATED / FO_3_TECHNICALLY_VALIDATED / LOCAL_UX_BLOCKED_BY_RUNTIME_DEFECT` | فقط repair متمرکز Issue #84 | FO-4، mutation، claim، SMS یا routing |
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

Plan version: `1.4.1`

### FO-0 — VALIDATED

```text
Issue #71
PR #72 / #73
merge 901dbfdf9c358ecc09d2a60a0680f6a4a8370d17
731 Specialist + 54 Accounting
```

### FO-1 — VALIDATED

```text
Issue #74
PR #75
merge 15ef1585c069a74c26fbc0ce859e03906e5f475a
736 Specialist + 54 Accounting
4 Episodes / 12 Links / zero duplicates on second apply
source truth unchanged
```

زیرساخت:

```text
followup_episodes              immutable identity
followup_episode_links         immutable patient-safe links
followup_episode_events        append-only linear lineage
```

### FO-2 — VALIDATED

```text
Issue #77
PR #78
merge 6c6e33203376a32165418e0d3c6f2a4a48253e7b
Final CI run 30773195914
747 Specialist + 54 Accounting
100% legacy coverage
0 hidden legacy sources
100% explainable mismatch
rebuild deterministic
source truth unchanged
```

زیرساخت:

```text
followup_work_item_projection   rebuildable disposable cache
source-state readers            read-only
FOUX-NEXT-ACTION-V1             fail-closed policy
state classes                   ACTION_REQUIRED / WAITING / BLOCKED / TERMINAL
role                            proposal only
CLI                             explicit shadow rebuild
```

### FO-3 — TECHNICALLY VALIDATED

```text
Issue #80
PR #81
final head 14e8bf56782ead4ccef46db05eb8c4b6b034d263
merge afed3545c0a90a1ed7ff7e0a892df89fffac00c2
Governance merge 527b9c981e742d0cbd796766535044414580ab14
Final CI run 30775348057
754 Specialist + 54 Accounting
```

قابلیت‌های merge‌شده:

```text
GET /followups/unified/
GET /followups/unified/<episode_id>
feature flag: FOLLOWUP_UNIFIED_WORKLIST_READONLY
```

مرزهای فنی اثبات‌شده:

- list/detail فقط GET؛
- POST برابر 405؛
- flag OFF برابر 404 و navigation مخفی؛
- pagination/search/filter whitelist؛
- query count محدود و source-link batch؛
- Timeline deterministic و provenance-aware؛
- عدم نمایش message body، note آزاد، raw clinical value و payload JSON؛
- digest Source Truth و Projection بعد از GET بدون تغییر؛
- Worklist قدیمی authority اقدام باقی مانده است؛
- role فقط proposal است؛
- هیچ SMS، Appointment، Scheduler، Rule، Shadow یا Accounting behavior تغییر نکرد.

### Incident جاری — FO3_UI_500

در مرور لوکال واقعی مالک، کلیک روی «نمای یکپارچه» generic HTTP 500 نشان داد.

```text
Incident issue       = #84
Reported by          = Emad211
Exact traceback      = not available at registration
UX acceptance        = BLOCKED
Allowed scope        = focused FO-3 runtime repair only
FO-4                 = BLOCKED
```

Gap طراحی تأییدشده:

- Read Model فقط وجود table را بررسی می‌کرد؛
- required columns و schema compatibility پیش از query کنترل نمی‌شد؛
- SQLite با `CREATE TABLE IF NOT EXISTS` جدول قدیمی را upgrade نمی‌کند؛
- Projection cache ممکن است از نسخهٔ آزمایشی قبلی باقی مانده باشد؛
- schema drift شناخته‌شده نباید generic 500 تولید کند.

Repair مجاز:

- فقط cache disposable `followup_work_item_projection` در صورت incompatibility recreate شود؛
- Episode/Link/Event و تمام Source Truthها بدون تغییر بمانند؛
- Read Model preflight و controlled Persian unavailable state اضافه شود؛
- خطاهای SQLite/schema شناخته‌شده کنترل شوند؛
- خطاهای برنامه‌نویسی ناشناخته پنهان نشوند؛
- full CI و مرور UX مجدد الزامی است.

---

## 5. Feature Flagها

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

در repair فعلی فقط `FOLLOWUP_UNIFIED_WORKLIST_READONLY` مصرف می‌شود. تمام action flags ممنوع‌اند.

---

## 6. Exit Gate Issue #84

Repair فقط وقتی معتبر است که:

1. cache ناقص safely recreate و خالی شود؛
2. migration rerun idempotent باشد؛
3. Source Truth و Episode digest تغییر نکند؛
4. schema drift شناخته‌شده صفحهٔ کنترل‌شده بدهد، نه 500؛
5. schema canonical list/detail را همچنان render کند؛
6. flag OFF و GET-only boundary حفظ شود؛
7. Specialist و Accounting CI کامل سبز باشد؛
8. PR merge شود؛
9. مالک مرور UX را روی commit repair تکرار کند.

---

## 7. اجرای مرور لوکال پس از repair

پس از merge fix:

```powershell
git checkout main
git pull origin main
cd specialist_clinic
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

برنامه یک بار اجرا و بسته شود تا migration cache-compatible اعمال شود. سپس:

```powershell
$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\rebuild_followup_projection.py `
  --database specialist.db `
  --as-of "2026-08-03 12:00:00" `
  --apply

$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
.\.venv\Scripts\python.exe start.py
```

Attestation باید commit repair را ثبت کند و `critical_ux_defects=0` باشد.

---

## 8. وضعیت Specialist Clinic

قابلیت‌های موجود:

- patient link و پروندهٔ طولی؛
- دارو، آلرژی، آزمایش و vital؛
- Appointment و Doctor Queue؛
- Encounter documentation append-only؛
- Plan Commitment و Worklist؛
- Contact Event append-only؛
- SMS consent/approval/campaign/delivery؛
- financial bridge read-only؛
- Scheduler lease/fencing/idempotency؛
- Clinical Engine v2 suggestion-only؛
- FOUX Episode، Projection و Unified Read-only UI.

Specialist Clinic فقط `clinic_new.db` را read-only می‌خواند.

---

## 9. Clinical Engine و Ruleها

```text
Engine infrastructure       = IMPLEMENTED
Clinical content approval   = NOT COMPLETED
Visible clinical activation = BLOCKED
```

Ruleهای `2026.1-draft.3` quarantined هستند و باید `REVALIDATE / REPLACE / RETIRE` شوند. تست فنی معادل clinical approval نیست.

---

## 10. Freeze فعلی

```text
FOUX Issue #84 focused repair      = ALLOWED
FOUX FO-3 local UX review          = BLOCKED UNTIL FIX MERGE
FOUX FO-4 and later                = BLOCKED
New clinical rules                 = PAUSED
Hypoglycemia Shadow expansion      = PAUSED
Disposition branch                 = DO NOT MERGE
Focused bug/security fixes         = ALLOWED
```

---

## 11. قواعد ادامه

هر ایجنت باید:

1. وضعیت واقعی GitHub و Issue #84 را بخواند؛
2. plan v1.4.1، JSON state و این فایل را تطبیق دهد؛
3. فقط branch focused repair را تغییر دهد؛
4. علت دقیق بدون traceback را جعل نکند؛
5. فقط cache disposable را repair کند؛
6. Source Truthها را تغییر ندهد؛
7. قبل از merge کل CI را اجرا کند؛
8. بدون post-fix owner attestation وارد FO-4 نشود؛
9. هیچ ادعای push/merge/test بدون SHA و run ID مطرح نکند.

---

## 12. تصمیم فعلی

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = TECHNICALLY_VALIDATED
FO-3 LOCAL UX ACCEPTANCE = BLOCKED BY RUNTIME DEFECT
FOCUSED FO-3 FIX = IN PROGRESS
FO-4 AND LATER = BLOCKED
```
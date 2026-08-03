# وضعیت حاکم پروژه — Clinic Management

> **Source of Truth مدیریتی مخزن.** پیش از هر توسعه، وضعیت واقعی GitHub، این فایل و `PROJECT_STATE.json` باید خوانده شوند. حافظهٔ گفتگو یا branch قدیمی به‌تنهایی معتبر نیست.

- آخرین ممیزی: `2026-08-03 14:25 +03:30`
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

این attestation فقط برای محیط فعلی است. پیش از دادهٔ واقعی، production-readiness، privacy، backup/restore، consent/role review و baseline بدون PHI اجباری است.

---

## 3. ماتریس جریان‌ها

| جریان | وضعیت | اختیار فعلی | ممنوعیت |
|---|---|---|---|
| محصول عملیاتی | `ACTIVE_PRODUCT_PRE_PRODUCTION` | رفتار واقعی main | تغییر بالینی بدون گیت |
| FOUX-V1 | `FO_0/1/2_VALIDATED / FO_3_TECHNICALLY_VALIDATED / LOCAL_UX_BLOCKED_BY_CONFIRMED_DEFECT` | فقط repair متمرکز PR #85 | FO-4، mutation، claim، SMS یا routing |
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

Plan version: `1.4.2`

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

---

## 5. Incident جاری — FO3_UI_500

### مشاهده

مالک هنگام مرور لوکال روی دادهٔ تست، generic HTTP 500 را پس از کلیک «نمای یکپارچه» گزارش کرد.

```text
Issue             = #84
Repair PR         = #85
Owner evidence    = screenshot
UX acceptance     = BLOCKED
FO-4              = BLOCKED
```

### علت قطعی

CI integration run `30808217800` با Flask/Jinja واقعی این traceback را ثبت کرد:

```text
TypeError: 'builtin_function_or_method' object is not iterable
{% for item in model.items %}
```

Jinja، `model.items` را به متد داخلی `dict.items` resolve کرده بود، نه mapping key `items`. همین collision علت مستقیم 500 بود.

اصلاح:

```jinja2
model['items']
timeline['items']
```

`timeline.items` نیز همان ریسک را داشت و پیشگیرانه اصلاح شد. guard static بازگشت dot notation را رد می‌کند.

### Hardening ثانویه

یک gap مستقل نیز رفع می‌شود:

- Projection cache قدیمی ممکن است required columns نداشته باشد؛
- `CREATE TABLE IF NOT EXISTS` آن را upgrade نمی‌کند؛
- فقط cache disposable در incompatibility recreate و خالی می‌شود؛
- rebuild همچنان صریح است؛
- Source Truth و Episodeها تغییر نمی‌کنند؛
- Read Model schema را preflight و known failures را به صفحهٔ کنترل‌شده تبدیل می‌کند.

این hardening علت قطعی screenshot نیست؛ علت قطعی Jinja collision است.

---

## 6. Exit Gate PR #85

PR فقط وقتی معتبر است که:

1. real Flask/Jinja list render سبز باشد؛
2. real Flask/Jinja Timeline render سبز باشد؛
3. `model.items` و `timeline.items` در templateها وجود نداشته باشند؛
4. cache ناقص safely recreate و خالی شود؛
5. migration rerun idempotent باشد؛
6. Source Truth و Episode digest تغییر نکند؛
7. schema drift شناخته‌شده صفحهٔ کنترل‌شده بدهد، نه 500؛
8. flag OFF و GET-only boundary حفظ شود؛
9. Specialist و Accounting CI کامل سبز باشد؛
10. PR merge شود؛
11. مالک UX را روی commit repair تکرار کند.

---

## 7. Feature Flagها

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

در repair فقط Read-only flag مصرف می‌شود؛ rebuild تستی با Shadow flag صریح است. Action flags ممنوع‌اند.

---

## 8. مرور لوکال پس از repair

پس از merge PR #85:

```powershell
git checkout main
git pull origin main
cd specialist_clinic
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

برنامه یک بار اجرا و بسته شود تا cache migration اعمال شود. سپس:

```powershell
$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\rebuild_followup_projection.py `
  --database specialist.db `
  --as-of "2026-08-03 12:00:00" `
  --apply

$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
.\.venv\Scripts\python.exe start.py
```

Attestation باید commit نهایی repair را ثبت کند و `critical_ux_defects=0` باشد.

---

## 9. Freeze فعلی

```text
FOUX PR #85 focused repair        = ALLOWED
FOUX FO-3 local UX review         = BLOCKED UNTIL FIX MERGE
FOUX FO-4 and later               = BLOCKED
New clinical rules                = PAUSED
Hypoglycemia Shadow expansion     = PAUSED
Disposition branch                = DO NOT MERGE
Focused bug/security fixes        = ALLOWED
```

---

## 10. قواعد ادامه

هر ایجنت باید:

1. GitHub، Issue #84 و PR #85 را بخواند؛
2. plan v1.4.2، JSON state و AGENTS را تطبیق دهد؛
3. فقط focused repair را تغییر دهد؛
4. علت قطعی را Jinja dict-method collision گزارش کند؛
5. schema hardening را علت قطعی screenshot معرفی نکند؛
6. فقط cache disposable را repair کند؛
7. Source Truthها را تغییر ندهد؛
8. full CI را پس از آخرین commit اجرا کند؛
9. بدون post-fix owner attestation وارد FO-4 نشود.

---

## 11. تصمیم فعلی

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = TECHNICALLY_VALIDATED
FO-3 LOCAL UX ACCEPTANCE = BLOCKED BY CONFIRMED JINJA RUNTIME DEFECT
FOCUSED FO-3 FIX = IN PROGRESS IN PR #85
FO-4 AND LATER = BLOCKED
```
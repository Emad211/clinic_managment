# Specialist Clinic — Agent Instructions

این فایل نزدیک‌ترین منبع دستور برای همهٔ تغییرات زیر `specialist_clinic/` است.

## ترتیب مطالعهٔ اجباری

1. وضعیت واقعی `main`، PRها و Issueها؛
2. `PROJECT_STATE.md` و `PROJECT_STATE.json`؛
3. `AGENTS.md` ریشه؛
4. همین فایل؛
5. سند canonical نزدیک به جریان.

برای Follow-up، Task، Worklist، SMS، Contact، Appointment یا automation:

```text
docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md
docs/FOLLOWUP_ORCHESTRATION_UX_V1_BASELINE.md
```

## طبقه‌بندی محیط

```text
specialist.db = TEST_ONLY / SYNTHETIC_OR_RESETTABLE
```

این طبقه‌بندی هیچ guardrail امنیتی یا بالینی را حذف نمی‌کند.

## وضعیت FOUX-V1

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 RUNTIME REPAIR = TECHNICALLY VALIDATED
FO-3 OPERATOR COPY REPAIR = TECHNICALLY VALIDATED
FO-3 POST-FIX LOCAL UX ACCEPTANCE = PENDING
CURRENT REVIEW ISSUE = #83
FO-4 and later = BLOCKED
```

سند canonical: نسخهٔ `1.4.4`.

### Evidence runtime repair

```text
Issue #84 / PR #85
Final head 8809252b2ca25fb55f200d783016d30ec10134d7
Merge 8f851c90da5a81f4b7ffce43eaa5bf6010d58fa2
Root-cause CI 30808217800
Final CI 30809363219
761 Specialist + 54 Accounting
```

### علت Incident

```text
JINJA_DICT_METHOD_COLLISION_ON_ITEMS_KEY
```

در Jinja، `model.items` به متد `dict.items` اشاره کرد، نه key دیکشنری. دسترسی حاکم:

```jinja2
model['items']
timeline['items']
```

تست واقعی Flask/Jinja و guard ثابت بازگشت این defect را رد می‌کنند.

Schema/cache hardening بخشی از repair است، اما علت screenshot نبود.

### Evidence operator copy repair

```text
Issue #87 / PR #88
Final head 39ebef3b70470f39292faaa7d986e2f1a90a0e80
Merge 020803868e1c2755f7669d52da92cb8050a46018
Final CI 30827033618
762 Specialist + 54 Accounting
```

این repair فقط کپی قابل‌مشاهده و regression test را تغییر داد:

- `Projection قدیمی` به متن عملیاتی فارسی تبدیل شد؛
- `سن Projection` به `آخرین بازسازی نما` تبدیل شد؛
- readiness copy فنی حذف شد؛
- machine codeها، audit فنی، route، query، schema، cache behavior و Source Truth ثابت ماندند.

## دامنهٔ مجاز فعلی

فقط:

- اجرای Issue #83 روی merge commit `020803868e1c2755f7669d52da92cb8050a46018`؛
- ثبت feedback و owner attestation؛
- در صورت کشف defect، focused FO-3 fix با Issue/PR/CI مستقل؛
- به‌روزرسانی governance پس از نتیجهٔ مرور.

## دامنهٔ ممنوع

- POST یا mutation endpoint جدید؛
- claim/assignment؛
- routing، SLA یا escalation mutation؛
- SMS send/approval automation؛
- appointment reaction یا outbox؛
- callback/retry/auto-close؛
- Evidence Assist یا clinical decision؛
- تغییر Rule یا Hypoglycemia Shadow؛
- write به `clinic_new.db`؛
- شروع FO-4.

## قرارداد FO-3 فعلی

1. list و detail فقط GET هستند.
2. Worklist قدیمی authority اقدام است.
3. role فقط proposal است.
4. mapping keyهای متعارض Jinja با bracket notation خوانده می‌شوند.
5. real render test الزامی است؛ mock کردن `render_template` کافی نیست.
6. فقط Projection cache disposable می‌تواند در schema drift recreate شود.
7. cache ناسازگار canonical و خالی می‌شود؛ rebuild فقط صریح است.
8. known SQLite/schema error باید controlled UI state بدهد، نه generic 500.
9. Source Truth و Episodeها تغییر نمی‌کنند.
10. flag OFF همچنان route=404 و navigation hidden است.
11. کپی اصلی اپراتوری نباید jargon فنی Projection/cache داشته باشد؛ audit جمع‌شونده استثنا است.

## Feature Flagها

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

همه default OFF. در review فقط Read-only flag و برای rebuild، Shadow flag صریح مصرف می‌شوند. Action flags ممنوع‌اند.

## مرور الزامی Issue #83

```powershell
git checkout main
git pull origin main
cd specialist_clinic
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe start.py
```

پس از اجرای یک‌باره و توقف:

```powershell
$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\rebuild_followup_projection.py `
  --database specialist.db `
  --as-of "2026-08-03 12:00:00" `
  --apply

$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
.\.venv\Scripts\python.exe start.py
```

Attestation باید commit `020803868e1c2755f7669d52da92cb8050a46018` را ثبت کند.

## مرزهای دائمی

- `clinic_new.db` read-only است.
- Source Truthها authoritative هستند.
- Episode/Projection حقیقت بالینی نیستند.
- Clinical Task completion نیازمند Evidence است.
- Appointment، Clinical Task را complete نمی‌کند.
- تصمیم دارویی، تشخیصی یا ارجاعی خودکار نیست.
- eventهای append-only UPDATE/DELETE نمی‌شوند.

## PR Contract

هر PR باید Issue، scope، schema/cache impact، feature flag، focused/full tests، rollback و proof عدم تغییر Clinical/Accounting/Source Truth را ثبت کند. FO-4 فقط پس از `FO3_UX_ACCEPTED=true`، `critical_ux_defects=0` و governance PR مستقل قابل بررسی است.

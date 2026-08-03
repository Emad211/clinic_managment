# Specialist Clinic — Agent Instructions

این فایل نزدیک‌ترین منبع دستور برای همهٔ تغییرات زیر `specialist_clinic/` است.

## ترتیب مطالعهٔ اجباری

پیش از هر تغییر:

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

حافظهٔ گفتگو، branch قدیمی و PR تاریخی بر منابع بالا مقدم نیستند.

## طبقه‌بندی محیط فعلی

```text
specialist.db = TEST_ONLY / SYNTHETIC_OR_RESETTABLE
source        = owner attestation, 2026-08-03
```

این طبقه‌بندی اجازهٔ حذف guardrail یا ورود shortcut runtime نمی‌دهد.

## وضعیت FOUX-V1

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = TECHNICALLY_VALIDATED
FO-3 LOCAL UX ACCEPTANCE = BLOCKED BY RUNTIME DEFECT
FOCUSED FIX ISSUE = #84
FO-4 and later = BLOCKED
```

سند canonical: نسخهٔ `1.4.1`.

Evidence پایهٔ FO-3:

```text
Issue #80 / PR #81
merge afed3545c0a90a1ed7ff7e0a892df89fffac00c2
CI 30775348057
754 Specialist + 54 Accounting
```

Incident:

```text
Code          = FO3_UI_500
Issue         = #84
Evidence      = owner screenshot of generic HTTP 500
Exact trace   = unavailable at registration
Allowed work  = focused FO-3 runtime repair only
```

## دامنهٔ مجاز فعلی

فقط این موارد مجازند:

- بررسی و رفع schema drift در cache disposable `followup_work_item_projection`؛
- required-column preflight برای Read Model؛
- controlled Persian unavailable state برای خطاهای SQLite/schema شناخته‌شده؛
- تست legacy/incomplete cache؛
- اثبات ثابت‌ماندن Source Truth و Episode digest؛
- focused/full CI؛
- مستندسازی repair و تکرار مرور UX.

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

## قرارداد Repair

1. فقط Projection cache disposable می‌تواند در schema drift حذف و recreate شود.
2. Episode/Link/Event، Task، SMS، Appointment، Contact و Clinical tables هرگز drop/rewrite نمی‌شوند.
3. cache ناسازگار به schema canonical بازمی‌گردد و خالی می‌ماند؛ rebuild فقط صریح است.
4. known SQLite/schema error باید controlled UI state بدهد، نه generic 500.
5. raw exception، نام بیمار، شماره، متن پیام، note یا clinical value در UI/log عمومی نمایش داده نمی‌شود.
6. unknown programming exception با `except Exception` پنهان نمی‌شود.
7. Worklist قدیمی authority اقدام باقی می‌ماند.
8. flag OFF همچنان route=404 و navigation hidden است.

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

همه default OFF. در repair فقط `FOLLOWUP_UNIFIED_WORKLIST_READONLY` مصرف می‌شود. Rebuild تستی می‌تواند با `FOLLOWUP_PROJECTION_SHADOW=1` صریح اجرا شود. Action flags ممنوع‌اند.

## تست‌های اجباری Issue #84

- incompatible cache recreated empty؛
- migration rerun idempotent؛
- required columns کامل؛
- Source Truth و Episode digest ثابت؛
- incompatible projection schema → controlled page، نه 500؛
- incomplete patient/link read schema → controlled state؛
- canonical list/detail همچنان render؛
- flag OFF 404/hidden؛
- POST 405؛
- GET هیچ mutation ندارد؛
- full Specialist و Accounting CI.

## مرزهای دائمی ایمنی

- `clinic_new.db` read-only است.
- Source Truthها authoritative هستند.
- Episode/Projection حقیقت بالینی نیستند.
- Clinical Task completion نیازمند Evidence است.
- Appointment، Clinical Task را complete نمی‌کند.
- تصمیم دارویی، تشخیصی یا ارجاعی خودکار نیست.
- eventهای append-only UPDATE/DELETE نمی‌شوند.

## PR Contract

هر PR باید Issue #84، scope، cache/schema impact، feature flag، focused/full tests، rollback، UX effect و proof عدم تغییر Source Truth/Clinical/Accounting را ثبت کند. پس از merge repair نیز FO-4 تا پذیرش UX جدید مالک مسدود است.

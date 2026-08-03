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

Reset/reseed و migration rehearsal روی دادهٔ فعلی مجاز است، اما guardrailهای امنیتی و بالینی حذف نمی‌شوند. پیش از دادهٔ واقعی، production-readiness و privacy review الزامی است. هیچ shortcut مبتنی بر `TEST_ONLY` وارد runtime نشود.

## وضعیت FOUX-V1

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = TECHNICALLY_VALIDATED
FO-3 LOCAL UX ACCEPTANCE = PENDING
FO-4 and later = BLOCKED pending owner UX attestation
```

Evidence FO-3:

```text
Issue #80
PR #81
final head 14e8bf56782ead4ccef46db05eb8c4b6b034d263
merge afed3545c0a90a1ed7ff7e0a892df89fffac00c2
CI 30775348057
754 Specialist + 54 Accounting
```

### زیرساخت موجود روی main

```text
followup_episodes
followup_episode_links
followup_episode_events
followup_work_item_projection
GET /followups/unified/
GET /followups/unified/<episode_id>
```

Episode/Link immutable، Episode Event append-only و Projection rebuildable cache است. Backfill و projection rebuild خودکار startup ندارند. UI جدید feature-gated و فقط خواندنی است.

## دامنهٔ مجاز فعلی: FO-3 Local UX Acceptance

کار مجاز:

- اجرای محلی با دادهٔ تست؛
- روشن‌کردن فقط `FOLLOWUP_PROJECTION_SHADOW` برای rebuild صریح؛
- روشن‌کردن فقط `FOLLOWUP_UNIFIED_WORKLIST_READONLY` برای مشاهده؛
- مرور pagination/search/filter؛
- مرور action/wait/block copy؛
- مرور role proposal، action due، target و projection age؛
- مرور Timeline، stale/error states و deep-linkها؛
- مرور RTL/Jalali/fa number/keyboard/mobile؛
- patch محدود نقص FO-3؛
- ثبت attestation مالک.

کار ممنوع:

- POST یا mutation endpoint جدید؛
- claim/assignment؛
- role proposal به‌عنوان assignment واقعی؛
- routing، SLA یا escalation mutation؛
- SMS send یا approval change؛
- appointment reaction یا outbox؛
- callback/retry/auto-close؛
- Evidence Assist یا clinical decision؛
- حذف یا تغییر authority Worklist قدیمی؛
- Rule یا Hypoglycemia Shadow change؛
- write به `clinic_new.db`؛
- آغاز FO-4 بدون attestation جدید سند.

## قرارداد FO-3 Read-only UI

- Projection source truth نیست.
- request نباید projection rebuild کند.
- list/detail فقط GET هستند؛ POST باید 405 باشد.
- flag OFF باید route را 404 و navigation را مخفی کند.
- projection missing/stale باید واضح نمایش داده شود.
- list query صفحه‌بندی‌شده و بدون N+1 است.
- source linkها batch خوانده می‌شوند.
- patient identity فقط به حداقل لازم محدود می‌شود.
- raw note، message body، clinical value و payload JSON در Timeline نمایش داده نمی‌شوند.
- Timeline chronological و provenance-aware است.
- deep-linkها permission را دور نمی‌زنند.
- CTA فقط به مسیر حاکم می‌رود؛ action داخل UI جدید انجام نمی‌شود.
- role proposal به معنی claim یا assignment نیست.

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

همه default OFF. در مرور فعلی فقط دو flag اولِ مرتبط با rebuild صریح و نمایش read-only ممکن است موقتاً ON شوند. `FOLLOWUP_UNIFIED_WORKLIST_ACTIONS` و تمام automation flags ممنوع‌اند.

## Local UX Review

```powershell
cd specialist_clinic
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe seed_demo_data.py

$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\rebuild_followup_projection.py `
  --database specialist.db `
  --as-of "2026-08-03 12:00:00" `
  --apply

$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
.\.venv\Scripts\python.exe start.py
```

attestation لازم:

```text
FO3_UX_ACCEPTED = true|false
reviewer = Emad211
reviewed_commit = afed3545c0a90a1ed7ff7e0a892df89fffac00c2
reviewed_on_test_data = true
critical_ux_defects = 0
notes = ...
```

## مرزهای دائمی ایمنی

- `clinic_new.db` برای Specialist Clinic read-only است.
- Source Truthهای فعلی authoritative باقی می‌مانند.
- Episode/Projection حقیقت بالینی نیستند.
- Clinical Task completion نیازمند Evidence است.
- Appointment، Clinical Task را complete نمی‌کند.
- هیچ تصمیم دارویی، تشخیصی یا ارجاعی خودکار نیست.
- SMS guardrailها حفظ می‌شوند.
- Rule و Hypoglycemia Shadow خارج از FOUX هستند.
- eventهای append-only UPDATE/DELETE نمی‌شوند.

## تست‌های اجباری patchهای FO-3

- flag OFF route/navigation hidden؛
- flag ON authorized GET works؛
- unauthorized access denied؛
- no POST/mutation route؛
- pagination/search/filter؛
- bounded query count و no N+1؛
- projection empty/stale/conflict states؛
- Timeline deterministic؛
- permission-safe deep-links؛
- RTL/Jalali/fa number/accessibility؛
- no source/projection mutation from GET؛
- legacy Worklist unchanged؛
- full Specialist and Accounting CI.

## PR Contract

هر PR باید tranche، Requirement ID، scope، schema/data impact، feature flag، focused/full tests، rollback، UX effect و proof مرزهای بالینی/حسابداری را ثبت کند. تا attestation مالک، هیچ PR مربوط به FO-4 مجاز نیست.

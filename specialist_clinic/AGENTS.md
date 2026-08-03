# Specialist Clinic — Agent Instructions

این فایل نزدیک‌ترین دستور حاکم برای تغییرات زیر `specialist_clinic/` است.

## ترتیب اعتماد

1. وضعیت واقعی `main`، PRها، Issueها و CI؛
2. `PROJECT_STATE.json` و `PROJECT_STATE.md`؛
3. `AGENTS.md` ریشه و همین فایل؛
4. سند canonical و رودمپ مرتبط؛
5. حافظهٔ گفتگو.

برای Follow-up، Task، Worklist، Contact، SMS و Appointment:

```text
docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md
docs/FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md
```

## محیط

```text
specialist.db = TEST_ONLY / SYNTHETIC_OR_RESETTABLE
real patient PHI = NOT EXPECTED
```

این طبقه‌بندی هیچ guardrail امنیتی یا بالینی را حذف نمی‌کند.

## وضعیت FOUX-V1

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = VALIDATED WITH OWNER ACCEPTANCE
FO-4 = VALIDATED WITH OWNER ACCEPTANCE
FO-5 = AUTHORIZED / IMPLEMENTATION PENDING
FO-6 and later = BLOCKED
CURRENT ISSUE = #103
ROADMAP PROGRESS = 5.0 / 11 = 45.5%
REMAINING = 54.5%
```

Canonical plan: `v1.6.0`.
Complete roadmap: `docs/FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md` v1.1.0.

## FO-4 Evidence و پذیرش مالک

```text
Ownership Issue #94 / PR #95
Merge 27ccb992f2cb43c78bfe98549c3f0414b88fd1d8
Final CI 30844075841
773 Specialist + 54 Accounting

Seed repair Issue #97 / PR #98
Merge 24119671b8b93fdb20db3064a59d416e02d81ef6
CI 30851594179
781 Specialist + 54 Accounting

SLA repair Issue #99 / PR #100
Merge cd243424ecbae98892e0dfde1780bb846554942f
CI 30852909213
784 Specialist + 54 Accounting
```

```text
FO4_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = cd243424ecbae98892e0dfde1780bb846554942f
reviewed_on_test_data = true
critical_ux_defects = 0
notes = بررسی شد و مشکل بحرانی مشاهده نشد
```

Recovery دیتابیس seedشده:

```powershell
$env:FOLLOWUP_PROJECTION_SHADOW = "1"
.\.venv\Scripts\python.exe scripts\prepare_seeded_followup_view.py `
  --database specialist.db
```

## مجوز فعلی FO-5

Issue حاکم: `#103`.

فقط موارد زیر مجازند:

- outcomeهای ساختاریافتهٔ تماس؛
- Contact Attempt append-only و اتصال آن به Episode؛
- callback scheduling با زمان آینده؛
- bounded retry برای `NO_ANSWER` و `BUSY`؛
- unreachable escalation دقیقاً یک‌بار پس از threshold؛
- phone-invalid workflow و route به پذیرش؛
- operational escalation به پزشک یا مدیر بدون تصمیم بالینی؛
- فرم کم‌کلیک و summary تماس در Unified Worklist؛
- Timeline بدون نمایش note آزاد؛
- idempotency، stale-form، permission و terminal fail-closed؛
- Feature Flag `FOLLOWUP_STRUCTURED_CONTACT` با پیش‌فرض OFF؛
- Issue و PR مستقل runtime، full CI و owner UX review.

## قرارداد FO-5

Structured outcomeهای مجاز:

```text
REACHED
NO_ANSWER
BUSY
CALLBACK_REQUESTED
PHONE_INVALID
APPOINTMENT_BOOKED
DECLINED
ESCALATED_TO_PHYSICIAN
OTHER
```

قواعد اصلی:

1. `CALLBACK_REQUESTED` بدون زمان آینده رد می‌شود.
2. `NO_ANSWER/BUSY` قبل از threshold تماس مجدد می‌سازند.
3. threshold عدم دسترسی فقط یک escalation ایجاد می‌کند.
4. `PHONE_INVALID` retry را متوقف و مسیر اصلاح اطلاعات تماس را به پذیرش می‌برد.
5. `APPOINTMENT_BOOKED` فقط گزارش عملیاتی است؛ نوبت نمی‌سازد و Clinical Task را کامل نمی‌کند.
6. `ESCALATED_TO_PHYSICIAN` فقط صف بررسی پزشک را ثبت می‌کند، نه تصمیم بالینی.
7. note آزاد محرک اتوماسیون نیست و در Timeline اصلی نمایش داده نمی‌شود.
8. exact replay رویداد تکراری نمی‌سازد.
9. Source Truthهای پیشین، SMS، Appointment، Rule و Accounting تغییر نمی‌کنند.

## Feature Flags

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

برای FO-5، سه سطح قبلی و Flag تماس باید صریح روشن شوند. با Flag تماس خاموش، کنترل تماس مخفی و POST مربوط 404 است.

## دامنهٔ ممنوع

- Governed SMS automation یا تغییر approval policy؛
- ارسال خودکار SMS؛
- ساخت، لغو یا تغییر Appointment؛
- Operational Outbox یا Dead-letter؛
- Clinical Evidence Assist؛
- Clinical Task completion یا clinical decision؛
- Rule یا Hypoglycemia Shadow؛
- Write به `clinic_new.db`؛
- شروع FO-6 تا FO-10.

## مرزهای دائمی

- Source Truthها authoritative هستند.
- Episode حقیقت بالینی نیست؛ Projection cache است.
- eventهای append-only UPDATE/DELETE نمی‌شوند.
- Clinical completion نیازمند Evidence و transition معتبر است.
- Appointment به‌تنهایی Clinical Task را کامل نمی‌کند.
- mutationها باید idempotent و audit‌شده باشند.
- stale form و terminal mutation fail closed هستند.

## PR Contract

هر PR باید Issue، scope، feature flag، permission، idempotency، stale/terminal guard، schema impact، rollback، focused/full tests و proof عدم تغییر SMS/Appointment/Clinical Rule/Accounting را ثبت کند.

FO-5 فقط تحت Issue #103 مجاز است؛ بدون Technical Validation، Local Owner UX Acceptance و governance مستقل وارد FO-6 نشوید.

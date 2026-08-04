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
FO-5 = VALIDATED WITH OWNER ACCEPTANCE
FO-6 = AUTHORIZED / IMPLEMENTATION PENDING
FO-7 and later = BLOCKED
CURRENT ISSUE = #109
REVIEWED FO-5 MERGE = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
ROADMAP PROGRESS = 6.0 / 11 = 54.5%
TECHNICAL IMPLEMENTATION = 6 / 11 = 54.5%
REMAINING = 45.5%
```

Canonical plan: `v1.8.0`.
Complete roadmap: `docs/FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md` v1.3.0.

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

## FO-5 Evidence و پذیرش مالک

```text
Implementation Issue #105 / PR #106
Runtime merge 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
CI 30865955479 — 801 Specialist + 54 Accounting
Owner UX Issue #107 — completed
```

```text
FO5_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
reviewed_on_test_data = true
critical_ux_defects = 0
notes = بررسی شد و مشکل بحرانی مشاهده نشد
```

## مجوز فعلی FO-6

Issue حاکم: `#109`؛ Governance PR: `#110`.

فقط موارد زیر مجازند:

- policy levels: `CLINICIAN_ONLY / MANUAL_APPROVAL / AUTO_GUARDED`؛
- AUTO_GUARDED فقط برای `appointment_reminder` و `refill_due`؛
- purpose فقط `CARE`؛
- policy/template/candidate/decision immutable و append-only؛
- TTL پیش‌فرض ۲۴ ساعت، bounded در ۱ تا ۷۲ ساعت؛
- pre-send revalidation کامل؛
- executor صریح، bounded و بدون GET/startup send؛
- Flag `FOLLOWUP_SMS_AUTO_GUARDED` با پیش‌فرض OFF؛
- Issue و PR مستقل runtime، full CI و owner UX review.

هر check نامعلوم یا failed باید fail-closed باشد. `CLINICIAN_ONLY` و `MANUAL_APPROVAL` هرگز خودکار ارسال نمی‌شوند.

## Pre-send checks اجباری

- policy و allowlist؛
- CARE consent head؛
- phone canonical freshness؛
- source event/period هنوز due؛
- template version/hash و body hash؛
- candidate expiry؛
- quiet hours، daily cap و cooldown؛
- dispatch/idempotency absence؛
- provider readiness و affinity.

## Feature Flags

همه default OFF باقی می‌مانند. FO-6 فقط با `FOLLOWUP_SMS_AUTO_GUARDED=1` وارد executor صریح می‌شود؛ manual approvals و گزارش‌های فعلی با Flag خاموش باقی می‌مانند.

## دامنهٔ ممنوع

- campaign یا MARKETING auto-send؛
- free-text auto-send؛
- auto-send برای `CLINICIAN_ONLY` یا `MANUAL_APPROVAL`؛
- `lapsed`، invite و invoice outreach در allowlist اولیه؛
- Appointment mutation؛
- clinical inference/decision/completion؛
- SMS delivery → Episode transition؛
- Outbox/dead-letter/cross-channel state machine؛
- scheduler health یا retry worker جدید؛
- Rule/Hypoglycemia Shadow؛
- Write به `clinic_new.db`؛
- شروع FO-7 تا FO-10.

## مرزهای دائمی

- Source Truthها authoritative هستند.
- SMS consent و delivery eventها append-only هستند.
- `sms_messages` ledger سازگاری و `sms_message_governance` snapshot immutable باقی می‌مانند.
- هیچ auto-send بدون decision تازه و تمام revalidationها مجاز نیست.
- Clinical completion نیازمند Evidence و transition معتبر است.
- Appointment به‌تنهایی Clinical Task را کامل نمی‌کند.

## PR Contract

PR اجرای FO-6 باید Issue #109، schema additive، policy/allowlist، feature flag، permission، idempotency، concurrency، expiry/supersession، rollback، focused/full tests و proof عدم تغییر campaign/MARKETING/Appointment/Clinical/Accounting را ثبت کند.

بدون Technical Validation، Local Owner UX Acceptance و governance مستقل وارد FO-7 نشوید.

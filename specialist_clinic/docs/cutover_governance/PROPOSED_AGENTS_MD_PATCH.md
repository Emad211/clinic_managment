# وصلهٔ پیشنهادی specialist_clinic/AGENTS.md — خط Cutover در بلوک وضعیت FOUX-V1

> **هدف:** اعمال دستی توسط مالک پس از امضای `GOVERNANCE_NOTE_CUTOVER_FA.md`.
>
> **فایل هدف:** `specialist_clinic/AGENTS.md` — فقط بخش «وضعیت FOUX-V1» و ناحیهٔ زیر «FO-5 Evidence».
>
> **قرارداد محدوده:** بخش‌های «مجوز فعلی FO-6»، «Pre-send checks اجباری»، «Feature Flags»، «دامنهٔ ممنوع»، «مرزهای دائمی» و «PR Contract» **دست‌نخورده** می‌مانند. این وصله هیچ قید مجوز FO-6 را تغییر نمی‌دهد.

---

## Hunk 1 — بلوک ```text``` داخل «## وضعیت FOUX-V1» (اجباری)

خط cutover دقیقاً زیر خط `FO-5 = VALIDATED WITH OWNER ACCEPTANCE` اضافه می‌شود. شمارش tranche معادل عمداً روی ۶/۱۱ می‌ماند — cutover یک تغییر سطحِ خواندنِ مالک‌تأیید روی سطح FO-3 است، نه tranche جدید؛ افزایش ۶→۷ فقط پس از merge و پذیرش FO-6 رخ می‌دهد (سازگار با `PROPOSED_ROADMAP_PROGRESS_NOTE.md`).

**BEFORE:**

`````text
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
`````

**AFTER:**

`````text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = VALIDATED WITH OWNER ACCEPTANCE
UNIFIED READ CUTOVER = APPLIED (owner-instructed 2026-08-24) — unified work center reads always-on; legacy followups/worklist.html removed with 302 shim; rollback = revert <CUTOVER_COMMIT_SHA> only
FO-4 = VALIDATED WITH OWNER ACCEPTANCE
FO-5 = VALIDATED WITH OWNER ACCEPTANCE
FO-6 = AUTHORIZED / IMPLEMENTATION PENDING
FO-7 and later = BLOCKED
CURRENT ISSUE = #109
REVIEWED FO-5 MERGE = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
ROADMAP PROGRESS = 6.0 / 11 = 54.5%
TECHNICAL IMPLEMENTATION = 6 / 11 = 54.5%
REMAINING = 45.5%
`````

---

## Hunk 2 — یادداشت توضیحی بعد از بخش «## FO-5 Evidence و پذیرش مالک» (اختیاری)

درج بین انتهای بلوک `FO5_UX_ACCEPTED` و عنوان «## مجوز فعلی FO-6»:

**BEFORE (انتهای بخش FO-5 Evidence):**

`````markdown
```text
FO5_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
reviewed_on_test_data = true
critical_ux_defects = 0
notes = بررسی شد و مشکل بحرانی مشاهده نشد
```

## مجوز فعلی FO-6
`````

**AFTER:**

`````markdown
```text
FO5_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
reviewed_on_test_data = true
critical_ux_defects = 0
notes = بررسی شد و مشکل بحرانی مشاهده نشد
```

### یادداشت Cutover خواندن یکپارچه (مالک‌تأیید 2026-08-24)

مسیرهای GET فهرست/جزئیات Unified Work Center بدون gate شدن با `FOLLOWUP_UNIFIED_WORKLIST_READONLY` سرو می‌شوند و صفحهٔ legacy `followups/worklist.html` با shim ریدایرکت 302 حذف شده است. این فقط سطح خواندنِ پذیرفته‌شدهٔ FO-3 را همیشه‌فعال می‌کند؛ همهٔ Flagهای اقدامی OFF می‌مانند، هیچ مجوز FO-6 تغییر نمی‌کند و rollback فقط با revert کامیت cutover (`<CUTOVER_COMMIT_SHA>`) ممکن است — متغیر محیطی به‌تنهایی دیگر رفتار legacy را برنمی‌گرداند. جزئیات: `docs/cutover_governance/GOVERNANCE_NOTE_CUTOVER_FA.md`.

## مجوز فعلی FO-6
`````

---

## خارج از محدودهٔ این وصله

- عبارت «همه default OFF باقی می‌مانند» در بخش «Feature Flags» همین AGENTS.md عمداً دست نخورده باقی می‌ماند تا قیدهای FO-6 لمس نشوند؛ اگر مالک بخواهد آنجا هم استثنا ثبت شود، باید در تصمیم حاکمیتی جداگانه بیاید.
- هیچ خطی از «مجوز فعلی FO-6»، «Pre-send checks»، «دامنهٔ ممنوع»، «مرزهای دائمی» یا «PR Contract» تغییر نمی‌کند.

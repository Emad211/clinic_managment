# یادداشت پیشرفت پیشنهادی برای ROADMAP v1.3.x — Cutover خواندن یکپارچه

> **هدف:** افزودن یک پاراگراف به `docs/FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md` (پیشنهاد: انتهای §2 «Progress model»، بعد از بلوک totals). اعمال دستی توسط مالک پس از امضای `GOVERNANCE_NOTE_CUTOVER_FA.md` و merge کامیت cutover (`<CUTOVER_COMMIT_SHA>`).

---

## پاراگراف پیشنهادی

> **Cutover annotation (owner-instructed 2026-08-24):** با اعمال cutover خواندن یکپارچه، سطحِ خواندنِ پذیرفته‌شدهٔ FO-3 همیشه‌فعال شد و صفحهٔ legacy با shim 302 حذف گردید؛ این تغییر یک تصمیم حاکمیتی محدود روی سطحِ ازقبل‌تأییدشده است و **به‌خودی‌خود tranche جدیدی را کامل نمی‌کند** — شمارش معادل در لحظهٔ ثبت این یادداشت همان **6.0 / 11 = 54.5%** می‌ماند. حرکت بعدی مدل پیشرفت از **6/11 به 7/11 (63.6%)** تنها زمانی رخ می‌دهد که FO-6 Governed SMS Automation & Freshness تحت Issue #109 با full CI، technical validation و local owner UX acceptance merge شود؛ تا آن زمان FO-6 = `AUTHORIZED / IMPLEMENTATION PENDING` با اعتبار 0.0 باقی می‌ماند و این درصد همچنان فقط ترانش‌های FOUX-V1 را می‌سنجد، نه production-readiness کل مطب.

---

## نکات سازگاری

- این یادداشت ادعا نمی‌کند FO-6 انجام شده یا پیشرفت فعلی بیش از ۶/۱۱ است.
- اگر مالک بخواهد cutover را به‌عنوان credit مستقل بشمارد (+1)، آن تصمیم باید در سند حاکمیتی جداگانه ثبت شود؛ این بسته عمداً چنین ادعایی نمی‌کند تا با مدل `TRANCHE_EQUIVALENT` در `PROJECT_STATE.json` تناقض پیش نیاید.
- پس از merge FO-6، همین پاراگراف باید با یک خط «FO-6 = 1.0 → Total = 7.0 / 11 = 63.6%» جایگزین/به‌روزرسانی شود.

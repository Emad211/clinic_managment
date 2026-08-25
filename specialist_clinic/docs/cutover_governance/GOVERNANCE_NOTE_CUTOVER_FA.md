# یادداشت حاکمیتی Cutover — خواندن همیشه‌فعال مرکز کار یکپارچه

> **سند:** `docs/cutover_governance/GOVERNANCE_NOTE_CUTOVER_FA.md`
>
> **تاریخ دستور مالک:** `2026-08-24`
>
> **وضعیت سند:** APPLY-READY — پیش از اعمال، امضای مالک در انتهای سند لازم است.
>
> **محدودهٔ تغییر runtime (توسط ایجنت موازی اجرا می‌شود):** مسیرهای GET فهرست/جزئیات Unified Work Center بدون gate شدن با `FOLLOWUP_UNIFIED_WORKLIST_READONLY`؛ حذف صفحهٔ legacy `followups/worklist.html` با shim ریدایرکت 302.
>
> **کامیت cutover:** `<CUTOVER_COMMIT_SHA>` — **PR مرجع:** `<CUTOVER_PR_NUMBER>`

---

## ۱. چه چیزی رفتاری تغییر کرد

- **خواندن مرکز کار یکپارچه همیشه فعال شد.** صفحات GET فهرست و جزئیات Unified Work Center دیگر به متغیر محیطی `FOLLOWUP_UNIFIED_WORKLIST_READONLY` وابسته نیستند؛ این سطحِ خواندنِ تأییدشده در FO-3 اکنون مسیر پیش‌فرض و بی‌قید است.
- **صفحهٔ legacy حذف شد.** قالب `followups/worklist.html` و مسیر آن برداشته شده و هر درخواست به آدرس قدیمی با **ریدایرکت 302** به نمای یکپارچه هدایت می‌شود؛ بوکمارک‌ها و لینک‌های قدیمی کار می‌کنند.
- **هیچ Flag اقدامی تغییر نکرد.** `FOLLOWUP_UNIFIED_WORKLIST_ACTIONS`، `FOLLOWUP_AUTO_ROUTING`، `FOLLOWUP_STRUCTURED_CONTACT` و `FOLLOWUP_SMS_AUTO_GUARDED` دست‌نخورده و همچنان **default OFF** هستند؛ کنترل‌های claim/assign/routing/contact مخفی و مسیرهای mutation آن‌ها 404 باقی می‌مانند.
- **هیچ داده یا Source Truth نوشته نشد.** این تغییر فقط سطح خواندن UI است؛ Episode/Projection همچنان cache غیربالینی است و Source Truthها authoritative می‌مانند.

## ۲. اصلاح موضع «همهٔ Flagها default OFF» — دامنهٔ دقیق

این cutover موضع مستند «همهٔ Feature Flagها default OFF» را **فقط برای یک سطحِ خواندنِ واحد** تغییر می‌دهد: همان سطح Read-only Unified Worklist که در **FO-3** پیاده‌سازی، تست و با پذیرش مالک (`FO3_UX_ACCEPTED = true`, reviewer = Emad211, reviewed_commit = `020803868e1c2755f7669d52da92cb8050a46018`) تأیید شده بود.

این استثنا **با دستور شفاهی مالک در تاریخ 2026-08-24** ثبت می‌شود و:

- هیچ Flag اقدامی (Actions/Auto-Routing/Structured-Contact/SMS) را روشن نمی‌کند؛
- هیچ ارسال خودکار پیامکی، mutation نوبت، تصمیم یا تکمیل بالینی ایجاد نمی‌کند؛
- وارد محدودهٔ مجوز FO-6 (Issue #109) نمی‌شود و آن را جلو نمی‌اندازد؛
- فقط پس از امضای مالک در انتهای همین سند معتبر است.

## ۳. سناریوی Rollback

```text
FOLLOWUP_UNIFIED_WORKLIST_READONLY=0  →  دیگر خواندن unified را خاموش نمی‌کند
```

- **متغیر محیطی به‌تنهایی دیگر rollback نیست.** چون gate از مسیرهای GET فهرست/جزئیات حذف شده، خاموش‌کردن Flag رفتار legacy را برنمی‌گرداند.
- **بازگشت کامل = revert کامیت cutover** (`git revert <CUTOVER_COMMIT_SHA>`): gate شرطی روی GET index/detail و قالب legacy `followups/worklist.html` بازگردانده می‌شوند و رفتار دقیقاً به وضعیت پیش از cutover برمی‌گردد.
- تا زمان revert، هیچ کلید خاموش‌کنندهٔ runtime برای این سطح خواندن وجود ندارد — این عمداً پذیرفته شده است.

## ۴. ماتریس اثر بر نقش‌های کاربری

| نقش / ذی‌نفع | قبل از cutover | بعد از cutover | تغییر عملی |
|---|---|---|---|
| مدیر (`manager`) | unified فقط با `FOLLOWUP_UNIFIED_WORKLIST_READONLY=1` | unified همیشه در دسترس؛ آدرس legacy → 302 به unified | مشاهدهٔ همیشگی؛ هیچ اقدام جدیدی فعال نشده |
| کارمند (`staff`) | مشروط به Flag | unified همیشه در دسترس؛ کنترل‌های ownership/contact مخفی (Flagها OFF)، mutation routeها 404 | فقط خواندن؛ بدون تغییر دسترسی اقدام |
| کاربر واردنشده | login_required | login_required بدون تغییر | هیچ |
| کاربران با بوکمارک قدیمی `/followups/worklist` | صفحهٔ legacy با 200 | ریدایرکت 302 به نمای یکپارچه | تجربهٔ یکسان با مسیر جدید |
| اسکریپت/ابزار خارجی که HTML صفحهٔ legacy را مستقیم می‌خواند | 200 + HTML قدیمی | 302 (دنبال‌کردن redirect معمولاً شفاف است) | ابزارهایی که redirect را دنبال نمی‌کنند باید به‌روزرسانی شوند |

## ۵. یادداشت ارتباطی برای کاربران مطب (پیش‌نویس اطلاع‌رسانی)

> صفحهٔ «پیگیری» قبلی با «مرکز کار یکپارچه» جایگزین شده است. اگر آدرس قدیمی را باز کنید، به‌صورت خودکار به صفحهٔ جدید هدایت می‌شوید و نیازی به تغییر بوکمارک نیست. ظاهر و امکانات اقدام (واگذاری، تماس ساخت‌یافته و …) تغییری نکرده و مانند قبل طبق تنظیمات مدیر فعال می‌شود.

## ۶. بلوک تأیید مالک (Sign-off)

```text
CUTOVER_GOVERNANCE_SIGNOFF
surface            = unified work center read paths (FO-3 lineage)
change             = reads unconditional; legacy followups/worklist.html removed with 302 shim
action_flags       = UNCHANGED / ALL DEFAULT OFF
rollback           = git revert <CUTOVER_COMMIT_SHA> only; env var no longer disables reads
owner_name         = ______________________
owner_decision     = APPROVED / REJECTED
decision_date      = ____-__-__  (Tehran local)
reviewed_on        = TEST_DATA (specialist.db)
notes              = ______________________________________________
```

بدون تکمیل این بلوک توسط مالک، وصله‌های پیشنهادیِ همراه (`PROPOSED_PROJECT_STATE_PATCH.md`، `PROPOSED_AGENTS_MD_PATCH.md`، `PROPOSED_ROADMAP_PROGRESS_NOTE.md`) نباید به اسناد حاکم اعمال شوند.

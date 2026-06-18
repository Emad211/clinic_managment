# نقشهٔ بازطراحیِ پروندهٔ بیمار و «حلقهٔ مراقبت»

> سندِ مرجعِ این فاز (تأییدِ مالک، خرداد ۱۴۰۵). بر پایهٔ ۲۰ پرسشِ طراحی + استراتژیِ قیفِ بازگشت/پیشنهاد + ترکِ پل نسخه‌نویسی.
> هم‌خانواده: [`accounting_sync.md`](accounting_sync.md) · [`kavenegar_reference.md`](kavenegar_reference.md) · [`engagement_engine_plan.md`](engagement_engine_plan.md)
> روال: **اول نقشهٔ دقیق، سپس اجرای فاز‌به‌فاز با تستِ هر فاز روی بیماران دمو (`TEST0001..0010`).**

---

## ۰) مفهومِ کلان — «حلقهٔ مراقبت بسته شود»

**۱) پروندهٔ بیماری‌محور:** هر بیماریِ مزمنِ ثبت‌شده بخش‌ها/داده‌های مخصوصِ خود را **اضافه** می‌کند = پایهٔ مشترک (هویت/حساسیت/جراحی/سبک‌زندگی) همیشه + ماژول‌های بیماری رویش. ماژول = **داده، نه کد**. دسته‌بندیِ فعلی **به‌هم‌ریخته** است و باید مرتب شود.

**۲) قیفِ پیگیری → ویزیت:** `تعریف(بیماری) → اندازه‌گیری(پرونده) → تشخیص(موتور) → اقدام(قیف) → ویزیت → تکرار`. مکملِ «اتاقِ کنترل». دو مسیرِ بستن:
- **حضوری:** مشاوره/معاینه/تیتراسیون → نوبتِ رزروشده.
- **از‌راه‌دور:** تجدیدِ نسخه/آزمایشِ دوره‌ای با تأییدِ پزشک →
  - **(الف) نسخهٔ آزادِ غیربیمه‌ای (baseline):** اپ خودش PDF/چاپی با مهر/امضا می‌سازد، بدونِ مجوزِ سامانه (نقدی، در UI شفاف).
  - **(ب) نسخهٔ بیمه‌ای via «پل نسخه‌نویسی»:** اکستنشن روی **لاگینِ خودِ پزشک** در پنلِ بیمه → مجوزِ شرکتی لازم ندارد، بیمه‌ای می‌شود. (ترکِ موازی، پایین.)

درآمد فقط از پلِ read-only حسابداری خوانده می‌شود (نه فاکتورسازی اینجا).

---

## ۱) اصول و گاردریل‌ها
لایه‌بندی (SQL فقط در repo) · migration افزایشی idempotent · Jalali/iran_now · **پزشک دروازه‌بانِ بالینی** · threshold-sync (`clinical_indicators`) · ری‌استارت برای تغییرِ پایتون · کاوه‌نگار تا KYC شبیه‌سازی (بدونِ ارسالِ واقعی در تست) · مرزِ پول = حسابداری · PyInstaller datas به‌روز شود اگر فایلِ بسته‌بندی‌شده افزوده شد.

---

## ۲) مدلِ داده (پایهٔ همه؛ همه idempotent در `schema.sql` + `_run_migrations`)

| شیء | ستون‌های کلیدی | نقش |
|---|---|---|
| `lab_test_catalog` | `test_key PK, name_fa, unit, ref_low, ref_high, category, display_order, is_active` | کاتالوگِ آزمایش؛ دراپ‌داونِ نام/واحد/حد. |
| `condition_lab_tests` | `condition_code, lab_test_key, display_order` | آزمایش‌های پرتکرارِ **per-disease**. |
| `drug_catalog` | `id PK, generic_fa, drug_class_key, standard_doses, is_active` | نامِ دارو فیلترشده بر کلاس + دوزِ استاندارد. |
| `surgery_history` | `id, patient_link_id, title, performed_on, note, created_at` | سابقهٔ جراحی. |
| `medical_history` | `id, patient_link_id, title, note, since, created_at` | سابقهٔ بیماری/کوموربیدیتی. |
| `clinical_notes` | `id, patient_link_id, kind, body, recorded_at, recorded_by` | `kind ∈ symptom\|exam\|lifestyle\|general`. |
| `prescriptions` | `id, patient_link_id, kind, items, mode, insurer, portal_rx_id, prescriber_user_id, issued_at, followup_task_id` | لاگِ نسخه؛ `mode ∈ free\|insurance`. |
| `engagement_approvals` | `id, patient_link_id, event_key, channel, due_date, message, offer, status, period_key, appointment_id, decided_by, decided_at, sent_at` | صفِ تأییدِ پزشک؛ `offer` برای فاز۸. |
| ستون‌های `users` | `+ api_token TEXT` (و نقش/پرچمِ doctor) | **هویتِ پزشک = همان کاربرِ staff**؛ توکن برای اکستنشن. جدولِ جدا لازم نیست. |
| ستون‌های موجود | `flag_catalog.record_section` · `followup_tasks.appointment_id`+`fulfillment(remote\|in_person)` · `engagement_events.event_type(+is_custom)` · تنظیماتِ مهر/امضا در `settings` | — |

**اصلِ تفکیک:** آزمایش‌ها از `vital_readings`ِ موتور جدا (کاتالوگ فقط واحد/رِنج را پر می‌کند). موتورِ ریسک بدون تغییر.

---

## فاز ۰ — حذف‌ها و جابه‌جایی‌های سریع (کم‌ریسک، بدونِ تغییرِ داده)
1. `manager/index.html` (L39–52): حذفِ جدولِ «بیماران به تفکیک بیماری» + `by_condition` از `manager.index` context اگر بی‌مصرف شد.
2. `patients/detail.html` (L503–524): حذفِ کارتِ کیف‌پول؛ زیرساختِ `WalletRepository` و دادهٔ context دست‌نخورده (جای جدید = micro-decision).
3. `patients/detail.html` (L155–157) و `analytics.html` (L75–77): حذفِ دکمهٔ «تولید پیگیری‌های سررسیده».
4. `sms/_hub_tabs.html` (L11): حذفِ تبِ «ورک‌لیست تماس» در صفحاتِ کمپین/تعامل (با فلگِ context؛ در صفحهٔ ورک‌لیست بماند).
5. `patients/detail.html` (L399–415): حذفِ کارتِ «رویدادهای دارویی»؛ ثبتِ رویداد در DB ادامه دارد.
**تست:** بصری روی دمو؛ هیچ روتی نشکند.

## فاز ۱ — پایهٔ مدلِ داده (بعدی؛ دقیق)
**۱-الف schema/migration:** افزودنِ ۸ جدول + ستون‌های §۲ به `src/adapters/sqlite/schema.sql` (با `CREATE TABLE IF NOT EXISTS` + `INSERT OR IGNORE` برای seed) و `core.py::_run_migrations` (`_ensure_column` برای ستون‌های جداولِ موجود؛ `CREATE TABLE IF NOT EXISTS` برای جداولِ جدید — امن روی DBِ موجود).
**۱-ب seedها (idempotent، در bootstrap مثلِ `clinical_rules_seed`):**
- `lab_catalog_seed.py`: آزمایش‌های رایجِ ایران (CBC، FBS/2hpp، HbA1c، لیپید، کراتینین/eGFR، UACR، TSH/T4، کبدی AST/ALT، الکترولیت‌ها، ویتامین D، …) با واحد/رِنجِ مرجع.
- نگاشتِ `condition_lab_tests`: per-disease (دیابت/فشار/چربی/کلیه/تیروئید).
- `drug_catalog_seed.py`: ~۳۰ داروی پرکاربردِ هر بیماری، با `drug_class_key` و `standard_doses`.
- re-sectionِ `flag_catalog.record_section` برای رفعِ به‌هم‌ریختگیِ دسته‌ها.
**۱-ج repoها (یک repo per aggregate):** `lab_catalog_repo.py`، `drug_catalog_repo.py`، `record_repo.py` (surgery/medical/clinical_notes/prescriptions)، توسعهٔ `engagement_repo` (approvals + create_event)، `followups_repo` (appointment_id/fulfillment/search/list_for_patient)، و توکنِ کاربر در `auth`/users repo.
**تست:** اجرای اپ روی `specialist.db`ِ موجود؛ migration **دوبار = صفر تغییر**؛ seedها idempotent؛ repoها با اسکیما هم‌خوان؛ هیچ SQL در service/route.

## فاز ۲ — تبِ «پرونده و داده»
گیتِ بیماری‌محور + ۷ سکشنِ مرتب (وضعیت‌کلی/بیماری‌ها(گیت)/سابقهٔ‌پزشکی‌وجراحی/سبک‌زندگی/حساسیت/علائم‌ومعاینه/آزمایش) + ثبتِ چندآزمایشِ کاتالوگی (دراپ‌داون→واحد/رِنجِ خودکار، چیپ‌های per-disease، گریدِ دسته‌ای، پنلِ بازشونده). **تست.**

## فاز ۳ — تبِ «داروها»
فرمِ افزودن: کلاس→نام(سرچ از `drug_catalog`)→دوزِ استاندارد؛ حذفِ تاریخِ شروع؛ تجدید ۱۵روز/۱/۲/۳ماه (`today+N`). باکس‌های تغییردوز/قطع پشتِ دکمهٔ «اقدام». ابزارِ دوزِ per-disease (انسولینِ تعاملیِ دیابتی `code=='diabetes'`؛ بقیه مودالِ پیشنهادِ دوز با titration+دوزِ فعلی). **تست.**

## فاز ۴ — نمای کلی + پشتیبان بالینی + روند
روندِ بی‌داده مخفی (تایل؛ کارتِ گروه فقط وقتی کلِ گروه خالی) + کارتِ «اثرِ دارو» منتقل‌شده. نمای کلی per-disease (شاخص≤۳ با `risk_weight>0`، وضعیت/ریسکِ هر بیماری) + **حفظِ امتیازِ کلی**. ایمنی داخلِ باکسِ دارو؛ پایش/غربالگری/واکسن = جدولِ فشرده؛ تأیید→ابزارِ دوزِ پیش‌پرشده (`drug_class`+`dose`، ثبت در `suggestion_log`). **تست.**

## فاز ۵ — پیگیری/ورک‌لیست + ویزیت + از‌راه‌دور
ورک‌لیستِ آکاردئونیِ per-patient + جستجوی کدملی/نام/موبایل. `fulfillment` (سبک=remote، بقیه=in_person). اتصال به ویزیت (`appointment_id`) + ادغامِ چند پیگیریِ هم‌موعد در یک ویزیت. معیارِ **نرخِ تبدیلِ پیگیری→ویزیت** در اتاقِ کنترل. **تست.**

## فاز ۶ — موتورِ تعامل + صفِ تأیید + دعوت + نسخهٔ آزاد + seamهای پل
ثبتِ رویداد/کانالِ جدید (واژگانِ محدود). **صفِ تأییدِ هر-بیمار** (پیامک فقط بعد از تأییدِ پزشک). پیامکِ دعوت/نوبت‌دهی. مسیرِ remote → **نسخهٔ آزاد** + ثبت در `prescriptions`. **قلابِ `offer`** (فاز۸). **seamهای پل:** `users.api_token`، endpointهای `GET /api/ext/pending` و `POST /api/ext/captured`، فیلدهای بیمه‌ایِ `prescriptions`. **تست.**

## فاز ۷ — یکپارچگی
تعیینِ تکلیفِ `analytics.html` + به‌روزرسانیِ docs/مموری/گراف.

## فاز ۸ (آینده) — موتورِ پیشنهاد/قیمتِ بازگشت
هدف‌گیری = «در‌حالِ‌ریزشِ پرارزشِ» اتاقِ کنترل. وسیله = **اعتبارِ کیف‌پول (نه «تخفیف»)**. اندازه‌گیری با **holdout/incrementality**. پرداختِ آتی فقط ثبت؛ تسویه در حسابداری ([`accounting_sync.md`](accounting_sync.md)). اخلاق: فقط رفعِ مانعِ مراقبتِ لازم.

---

## ترکِ موازی — «پل نسخه‌نویسی» (اکستنشنِ مرورگر؛ بعد از فاز ۵/۶)

> کدبیسِ **جدا** (Manifest V3). آخرین‌مایلِ قیفِ از‌راه‌دور. seamهای اپ در فاز ۶.

**اصول:** پزشک با **لاگینِ خودش** وارد پنلِ وب می‌شود؛ اکستنشن روی همان نشست کار می‌کند (رمز ذخیره نمی‌شود، مجوزِ شرکتی لازم نیست). **چند سامانه (سلامت، خدمات‌درمانی، نیروهای‌مسلح، …) = آداپتورهای plug-in با اینترفیسِ مشترک** (`detectFinalizedRx()`، `extract()→{national_id, items, portal_rx_id, insurer}`، `fill(items)`)؛ همه **SPA** (hash-routing + `MutationObserver`). **چند پزشک = همان کاربرِ `staff` + `users.api_token`**. هویتِ بیمار با `national_id`. **ثبتِ نهایی همیشه با کلیکِ پزشک**. baselineِ نسخهٔ آزاد می‌ماند.

**seamهای Flask (فاز ۶):** `GET /api/ext/pending` (نسخه‌های remoteِ تأییدشده) · `POST /api/ext/captured` (`national_id`, items, `portal_rx_id`, `insurer` → بستنِ پیگیری + ثبت در `prescriptions`)؛ توکن اجباری، مبدأ محدود به دامنه‌های پنل + localhost.

**زیرفازها:** **E0** اسکلت MV3 + توکن → **E1 Capture (اول)**: آداپتورِ تأمین اجتماعی `https://ep.tamin.ir/view/#/blp` (هنگامِ ساخت، مالک HTML/اسکرین‌شاتِ صفحهٔ نسخهٔ نهایی می‌دهد) → **E2 Auto-fill** (در نقشه ثبت‌شده؛ بعد از E1) → **E3** سلامت و سایر سامانه‌ها.

**ریسک:** شکنندگیِ DOMِ SPA (نگه‌داری + fallbackِ دستی) · تفاوتِ پنل‌ها (آداپتورِ جدا) · امنیتِ توکن · حفظِ پزشک به‌عنوانِ دروازه. **بساز‌یا‌ادغام:** بررسیِ ابزارهای کمکیِ نسخه‌نویسیِ موجودِ ایران.

---

## ترتیب و وابستگی
`۰ → ۱ → (۲,۳,۴,۵,۶) → ۷ → [۸ آینده]`؛ **پل: بعد از ۵/۶ (E0→E1→E2→E3)**. فاز ۱ پیش‌نیازِ بقیه.

## micro-decisionها (غیرِبلوکه‌کننده)
محلِ نهاییِ کیف‌پول · فهرستِ دقیقِ seedِ آزمایش/دارو (بازبینیِ بالینی) · سرنوشتِ `analytics.html` · قالبِ نسخهٔ آزاد · نقشِ doctor (نقشِ سوم یا پرچمِ `is_prescriber` روی staff).

## ریسک‌ها
بازنویسیِ بزرگِ `detail.html` (per-tab) · دادهٔ بالینیِ seed (قابلِ‌ویرایش+بازبینی+دیسکلیمر) · تغییرِ موتورِ تعامل به approval (مراقبِ scheduler/idempotency) · شکنندگیِ اکستنشن.

## خارج از دامنه (بعداً)
inbound خودکارِ پیامکِ بیمار (بعد از احرازِهویت + خطِ اختصاصی) · کاتالوگِ کاملِ دارو/آزمایش · API رسمیِ بیمه (موجود نیست).

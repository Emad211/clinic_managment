# حسابرسی یکپارچهٔ انتقال حسابداری و کلینیک تخصصی به حلقه

این سند وضعیت واقعی مهاجرت را در شاخهٔ `agent/halqe-unified-migration-audit`
ثبت می‌کند. وجود schema، API یا صفحه به‌تنهایی به معنی «انتقال کامل» نیست. هر
قابلیت زمانی `complete` است که منطق دامنه، UI قابل‌استفاده، آزمون رفتاری و مسیر
مهاجرت/تطبیق دادهٔ تاریخی متناسب با همان قابلیت وجود داشته باشد.

## واژه‌نامهٔ وضعیت

| وضعیت | معنی |
|---|---|
| `complete` | منطق، UI و تست خودکار موجود است؛ برای دادهٔ تاریخی نیز مسیر مناسب وجود دارد یا قابلیت دادهٔ تاریخی ندارد. |
| `runtime-complete` | اجرای جدید آماده است، اما rehearsal یا ETL واقعی هنوز انجام نشده است. |
| `partial` | بخشی از جریان موجود است، ولی یک سطح عملیاتی یا مدیریتی کم است. |
| `missing` | هنوز در Halqe پیاده‌سازی نشده است. |
| `external-gate` | کد آماده است، ولی دادهٔ واقعی، امضای پزشک، پنل بیرونی یا تصمیم مالک لازم است. |

---

## ۱. مرزهای معماری مشترک

| قرارداد | وضعیت | شاهد |
|---|---|---|
| هویت بیمار فقط در `accounting.patients` | complete | clinical فقط `patient_link_id` نگه می‌دارد و resolve از Accounting Read Port عبور می‌کند. |
| clinical حق نوشتن حسابداری ندارد | complete | alias و port خواندنی، تست confinement و roleهای جداگانه. |
| write-side حسابداری نقش مستقل دارد | complete | `accounting_app` و login اختصاصی؛ platform/clinical برای آن revoke شده‌اند. |
| RLS و tenant scope | complete | tenant GUC، FKهای مرکب و تست‌های cross-tenant. |
| OpenAPI مشترک | complete | hash کامل schema + manifest دقیق ۸۳ path و ۸۷ operation؛ JSON کامل در CI artifact. |
| CI مشترک دو legacy oracle | runtime-complete | suite کامل Halqe، oracle مالی Flask و suite کامل specialist در یک workflow اجرا می‌شوند. |

---

## ۲. حسابداری

| قابلیت legacy | Backend Halqe | UI Halqe | تست/Oracle | ETL/Reconciliation | وضعیت |
|---|---|---|---|---|---|
| جست‌وجو و upsert بیمار پذیرش | موجود | `/accounting` | PostgreSQL + oracle | ETL بیمار باید از مرز هویت مشترک انجام شود | runtime-complete |
| ایجاد فاکتور و ویزیت | موجود | `/accounting` | atomicity، tariff، shift، audit | هنوز historical accounting ETL ندارد | runtime-complete |
| شیفت دستی کاربر | موجود | در جریان پذیرش | تست تاریخ/شیفت | import تاریخی تنظیمات باقی است | runtime-complete |
| کادر پزشک/پرستار شیفت | موجود | `/accounting/nursing` و `/procedures` | تست staff ownership | import تاریخی staff/shift باقی است | runtime-complete |
| پرداخت آیتمی و paid-only close | موجود | `/accounting/payments` | DB trigger + payment tests + oracle | reconciliation مالی واقعی باقی است | runtime-complete |
| خدمات پرستاری/تزریق | موجود | `/accounting/nursing` | پوشش بیمه، exclusion، snapshot | ETL تاریخی باقی است | runtime-complete |
| مصرفی/دارو | موجود | `/accounting/nursing` | liability و rollback | ETL تاریخی باقی است | runtime-complete |
| پروسیجر پزشک/پرستار | موجود | `/accounting/procedures` | performer و coverage snapshot | ETL تاریخی باقی است | runtime-complete |
| مشاهده و اصلاح فاکتور | موجود | `/accounting/invoices/{id}` | ownership، payment cleanup، totals | reconciliation واقعی باقی است | runtime-complete |
| مدیریت کادر درمان | schema فقط | ندارد | ندارد | ندارد | missing |
| مدیریت بیمه و تعرفهٔ ویزیت | schema/read فقط | ندارد | فقط pricing tests | ندارد | partial |
| مدیریت کاتالوگ پرستاری | read فقط | ندارد | service-read tests | ندارد | partial |
| مدیریت تعرفهٔ پروسیجر و مصرفی | read فقط | ندارد | mutation عملیاتی از catalog تست می‌شود | ندارد | partial |
| مدیریت exclusionهای بیمه | منطق خواندن موجود | ندارد | coverage tests | ندارد | partial |
| تنظیم درصدها و پایهٔ حقوق | schema موجود | ندارد | ندارد | ندارد | missing |
| داشبورد مالی مدیر | ندارد | ندارد | legacy تنها | ندارد | missing |
| گزارش فاکتور/بیمار/ویزیت/تزریق/پروسیجر/مصرفی | ندارد | ندارد | legacy تنها | ندارد | missing |
| خروجی CSV/Excel | ندارد | ندارد | ندارد | ندارد | missing |
| حقوق و دستمزد | فقط schema و legacy service | ندارد | ندارد | ندارد | missing |
| جست‌وجوی audit مدیریتی | write audit موجود | UI/read API ندارد | audit mutation tests | ندارد | partial |
| backup/reset/settings مدیریتی | ندارد | ندارد | ندارد | ندارد | missing |
| ETL تاریخی `clinic.db` | ندارد | — | oracle رفتار موجود | importer/ledger/verifier ندارد | missing |
| تطبیق مالی و dual-run | ندارد | — | oracle موجود | count/hash/money reconciliation ندارد | missing |
| cutover/rollback حسابداری | runbook مقدماتی | — | — | rehearsal نشده | external-gate |

### نتیجهٔ حسابداری

جریان عملیاتی پذیرش تا بستن فاکتور در Halqe اجرا می‌شود، اما **حسابداری کامل
منتقل نشده است**. چهار حوزهٔ الزامی باقی است:

1. مدیریت کاتالوگ‌ها، کادر، بیمه و تنظیمات حقوق؛
2. گزارش‌ها، dashboard مدیر، audit search و payroll؛
3. ETL تاریخی و reconciliation مبلغی؛
4. dual-run، backup/restore rehearsal و cutover.

---

## ۳. کلینیک تخصصی

| قابلیت legacy | Backend Halqe | UI Halqe | تست | ETL/Reconciliation | وضعیت |
|---|---|---|---|---|---|
| فهرست/جزئیات بیمار | موجود | موجود | tenant/API tests | از هویت حسابداری resolve می‌شود | complete |
| کاکپیت ایمنی | موجود | جذاب و responsive | snapshot/API/component tests | دادهٔ تاریخی از record ETL | runtime-complete |
| بیماری‌های مزمن | CRUD ساختاریافته | تب پرونده | duplicate/ownership/rollback | importer + ledger + verifier | runtime-complete |
| دارو و timeline | start/dose/stop اتمیک | تب دارو | lifecycle و component tests | importer + event mapping | runtime-complete |
| حساسیت‌ها | CRUD و هشدار | banner + editor | cross-tenant/safety | importer | runtime-complete |
| فلگ‌های بالینی | partial-safe typed API | گروه‌بندی‌شده | enum/date/rollback/PHI | importer | runtime-complete |
| سابقه پزشکی/جراحی/یادداشت | CRUD | UI فارسی | ownership/audit | importer | runtime-complete |
| علائم حیاتی و self-report | موجود | review inbox و روند | verify/reject/retention | importer؛ self-report unverified | runtime-complete |
| آزمایش و Observation | موجود | catalog/free-text | server-authoritative metadata | importer + fingerprint | runtime-complete |
| encounter و نسخه | موجود | ثبت و سابقه | service/API tests | importer نسخهٔ legacy/structured | runtime-complete |
| نوبت و پیگیری | read + worklist/queue | نمایش و worklist | tests | importer | runtime-complete |
| پیشنهادهای تصمیم‌یار | suggestion-only | ستون ثابت و action | rule/safety tests | catalogs source-of-truth | complete |
| اتاق کنترل | read-only prioritisation | UI جذاب، accessible | API/UI tests | داده از Halqe | complete |
| engagement approval queue | موجود | UI مدیریتی | consent/PHI/send gate | importer record آن را عمداً منتقل نمی‌کند | complete |
| patient card/self-report public channel | موجود، fail-closed | موجود | token/consent tests | تنظیم واقعی خارجی لازم | external-gate |
| dashboard outcome مدیر | read-only analytics | موجود | honest-denominator tests | دادهٔ واقعی لازم | runtime-complete |
| تنظیم provider پیامک و template | env/fail-closed، بخشی از settings | settings تعامل محدود | safety tests | secrets legacy عمداً import نمی‌شوند | partial |
| مدیریت کاربران و token extension | auth موجود | UI مدیریتی ندارد | auth tests | user mapping/cutover باقی است | partial |
| ویرایش indicatorهای بالینی | schema/read موجود | UI و write API ندارد | engine tests | catalog review لازم | missing |
| ویرایش decision-rule catalog | engine موجود | UI و write API ندارد | rule tests | sign-off پزشکی لازم | missing |
| protocol summary/editor | ندارد | ندارد | legacy تنها | ندارد | missing |
| تنظیم سربرگ/مهر نسخهٔ آزاد | بخشی در prescription domain نیست | ندارد | ندارد | تصمیم محصول لازم | missing |
| ETL historical specialist DB | کامل و fail-closed | command/runbook | importer/verifier/signoff tests | rehearsal واقعی باقی است | external-gate |
| clinician sign-off و release manifest | کامل | artifact workflow | policy/DB-binding/fresh-check tests | نیازمند پزشک و snapshot واقعی | external-gate |

### نتیجهٔ کلینیک تخصصی

پرونده و care-loop اصلی از نظر runtime و migration tooling تقریباً کامل است، اما
برای برابری کامل مدیریتی این موارد باقی‌اند:

- مدیریت کاربر و نقش‌ها؛
- editor امن indicatorها و decision ruleها؛
- protocol/settings مدیریتی؛
- rehearsal روی snapshot واقعی و امضای پزشک.

---

## ۴. معیار UX مشترک

تمام صفحات جدید باید این قرارداد را رعایت کنند:

- RTL و فونت فارسی؛
- keyboard navigation و `focus-visible`؛
- وضعیت‌ها فقط با رنگ منتقل نشوند؛
- loading، empty، error و success state صریح؛
- قالب ثابت تومان، تاریخ جلالی و ارقام فارسی؛
- desktop table با mobile card fallback؛
- operation خطرناک با confirmation و توضیح اثر؛
- سطح دسترسی در navigation و backend یکسان؛
- عدم نمایش PHI در URL query، log یا artifact عمومی؛
- breadcrumb و quick action برای جریان‌های چندمرحله‌ای؛
- componentهای مشترک به‌جای CSS تکراری هر صفحه.

وضعیت فعلی: صفحات تخصصی و workbenchهای حسابداری قابل‌استفاده و responsive هستند،
ولی حسابداری هنوز design-system مشترک، dashboard مدیریتی و mobile-card کامل ندارد.

---

## ۵. ترتیب اجرایی مصوب برای رسیدن به «کامل»

1. سبزکردن CI دو دامنه روی merge commit واقعی؛
2. پنل مدیریت حسابداری و catalog CRUD؛
3. گزارش مالی، audit search و payroll؛
4. importer و verifier تاریخی حسابداری؛
5. editorهای مدیریتی rule/indicator و user management کلینیک؛
6. یکپارچه‌سازی App Shell و design system؛
7. rehearsal هر دو SQLite روی PostgreSQL staging؛
8. clinician + financial sign-off؛
9. backup/restore rehearsal، dual-run و cutover.

تا پایان مراحل ۲ تا ۸، PR یکپارچه باید Draft بماند و هیچ legacy app بازنشسته نشود.

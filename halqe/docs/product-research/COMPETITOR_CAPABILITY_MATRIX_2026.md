# ماتریس قابلیت رقبا و جایگاه هدف Halqe — ۲۰۲۶

**هدف:** مقایسهٔ جهت محصول، نه تأیید ادعاهای تجاری رقبا.  
**روش:** صفحات رسمی محصول برای capability claim و مقالات peer-reviewed برای ادعاهای outcome.  
**هشدار:** عبارت‌های مربوط به شرکت‌ها «ادعای vendor» هستند مگر اینکه منبع پژوهشی مستقل جداگانه ذکر شود.

---

## ۱. گروه‌بندی بازار

### پورتال و EHR-facing

**MyChart** روی دسترسی بیمار به appointment، results، medications، messages، bills، family care و virtual visit تمرکز دارد. مزیتش breadth و اتصال عمیق به EHR است، اما ذاتاً یک operating model واحد برای care-loopهای کلینیک مستقل نیست.

### digital chronic-care program

**Omada** و **Dario** تجربهٔ چندبیماری، coaching، connected devices، آموزش و رفتار را به‌صورت program عرضه می‌کنند. مزیت آن‌ها patient engagement و service layer است.

### cardiometabolic decision support

**Welldoc** بر insightهای cardiometabolic، personalization و اتصال member/care team تمرکز دارد.

### clinical RPM operations

**Cadence** مدل physician-led monitoring، triage، care team و treatment workflow را عرضه می‌کند. تمایز اصلی آن «عملیات انسانی پشت داده» است، نه فقط dashboard.

### configurable digital-health infrastructure

**Huma** بر زیرساخت، appهای configurable، remote monitoring، clinical dashboard و deployment سازمانی تمرکز دارد.

---

## ۲. ماتریس قابلیت

علامت‌ها:

- **●** قابلیت محوری و برجسته در positioning رسمی
- **◐** وجود دارد ولی محور اصلی یا عمق آن نامشخص است
- **○** در منابع بررسی‌شده برجسته نبود
- **—** نامرتبط یا شواهد کافی نداریم

| قابلیت | MyChart | Omada | Dario | Welldoc | Cadence | Huma | Halqe فعلی | Halqe هدف |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| پرونده و نتایج بیمار | ● | ◐ | ◐ | ◐ | ◐ | ● | ● | ● |
| appointment و virtual care | ● | ◐ | ◐ | ◐ | ● | ● | ● | ● |
| پیام بیمار و تیم | ● | ● | ● | ◐ | ● | ● | ◐ | ● |
| family/caregiver access | ● | ◐ | ◐ | ○ | ◐ | ◐ | ○ | ● |
| care plan و goal | ◐ | ● | ● | ● | ● | ● | ○ | ● |
| Today/action dashboard | ◐ | ● | ● | ● | ◐ | ◐ | ○ | ● |
| coaching انسانی | ○ | ● | ● | ◐ | ● | ◐ | ○ | ●/configurable |
| connected devices | ◐ | ● | ● | ● | ● | ● | محدود | ● |
| remote monitoring | ◐ | ● | ● | ● | ● | ● | محدود | ● |
| 24/7 clinical triage | ○ | ◐ | ◐ | ○ | ● | configurable | ○ | policy/service-dependent |
| medication workflow | ● | ◐ | ◐ | ● | ● | ◐ | ● | ● |
| physician-led titration | EHR-dependent | ○ | ○ | support | ● | configurable | ○ | فقط تحت protocol آینده |
| AI/personalized insight | EHR-dependent | ◐ | ● | ● | ● | ● | rule engine اولیه | hybrid governed CDS |
| explainable evidence/version | نامشخص | نامشخص | نامشخص | محدود عمومی | محدود عمومی | configurable | source_ref/evidence اولیه | ● |
| human review state | ◐ | ● | ● | ◐ | ● | ● | self-report verify | ● |
| closed-loop owner/SLA | EHR/workflow-dependent | program ops | program ops | نامشخص | ● | configurable | follow-up ساده | ● |
| population workbench | ● | ● | ● | ● | ● | ● | manager analytics اولیه | ● |
| clinic accounting | billing-facing | — | — | — | — | — | ● | ● |
| payroll/clinic operations | ○ | — | — | — | — | — | ● | ● |
| multi-tenant clinic SaaS | enterprise | employer/plan | enterprise | enterprise | health-system | enterprise platform | زیرساخت موجود | ● عمومی‌شده |
| بیمه و workflow بومی ایران | ○ | ○ | ○ | ○ | ○ | ○ | ● | ● |
| فارسی/RTL | ○ | ○ | ○ | ○ | ○ | configurable | ● | ● |
| low-data/offline-first | نامشخص | app-dependent | app-dependent | app-dependent | connected-care dependent | configurable | محدود | ● |
| clinic owns patient workflow | EHR organization | program provider | program provider | partner model | physician partnership | deployer | ● | ● |

---

## ۳. چیزهایی که رقبا بهتر از Halqe فعلی انجام می‌دهند

### MyChart

- حساب بیمار و recovery بالغ؛
- family/proxy access؛
- یکپارچگی appointment، results، messages و billing؛
- تجربهٔ قابل‌پیش‌بینی برای میلیون‌ها کاربر.

**درس:** patient identity، caregiver access و navigation پایه باید قبل از featureهای هوشمند بالغ شوند.

### Omada و Dario

- onboarding برنامه‌ای؛
- coaching و human relationship؛
- connected device experience؛
- درس‌های کوتاه و رفتارمحور؛
- تجربهٔ یکپارچه برای چند وضعیت cardiometabolic.

**درس:** dashboard بدون service model و coaching/response layer engagement پایدار نمی‌سازد.

### Welldoc

- تبدیل داده‌های پراکندهٔ cardiometabolic به insight؛
- personalization به‌عنوان هستهٔ محصول؛
- positioning روشن حول intelligence.

**درس:** پیشنهادها باید context-aware و قابل‌اقدام باشند، نه فهرست ruleهای خام.

### Cadence

- مسئولیت روشن تیم بالینی؛
- monitoring روزانه؛
- triage و escalation؛
- اتصال به workflow پزشک؛
- استفاده از automation برای موارد قابل‌پیش‌بینی و انتقال موارد پیچیده به انسان.

**درس:** مزیت واقعی RPM در dashboard نیست؛ در operating model، SLA و clinical capacity است.

### Huma

- configurability سازمانی؛
- pathway و dashboard قابل‌تنظیم؛
- زیرساخت deployment و integration؛
- چند use case روی یک platform.

**درس:** multi-tenancy باید به configuration system واقعی تبدیل شود، نه fork برای هر درمانگاه.

---

## ۴. مزیت بالقوهٔ Halqe

Halqe می‌تواند چیزی بسازد که در این ترکیب کمتر دیده می‌شود:

```text
Clinic-native EHR / record
+ operations and accounting
+ closed-loop chronic care
+ patient and caregiver experience
+ governed scientific recommendation engine
+ local payer and workflow configuration
+ multi-tenant SaaS
```

این مزیت فقط با جمع‌کردن menuها ایجاد نمی‌شود. شروط دفاع‌پذیری:

1. Care Loop واقعاً owner، SLA، evidence و closure داشته باشد.
2. patient dashboard به action و response انسانی متصل باشد.
3. موتور دانش provenance، version، test و monitoring داشته باشد.
4. حسابداری configuration-driven و مستقل از درمانگاه اولیه شود.
5. data migration و audit برای onboarding کلینیک‌ها محصول‌شده باشد.
6. فارسی، بیمه، جریان پذیرش و عملیات منطقه‌ای عمیق باشد.
7. multi-tenant safety و customization بدون fork انجام شود.

---

## ۵. ضدتمایزها: چیزهایی که نباید به‌عنوان مزیت ادعا شوند

- «داشبورد دارد»؛ همه دارند.
- «AI دارد»؛ بدون validation و workflow ارزش مشخصی ندارد.
- «داده جمع می‌کند»؛ collection بدون review loop مزیت نیست.
- «همه‌چیز در یک اپ است»؛ اگر UX شلوغ و ownership مبهم باشد، حتی ضعف است.
- «بیمار را درگیر می‌کند»؛ باید با action completion و response قابل‌اندازه‌گیری نشان داده شود.
- «نتیجه درمان را بهتر می‌کند»؛ پیش از pilot معتبر نباید ادعا شود.

---

## ۶. gapهای اولویت‌دار Halqe نسبت به بازار

### سطح صفر: اعتماد و دسترسی

- authenticated patient account؛
- account recovery؛
- caregiver/proxy؛
- consent و audit؛
- notification preferences؛
- privacy controls.

### سطح یک: تجربهٔ روزانه

- Today dashboard؛
- care plan و goal؛
- tasks بیمار؛
- messaging؛
- status بررسی داده؛
- expected response time؛
- education contextual.

### سطح دو: عملیات مراقبت

- care loop؛
- owner/team/queue؛
- SLA و escalation؛
- communication receipts؛
- outcome evidence؛
- unified staff inbox؛
- cohort exception workbench.

### سطح سه: علم و هوشمندی

- evidence registry؛
- versioned guideline packs؛
- explainable recommendation؛
- suppression و alert budget؛
- conflict resolution چندبیماری؛
- shadow mode و evaluation؛
- risk model governance.

### سطح چهار: مقیاس‌پذیری کسب‌وکار

- tenant configuration center؛
- multi-location؛
- integration adapters؛
- device/channel marketplace؛
- implementation tooling؛
- migration/reconciliation product؛
- capacity and unit-economics analytics.

---

## ۷. موقعیت پیشنهادی برند

### گزینهٔ نامناسب

> نرم‌افزار مدیریت مطب با هوش مصنوعی

بیش از حد عمومی و قابل‌کپی است.

### جهت پیشنهادی

> حلقه، سیستم‌عامل مراقبت پیوسته برای کلینیک‌هایی است که می‌خواهند بیمار مزمن را از ویزیت پراکنده به برنامهٔ قابل‌پیگیری، اقدام‌محور و علمی منتقل کنند؛ در حالی که پرونده، عملیات و حسابداری همان کلینیک در یک پلتفرم چندمستاجره باقی می‌ماند.

### وعدهٔ محصولی قابل‌آزمایش

> هیچ پیگیری مهمی بدون مالک، زمان پاسخ و نتیجهٔ قابل‌اثبات رها نشود.

این وعده باید با telemetry Care Loop اثبات شود.

---

## ۸. سؤال‌های رقابتی برای مصاحبه و discovery

- کلینیک امروز برای کارهای پس از ویزیت از چه ابزارهایی استفاده می‌کند؟
- چه کسی مسئول تماس و پیگیری است و مدیر چگونه می‌فهمد کار انجام شده؟
- بیمار کجا می‌فهمد داده‌اش دیده شده است؟
- خانواده چگونه وارد جریان می‌شود؟
- چند درصد پیام‌ها بی‌پاسخ می‌مانند؟
- alertهای فعلی پزشک چقدر نادیده گرفته می‌شوند؟
- حسابداری و مراقبت کجا به هم نیاز دارند و کجا باید جدا باشند؟
- کلینیک حاضر است برای کدام service layer پول بدهد: software، monitoring، navigator یا outcome contract؟
- چه بخشی باید توسط کلینیک انجام شود و چه بخشی می‌تواند سرویس Halqe باشد؟

---

## ۹. منابع رسمی محصول

این منابع capability و positioning رسمی شرکت‌ها را نشان می‌دهند و به‌تنهایی اثبات outcome نیستند:

- [MyChart](https://www.mychart.org/)
- [Omada Health](https://www.omadahealth.com/)
- [DarioHealth](https://www.dariohealth.com/)
- [Welldoc](https://www.welldoc.com/)
- [Cadence](https://www.cadence.care/)
- [Huma](https://www.huma.com/)

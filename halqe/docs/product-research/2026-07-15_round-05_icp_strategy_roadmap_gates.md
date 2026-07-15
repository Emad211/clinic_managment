# دور پنجم پژوهش عمیق محصول حلقه

**تاریخ:** ۲۰۲۶-۰۷-۱۵  
**موضوع:** ICP اولیه، مزیت رقابتی، Product Pillars، dependency graph، roadmap مبتنی بر outcome و معیارهای build / defer / kill  
**وضعیت:** تصمیم راهبردی موقت و قابل‌آزمون؛ نه تعهد roadmap، نه ادعای بازار، نه دستور بالینی  
**شاخهٔ مبنا:** `agent/halqe-unified-migration-audit`

---

## ۱. سؤال پژوهش

پس از تثبیت این پایه‌ها:

- پرونده و عملیات کلینیک؛
- حسابداری، گزارش، payroll و audit؛
- ابزار مهاجرت و reconciliation؛
- تعریف Care Loop؛
- PRD پرتال بیمار و همراه؛
- حاکمیت Clinical Program و CDS؛
- مدل چندمستاجری و مرز Revenue Cycle؛

محصول باید به این سؤال پاسخ دهد:

> حلقه برای کدام نوع مرکز، با کدام workflow اولیه، چه وعدهٔ قابل‌اندازه‌گیری و با چه ترتیب سرمایه‌گذاری باید وارد پایلوت شود؟

این دور عمداً از «فهرست قابلیت‌ها» فاصله می‌گیرد. هدف آن انتخاب یک **wedge باریک، قابل‌فروش، قابل‌پیاده‌سازی و قابل‌اندازه‌گیری** است.

---

## ۲. نتیجهٔ اجرایی

فرضیهٔ راهبردی این دور:

> **ICP اولیهٔ حلقه، مطب تک‌پزشک، بیمارستان بزرگ، بیمه‌گر یا محصول مستقیم برای مصرف‌کننده نیست. بهترین نقطهٔ شروع، کلینیک تخصصی یا چندتخصصی کوچک تا متوسطِ صاحب رابطهٔ طولی با بیماران مزمن است؛ مرکزی که تیم درمان و عملیات مشخص، درد واقعی پیگیری، دادهٔ قابل‌مهاجرت و یک مسئول اجرایی برای پاسخ‌گویی دارد.**

صورت دقیق‌تر ICP پیشنهادی:

```text
کلینیک خصوصی یا غیردولتی فارسی‌زبان
+ یک تا چند شعبه محدود
+ پنل معنادار بیمار بالغ مبتلا به دیابت نوع ۲، فشارخون یا ریسک قلبی‌متابولیک
+ پزشک مسئول بالینی
+ حداقل یک نقش عملیاتی قابل‌نام‌گذاری برای پیگیری
  (پرستار، مراقب سلامت، منشی آموزش‌دیده یا care navigator)
+ پیگیری فعلی پراکنده میان تماس، پیام‌رسان، کاغذ و فایل
+ نیاز هم‌زمان به پرونده، عملیات، مالی و پیگیری
+ آمادگی برای پایلوت اندازه‌گیری‌شده و تغییر workflow
```

وعدهٔ اولیه نباید «بهبود قطعی HbA1c»، «کاهش بستری» یا «هوش مصنوعی بهتر» باشد.

وعدهٔ قابل‌آزمون:

> **هیچ پیگیری مهمی بدون owner، زمان پاسخ، وضعیت روشن و evidence قابل‌ارجاع رها نشود.**

wedge محصول:

```text
Care Loop Operations
روی پرونده و عملیات واقعی همان کلینیک
با پرتال محدود و action-first برای بیمار
و CDS در shadow / suggestion-only
```

---

## ۳. وضعیت واقعی محصول و محدودیت انتخاب

حلقه از صفر شروع نمی‌کند. شاخهٔ فعلی زیرساخت قوی در این حوزه‌ها دارد:

- پروندهٔ بیمار، دارو، حساسیت، بیماری، علائم حیاتی، آزمایش، نسخه، نوبت و پیگیری؛
- عملیات پذیرش، فاکتور، پرداخت، خدمات، تعرفه، بیمه و حقوق؛
- گزارش و audit؛
- ETL تاریخی، import ledger، replay و verifier؛
- backup/restore fingerprint، dual-run، sign-off و release manifest؛
- کارت عمومی بیمار و self-report محدود؛
- موتور پیشنهاد suggestion-only با gate دادهٔ verified.

اما هنوز این اجزای راهبردی runtime-complete نیستند:

- Care Loop مستقل با owner، queue، SLA، attempt history، outcome evidence و closure contract؛
- Portal Identity و Patient Account؛
- caregiver grant رسمی؛
- صندوق درخواست ساختاریافتهٔ بیمار؛
- Clinical Program و Rule Version تغییرناپذیر؛
- Recommendation Instance قابل بازسازی؛
- Organization / Location / Department / Membership کامل؛
- ابزار onboarding تکرارپذیر برای چند کلینیک؛
- دادهٔ پایلوت واقعی دربارهٔ ظرفیت، adoption، willingness-to-pay یا outcome.

بنابراین راهبرد باید از **دارایی‌های موجود** استفاده کند، ولی روی قابلیت‌هایی که هنوز اثبات نشده‌اند وعده نسازد.

---

## ۴. سنتز شواهد این دور

### ۴.۱ فناوری به‌تنهایی مدل مراقبت نیست

مرور شواهد Health IT برای افراد دارای چند بیماری مزمن، نتایج ناهمگون و محدود گزارش می‌کند. نقش‌ها، مسئولیت‌ها، همکاری تیمی و سازگاری با workflow تعیین‌کننده‌اند؛ نبود interoperability می‌تواند مستندسازی و بار ارائه‌دهنده را افزایش دهد ([Samal et al., 2021](https://doi.org/10.1111/1475-6773.13860)).

مرورهای مداخلات دیجیتال پرستاری نیز نشان می‌دهند که training، coaching و تعامل انسانی از مؤلفه‌های تکرارشونده‌اند و یک مدل دیجیتال واحد به‌طور یکنواخت بهتر نیست ([Mikkonen et al., 2022](https://doi.org/10.1111/jocn.16448)).

**نتیجهٔ محصولی:** حلقه نباید با app، dashboard یا device فروخته شود؛ باید با مدل تحویل خدمت و workflow پاسخ فروخته شود.

### ۴.۲ fit با مرکز و workflow از breadth قابلیت مهم‌تر است

مطالعهٔ implementation در کلینیک‌های تخصصی نشان داد service fit، buy-in ذی‌نفعان، طراحی workflow، pilot و مستندسازی استاندارد برای ماندگاری خدمت حیاتی‌اند؛ چند مرکز خدمت را به‌دلیل fit ضعیف متوقف کردند ([Livet et al., 2023](https://doi.org/10.1002/jac5.1821)).

پژوهش‌های implementation جدید نیز integration داده، outreach به‌موقع، حمایت رهبری، champion بالینی و staffing کافی را برای sustainment برجسته می‌کنند ([Garcia et al., 2026](https://doi.org/10.1111/1475-6773.70124); [Burns et al., 2026](https://doi.org/10.1002/alz.71405)).

**نتیجهٔ محصولی:** مرکزی که owner اجرایی یا ظرفیت پاسخ ندارد، حتی با علاقهٔ پزشک ICP مناسب نیست.

### ۴.۳ workload و اقتصاد باید هم‌زمان با adoption اندازه‌گیری شوند

مرور مدل‌های یکپارچهٔ مراقبت مزمن، ناهمگونی زیاد و نبود یک مدل برتر واحد را نشان می‌دهد؛ نقش‌ها، آموزش و ترکیب تیم باید صریح گزارش شوند ([Longhini et al., 2021](https://doi.org/10.1111/hsc.13611)).

ارزیابی مدل‌های nurse-led باید علاوه بر تجربه و سلامت جمعیت، delivery system، تجربهٔ ارائه‌دهنده، هزینهٔ عملیاتی، staffing و funding را بسنجد ([Li et al., 2025](https://doi.org/10.1111/jocn.17791)). پژوهش دیگری هشدار می‌دهد که کار پرستاری در برنامه‌های مزمن می‌تواند در داده‌های معمول نامرئی بماند و بدون مستندسازی workload، برنامه ظاهراً مقیاس‌پذیر ولی عملاً فرساینده باشد ([Zaghini et al., 2025](https://doi.org/10.1111/phn.70053)).

در محیط‌های با منابع محدود، صرفه‌جویی‌های فنی لزوماً نقدشونده یا قابل‌تصاحب نیستند؛ هزینه و منفعت ممکن است به بازیگران متفاوت برسد و زیرساخت، نیروی انسانی و مدیریت تعیین‌کننده‌اند ([Atiku & Olakotan, 2026](https://doi.org/10.1111/jep.70372)).

**نتیجهٔ محصولی:** metricهایی مثل login، message count و reading count کافی نیستند. هزینهٔ هر loop، زمان هر نقش، after-hours work و ظرفیت پاسخ باید از روز اول ثبت شوند.

### ۴.۴ پرتال بدون بازخورد و onboarding می‌تواند به کانال رهاشده تبدیل شود

برای سالمندان و افراد چندبیماری، ارزش قابل‌فهم، سادگی login، خوانایی، digital literacy، آموزش، حمایت خانواده و بازخورد تیم درمان بر استفادهٔ مداوم اثر دارند ([Samal et al., 2021](https://doi.org/10.1111/1475-6773.13860); [Shiu et al., 2025](https://doi.org/10.1111/jan.70207)).

پژوهش mixed-methods در سالمندان تأکید می‌کند که self-assessment بدون امکان حمایت حرفه‌ای نباید تفسیر شود و باید برای افراد فاقد دسترسی یا سواد دیجیتال مسیر جایگزین وجود داشته باشد ([Schumacher et al., 2024](https://doi.org/10.1111/opn.12667)).

مطالعات جدید بر trust، readability، personalization، سازگاری با workflow، دسترس‌پذیری حسی/حرکتی، caregiver facilitation و reinforcement چندکاناله تأکید دارند ([Mundo et al., 2026](https://doi.org/10.1111/acem.70261)).

مرور patient engagement گزارش می‌کند که care partnerها اغلب به‌طور غیررسمی از credential بیمار استفاده می‌کنند؛ ثبت رسمی proxy می‌تواند continuity و accountability را بهتر کند ([Schiavone et al., 2025](https://doi.org/10.1111/beer.70035)).

**نتیجهٔ محصولی:** Patient Portal باید پس از queue و response contract کارکنان ساخته شود، نه پیش از آن.

### ۴.۵ پایلوت باید implementation outcome را از clinical outcome جدا کند

Implementation science میان سه سطح تفاوت می‌گذارد:

```text
Implementation outcomes
→ acceptability, adoption, appropriateness, cost,
  feasibility, fidelity, penetration, sustainability

Service outcomes
→ efficiency, safety, effectiveness, equity,
  patient-centeredness, timeliness

Client outcomes
→ satisfaction, function, symptoms, quality of life,
  disease-specific outcomes
```

این تفکیک در چارچوب‌های RE-AIM و Implementation Outcomes Framework صریح است ([Kuo et al., 2022](https://doi.org/10.1002/jac5.1673)). مرور چارچوب‌های مداخلات دیجیتال نیز توصیه می‌کند feasibility و acceptability پیش از effectiveness و scale آزموده شوند و context، stakeholder، economics و programme theory ثبت شوند ([Vega et al., 2024](https://doi.org/10.1002/ejp.2262)).

بسیاری از مطالعات implementation فقط feasibility و acceptability را می‌سنجند و fidelity، cost، penetration و sustainability را نادیده می‌گیرند ([Bacci et al., 2019](https://doi.org/10.1002/jac5.1136); [Paolinelli et al., 2025](https://doi.org/10.1111/jep.70285)).

**نتیجهٔ محصولی:** پایلوت حلقه بدون metricهای fidelity، workload، cost و sustainment، حتی با رضایت بالا، مجوز scale نیست.

---

## ۵. انتخاب ICP

### ۵.۱ معیارهای امتیازدهی

هر segment با هشت معیار ۱ تا ۵ امتیاز می‌گیرد. امتیازها **فرضیهٔ داخلی** هستند و باید با مصاحبه، مشاهده و دادهٔ فروش اصلاح شوند.

| معیار | وزن | سؤال |
|---|---:|---|
| شدت مسئله | ۱۵٪ | آیا پیگیری رهاشده، ابهام مالکیت و fragmentation درد پرتکرار است؟ |
| fit با محصول موجود | ۱۵٪ | آیا پرونده، عملیات، مالی و migration فعلی ارزش فوری ایجاد می‌کنند؟ |
| کنترل workflow | ۱۵٪ | آیا خریدار می‌تواند نقش، SLA و فرایند را تغییر دهد؟ |
| وضوح buyer و budget | ۱۰٪ | آیا تصمیم‌گیر و منفعت اقتصادی قابل‌شناسایی است؟ |
| پیچیدگی implementation | ۱۵٪ | آیا بدون integration سنگین و procurement طولانی می‌توان پایلوت کرد؟ |
| بار ایمنی و پاسخ | ۱۰٪ | آیا scope اولیه بدون ۲۴/۷ و درمان خودکار ایمن می‌ماند؟ |
| ظرفیت توسعه | ۱۰٪ | آیا از wedge می‌توان به program، portal، finance و multi-location گسترش یافت؟ |
| قابلیت اندازه‌گیری | ۱۰٪ | آیا baseline، event و outcome قابل ثبت‌اند؟ |

### ۵.۲ scorecard موقت segmentها

| Segment | امتیاز وزنی / ۵ | تفسیر |
|---|---:|---|
| کلینیک تخصصی/چندتخصصی کوچک تا متوسط با پنل مزمن | **۴٫۴۵** | بهترین fit میان درد، کنترل workflow، محصول موجود و امکان پایلوت. |
| درمانگاه چندشیفت یا مرکز چندبخشی متوسط | ۳٫۶۵ | ارزش بالقوه بالا، ولی نقش، شعبه، صندوق، SLA و implementation پیچیده‌تر است. |
| مطب تک‌پزشک | ۳٫۳۰ | تصمیم‌گیری سریع، اما ظرفیت پاسخ و willingness-to-pay برای operating model محدودتر است. |
| payer / employer population health | ۲٫۸۰ | جمعیت و budget ممکن است جذاب باشد، ولی رابطهٔ درمانی و کنترل workflow ضعیف و integration سنگین است. |
| بیمارستان یا health system بزرگ | ۲٫۵۵ | مسئله بزرگ است، اما procurement، integration، governance و safety burden برای مرحلهٔ فعلی نامتناسب‌اند. |
| مستقیم برای مصرف‌کننده | ۲٫۲۰ | acquisition، trust، response liability و نبود تیم درمان مالک، thesis Care Loop را تضعیف می‌کند. |

### ۵.۳ ICP پیشنهادی

#### ویژگی‌های مثبت

- مالک/مدیر یا medical director در دسترس؛
- یک champion بالینی و یک champion عملیاتی؛
- ۲ تا حدود ۱۵ ارائه‌دهنده یا تیم معادل آن؛
- یک تا چند location محدود؛
- حجم تکرارشوندهٔ بیمار بالغ مزمن؛
- پیگیری فعلی با تماس، پیام‌رسان، دفتر، spreadsheet یا حافظهٔ کارکنان؛
- از دست‌رفتن follow-up، refill، آزمایش، تماس یا بازبینی داده قابل مشاهده؛
- یک نقش واقعی برای triage و پیگیری؛
- دادهٔ قابل export یا migration؛
- آمادگی برای ثبت baseline و شرکت در usability/pilot؛
- تمایل به استفاده از یک محصول مشترک برای پرونده، عملیات و مالی؛
- پذیرش اینکه CDS در ابتدا shadow و suggestion-only است.

#### disqualifierها

مرکز برای پایلوت اولیه مناسب نیست اگر:

- هیچ owner مشخصی برای صف پیگیری ندارد؛
- انتظار دارد نرم‌افزار جای نیروی پاسخ‌گو را بدون تغییر workflow بگیرد؛
- فقط یک «اپ بیمار» یا chatbot می‌خواهد؛
- از ابتدا ۲۴/۷ monitoring یا emergency response می‌خواهد؛
- درمان، titration یا diagnosis خودکار مطالبه می‌کند؛
- به custom fork وابسته است و configuration مشترک را نمی‌پذیرد؛
- دسترسی به داده، رضایت، audit یا migration کنترل‌شده ندارد؛
- willingness برای مشاهدهٔ workflow و اندازه‌گیری بار کار ندارد؛
- مسئلهٔ اصلی‌اش فقط نوبت‌دهی یا فقط حسابداری است؛
- buyer، budget یا معیار موفقیت نامشخص است.

---

## ۶. انتخاب wedge بالینی و عملیاتی

### ۶.۱ توصیه

پایلوت اولیه باید روی **پیگیری بزرگسالان مبتلا به فشارخون و دیابت نوع ۲ در کلینیک‌های قلب، غدد، داخلی یا مراکز cardiometabolic** متمرکز شود، ولی محصول از ابتدا نباید ادعا کند یک program کامل disease management را تحویل داده است.

شروع مناسب، workflowهای پرتکرار و کم‌ابهام‌تر است:

1. پیگیری بعد از ویزیت یا اقدام بالینی؛
2. آزمایش یا نوبت overdue؛
3. refill / renewal request؛
4. ارسال محدود فشارخون یا دادهٔ self-report؛
5. verification؛
6. review تیم؛
7. پاسخ قابل مشاهده؛
8. closure با evidence و next step.

### ۶.۲ چرا فشارخون و دیابت، نه HF monitoring کامل

- فشارخون و دیابت در محصول و پژوهش قبلی context روشن‌تری دارند؛
- home measurement و care gap قابل تعریف‌اند؛
- می‌توان scope را به ساعات کاری و escalation contract محدود کرد؛
- با پرونده، دارو، آزمایش، نوبت و follow-up موجود هم‌افزایی دارند؛
- مسیر expansion به ASCVD risk و cardiometabolic care وجود دارد.

نارسایی قلبی برای آینده مهم است، ولی شروع با HF monitoring کامل این ریسک‌ها را دارد:

- احتمال انتظار پاسخ فوری یا ۲۴/۷؛
- بار هشدار و escalation بیشتر؛
- نیاز بالاتر به device، protocol، staffing و integration؛
- مرز حساس‌تر میان monitoring و treatment action؛
- نیاز شدیدتر به evidence package و clinical governance.

بنابراین:

```text
Build first:
HTN / T2D follow-up loops and care gaps

Shadow later:
ASCVD risk and structured recommendations

Defer until operating model proven:
HF high-acuity monitoring, automated titration,
24/7 triage, device-heavy pathways
```

---

## ۷. مزیت رقابتی و moat

### ۷.۱ thesis مزیت

حلقه نباید در breadth با هر practice-management suite یا digital-health platform رقابت کند.

مزیت هدف:

```text
Clinic-native record and operations
+ local accounting and revenue-cycle truth
+ migration and reconciliation discipline
+ closed-loop chronic-care operations
+ patient/caregiver action layer
+ governed, reproducible clinical programs
+ configurable multi-tenant deployment
```

### ۷.۲ moatهای قابل‌ساخت

#### ۱. Care-loop event graph

اگر هر loop از detection تا action، response، review، outcome و reopen به‌صورت ساختاریافته ثبت شود، حلقه یک دیتاست عملیاتی طولی می‌سازد که نشان می‌دهد:

- چه چیزی واقعاً پیگیری شد؛
- چه کسی پاسخ داد؛
- چه مدت طول کشید؛
- چه evidenceای closure را توجیه کرد؛
- کدام workflowها شکست خوردند؛
- کدام patient actionها به review و اقدام منجر شدند.

این moat از «تعداد داده» نمی‌آید؛ از کیفیت provenance و اتصال data → work → outcome می‌آید.

#### ۲. Migration and trust moat

ابزارهای ETL، ledger، replay، reconciliation، sign-off، backup و release manifest می‌توانند onboarding ایمن و قابل‌اعتماد را به بخشی از محصول تبدیل کنند. بسیاری از رقابت‌ها در روز demo رخ نمی‌دهد؛ در روز migration و cutover رخ می‌دهد.

#### ۳. Local workflow and finance moat

پشتیبانی واقعی از تاریخ، زبان، پول، بیمه، فاکتور، شیفت، حقوق و workflow کلینیک محلی، در صورتی مزیت است که configuration-driven و بدون fork باشد.

#### ۴. Governance moat

Rule version، evidence package، fact snapshot، shadow deployment، alert budget و audit تصمیم می‌توانند اعتماد سازمانی بسازند. «AI» به‌تنهایی moat نیست؛ governance و reproducibility می‌تواند باشد.

#### ۵. Implementation learning moat

playbook تکرارپذیر برای:

- workflow mapping؛
- role/SLA design؛
- data migration؛
- staff onboarding؛
- patient onboarding؛
- workload measurement؛
- pilot evaluation؛
- adaptation بدون شکستن core؛

در مرحلهٔ اول از خود الگوریتم ارزشمندتر است.

### ۷.۳ چیزهایی که moat نیستند

- dashboard؛
- chatbot؛
- AI summary؛
- reminder؛
- ذخیرهٔ vital؛
- «all-in-one» بدون integration واقعی؛
- تعداد feature؛
- claim بهبود outcome بدون trial؛
- proprietary threshold بدون evidence governance؛
- lock-in داده.

بازار practice-management اکنون booking، records، finance، reports، multiple locations، patient app، secure messaging، billing و onboarding را baseline معرفی می‌کند؛ برای نمونه صفحات رسمی [Cliniko](https://www.cliniko.com/features/) و [Jane](https://jane.app/features) این breadth را نمایش می‌دهند. پلتفرم‌های chronic-care مانند [Cadence](https://www.cadence.care/) نیز monitoring را به care team، protocol و workflow متصل می‌کنند. بنابراین تمایز حلقه باید در **عمق operating model و closure قابل‌اثبات** باشد، نه در داشتن منوهای مشابه.

---

## ۸. Product Pillars

### Pillar 1 — Trustworthy Clinic Core

شامل:

- patient identity و enrollment؛
- پرونده و safety context؛
- appointment / encounter / prescription؛
- accounting و revenue cycle؛
- audit و access boundary؛
- migration، reconciliation، backup و recovery؛
- tenant-scoped configuration.

**Outcome:** کلینیک بتواند به داده، تاریخچه، مبلغ و provenance اعتماد کند.

### Pillar 2 — Care Loop Operations

شامل:

- CareLoop؛
- owner، team و queue؛
- SLA پاسخ و حل؛
- task/action/evidence؛
- attempt history؛
- waiting state؛
- escalation؛
- closure code و outcome؛
- reopen؛
- staff inbox و capacity view.

**Outcome:** کار مهم گم نشود و مسئولیت قابل مشاهده باشد.

### Pillar 3 — Patient & Caregiver Action Layer

شامل:

- Portal Identity؛
- صفحهٔ Today؛
- patient tasks؛
- measurements/submissions؛
- status «دریافت شد / دیده شد / پاسخ داده شد»؛
- structured request threads؛
- appointment/refill؛
- caregiver grant؛
- accessible onboarding و recovery؛
- non-digital fallback.

**Outcome:** بیمار بداند امروز چه کند و پس از اقدام چه اتفاقی می‌افتد.

### Pillar 4 — Governed Clinical Programs & CDS

شامل:

- ClinicalProgram / ProgramVersion؛
- EvidencePackage؛
- RuleVersion؛
- measurement protocol؛
- eligibility/exclusion/conflict؛
- RecommendationInstance؛
- fact provenance؛
- shadow/pilot/active lifecycle؛
- alert budget؛
- validation و monitoring.

**Outcome:** پیشنهاد قابل توضیح، قابل بازسازی و تحت کنترل انسان باشد.

### Pillar 5 — Repeatable Multi-tenant Implementation

شامل:

- Organization / Location / Department؛
- membership و role؛
- capability packs؛
- templateهای onboarding؛
- configuration diff؛
- migration workbench؛
- rollout/rollback؛
- cross-tenant operational analytics بدون نشت داده؛
- support و implementation telemetry.

**Outcome:** کلینیک دوم و سوم با هزینه و زمان کمتر از اول راه‌اندازی شوند، بدون fork.

---

## ۹. Dependency graph

```text
Security / identity / audit / tenant isolation
                │
                ├── Patient identity and enrollment
                ├── Organization / membership / roles
                ├── Event model and immutable provenance
                └── Migration and reconciliation foundation
                              │
                              ▼
                    Care Loop Operations
             owner + queue + SLA + evidence + closure
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
        Staff inbox      Patient actions   Program metrics
              │               │                │
              │        Portal identity          │
              │        Caregiver grants         │
              │        Request routing          │
              └───────────────┬────────────────┘
                              ▼
               Governed Clinical Programs / CDS
       evidence + rule version + fact snapshot + shadow mode
                              │
                              ▼
             Repeatable multi-clinic implementation
     capability packs + onboarding + migration + analytics
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
       Device integration  Multi-location   Advanced finance
       higher-acuity RPM   inventory        payer/claims
```

### قواعد dependency

- Portal messaging قبل از queue و owner ساخته نشود.
- CDS active قبل از rule version، fact provenance، shadow test و alert budget فعال نشود.
- device ingestion قبل از verification، review capacity و escalation contract ساخته نشود.
- multi-location sales قبل از organization/membership/capability isolation انجام نشود.
- advanced claims قبل از invoice/payment/refund state machine عمومی‌تر ساخته نشود.
- analytics outcome قبل از event completeness و closure semantics عرضه نشود.

---

## ۱۰. Roadmap مبتنی بر outcome

این roadmap تاریخ‌محور نیست. عبور هر phase وابسته به evidence gate است.

### Phase 0 — Problem and operating-model validation

**ساخت اصلی:** حداقل prototype؛ نه platform expansion.

**کارها:**

- مشاهدهٔ workflow در ۳ تا ۵ مرکز؛
- مصاحبهٔ پزشک، پرستار/پیگیر، پذیرش، مدیر و مسئول مالی؛
- mapping ده نمونهٔ واقعی پیگیری از شروع تا پایان؛
- time-and-motion ساده؛
- baseline dropped follow-up و پاسخ؛
- تعریف owner و SLA واقعی؛
- تست willingness-to-change و willingness-to-pay؛
- ارزیابی data export و migration.

**Outcome gate:** مسئله، buyer، workflow owner و baseline قابل‌اندازه‌گیری تأیید شوند.

### Phase 1 — Staff-only Care Loop MVP

**ساخت:**

- CareLoop domain؛
- owner/queue/SLA؛
- evidence/closure/reopen؛
- staff inbox؛
- event telemetry؛
- workflow template برای HTN/T2D follow-up؛
- بدون portal کامل؛
- بدون CDS active.

**Outcome gate:**

- کار گم‌شده کاهش یابد؛
- درصد loopهای ownerدار بالا باشد؛
- زمان پاسخ قابل اندازه‌گیری شود؛
- closure بدون evidence ممکن نباشد؛
- بار مستندسازی قابل‌قبول بماند؛
- کاربران workflow را خارج از سیستم دور نزنند.

### Phase 2 — Patient action and response visibility

**ساخت:**

- portal identity و recovery؛
- Today؛
- محدود به measurement، refill، appointment و structured request؛
- patient acknowledgement؛
- caregiver grant؛
- status پاسخ؛
- accessible onboarding و fallback.

**Outcome gate:**

- بیمار وظیفه را بدون کمک غیرمنطقی انجام دهد؛
- submission بدون review رها نشود؛
- افزایش کانال بیمار باعث backlog کنترل‌نشده نشود؛
- caregiver با هویت مستقل استفاده کند؛
- trust و comprehension مناسب باشد.

### Phase 3 — Governed program and shadow CDS

**ساخت:**

- HTN/T2D Clinical Program v1؛
- evidence package؛
- immutable rule version؛
- RecommendationInstance؛
- shadow mode؛
- false-positive review؛
- alert budget؛
- accept/dismiss/defer reason؛
- هیچ اقدام درمانی خودکار.

**Outcome gate:**

- recommendation تاریخی قابل بازسازی باشد؛
- missing/stale data fail closed شود؛
- fire rate و burden در محدودهٔ پذیرفتنی باشد؛
- پزشک explanation را بفهمد؛
- هیچ serious safety issue رخ ندهد؛
- فقط ruleهای clinically signed off به pilot برسند.

### Phase 4 — Repeatable clinic onboarding

**ساخت:**

- organization/location/membership؛
- capability packs؛
- onboarding checklist؛
- migration workbench؛
- configuration templates؛
- implementation dashboard؛
- support telemetry؛
- contract and pricing experiments.

**Outcome gate:**

- کلینیک دوم و سوم سریع‌تر و با exception کمتر راه‌اندازی شوند؛
- customization بدون fork انجام شود؛
- time-to-first-value کاهش یابد؛
- support burden به ازای tenant کنترل شود؛
- retention و expansion signal مشاهده شود.

### Phase 5 — Selective expansion

فقط پس از شواهد phases قبل:

- device integrations؛
- ASCVD program؛
- HF transition/follow-up محدود؛
- multi-location operations؛
- advanced inventory؛
- payer/claims؛
- API ecosystem؛
- predictive risk model با validation مستقل.

---

## ۱۱. North-star و metric hierarchy

### North-star موقت

```text
Evidence-backed Care Loops closed on time
per active enrolled patient
without unsafe closure or hidden staff burden
```

این metric عمداً سه شرط دارد:

1. closure واقعی، نه تغییر status؛
2. زمان و evidence؛
3. guardrail ایمنی و بار کاری.

### ۱۱.۱ Workflow metrics

- درصد loop دارای owner؛
- درصد loop دارای SLA؛
- first-response time؛
- resolution time؛
- overdue rate؛
- unowned rate؛
- waiting-on-patient / waiting-on-team duration؛
- attempt count؛
- closure evidence completeness؛
- reopen rate؛
- cancellation reason؛
- work خارج از سیستم.

### ۱۱.۲ Patient/caregiver metrics

- activation و recovery success؛
- task completion؛
- submission completion؛
- time from submission to acknowledgement/review/response؛
- comprehension task success؛
- abandonment point؛
- caregiver invitation/accept/revoke؛
- credential-sharing signal؛
- accessibility failure؛
- non-digital fallback use.

### ۱۱.۳ Staff and capacity metrics

- زمان median برای triage، review و closure؛
- loop به‌ازای role/FTE/day؛
- backlog age؛
- after-hours activity؛
- duplicate documentation؛
- interruption count؛
- perceived workload؛
- staff turnover/absence context؛
- handoff failure؛
- inbox burden.

### ۱۱.۴ Safety and CDS metrics

- unreviewed abnormal submission؛
- missed escalation؛
- inappropriate escalation؛
- unsafe closure؛
- stale/missing-data block؛
- recommendation fire rate؛
- repeated recommendation burden؛
- accept/modify/dismiss/defer؛
- dismiss reason؛
- time to action؛
- false-positive chart review؛
- near miss / incident؛
- rule rollback.

### ۱۱.۵ Business and implementation metrics

- time-to-contract؛
- time-to-clean-data؛
- migration exception rate؛
- time-to-first-live-loop؛
- training minutes by role؛
- implementation hours per tenant؛
- support minutes per active user؛
- paid pilot conversion؛
- gross retention؛
- expansion to second module/location؛
- contribution margin per clinic و per active patient؛
- receivable/collection impact فقط در صورت causal design مناسب.

---

## ۱۲. Research gates

Thresholdهای زیر **پیشنهاد اولیه برای تصمیم‌گیری** هستند، نه استاندارد علمی و نه حقیقت بازار. پیش از استفاده در قرارداد یا claim باید با pilot design بازنگری شوند.

### Gate A — Problem evidence

برای ادامهٔ build:

- حداقل سه مرکز مستقل همان مسئله را با مثال واقعی نشان دهند؛
- حداقل دو نقش در هر مرکز pain را تأیید کنند؛
- حداقل ده case واقعی end-to-end map شود؛
- baseline رهاشدگی، تأخیر یا دوباره‌کاری قابل ثبت باشد؛
- buyer و budget owner مشخص باشد.

**No-go:** مسئله فقط در سطح نظر یا علاقه به feature باشد.

### Gate B — Workflow ownership

- owner هر loop قابل نام‌گذاری باشد؛
- ساعات پاسخ و escalation روشن باشد؛
- مدیر ظرفیت staff را تخصیص دهد؛
- workflow خارج از ساعات پوشش به بیمار واضح باشد؛
- closure definition مورد توافق تیم باشد.

**No-go:** همهٔ کارها «برای پزشک» باشد ولی زمان/ظرفیت پزشک تخصیص نیابد.

### Gate C — Prototype usability

پیشنهاد اولیه:

- حداقل ۸۰٪ taskهای اصلی بدون کمک کامل شوند؛
- هیچ critical safety or privacy error رخ ندهد؛
- کاربر بتواند وضعیت و next step را توضیح دهد؛
- سالمند/کم‌سواد و caregiver جداگانه تست شوند؛
- keyboard، mobile، RTL، text scaling و error recovery آزموده شوند.

**No-go:** موفقیت وابسته به آموزش شفاهی مداوم یا credential sharing باشد.

### Gate D — Operational feasibility pilot

پیشنهاد اولیه:

- بیش از ۹۰٪ loopها owner داشته باشند؛
- کمتر از ۵٪ loop بدون تعیین تکلیف یا خارج از دید بمانند؛
- حداقل ۸۰٪ first responseها در SLA توافق‌شده باشند؛
- closure evidence در بیش از ۹۰٪ loopهای بسته کامل باشد؛
- هیچ serious safety incident منتسب به workflow رخ ندهد؛
- افزایش after-hours staff activity بیش از ۱۵٪ نباشد؛
- زمان افزودهٔ مستندسازی median از دو دقیقه به‌ازای loop فراتر نرود، مگر value واضح و پذیرفته‌شده ثبت شود.

این اعداد باید بر اساس complexity هر loop stratify شوند.

### Gate E — Patient channel feasibility

- حداقل ۶۰٪ بیماران دعوت‌شده یک اقدام معنادار کامل کنند؛
- بیش از ۹۵٪ submissionهای کامل status دریافت/بازبینی روشن داشته باشند؛
- zero unowned clinical request؛
- abandonment و failure بر اساس سن، سواد، device و caregiver stratify شود؛
- مسیر تلفنی/حضوری برای افراد نامناسب دیجیتال حفظ شود.

**No-go:** engagement بالا ولی backlog تیم یا تأخیر پاسخ غیرقابل‌قبول باشد.

### Gate F — CDS shadow safety

- ۱۰۰٪ recommendationها به rule version و fact snapshot متصل باشند؛
- unknown/missing critical data باعث suppression یا explicit uncertainty شود؛
- false-positive و burden به‌صورت chart review نمونه‌برداری شود؛
- rule بدون sign-off و test manifest فعال نشود؛
- serious unsafe recommendation برابر stop و root-cause review باشد.

### Gate G — Repeatability and economics

پیشنهاد اولیه:

- حداقل دو کلینیک پس از pilot نخست بدون fork راه‌اندازی شوند؛
- زمان implementation کلینیک بعدی کاهش یابد؛
- migration exception و support burden نزولی باشد؛
- حداقل سه buyer از پنج buyer واجد شرایط برای paid pilot یا قرارداد مشروط آماده باشند؛
- هزینهٔ delivery و support در مدل قیمت قابل‌پوشش باشد؛
- value به بازیگری برسد که پرداخت می‌کند، یا contract mechanism آن را هم‌راستا کند.

**No-go:** هر tenant به توسعهٔ اختصاصی، staffing اختصاصی یا integration غیرقابل‌تکرار نیاز داشته باشد.

---

## ۱۳. Build / Defer / Kill criteria

### Build

یک قابلیت build می‌شود اگر:

- به pain پرتکرار ICP متصل باشد؛
- owner و workflow واقعی داشته باشد؛
- value و guardrail قابل‌اندازه‌گیری باشد؛
- با معماری مشترک و capability configuration سازگار باشد؛
- safety boundary روشن داشته باشد؛
- بدون claim اثبات‌نشده قابل عرضه باشد؛
- dependencyهایش آماده باشند؛
- دادهٔ لازم با consent و provenance قابل دریافت باشد؛
- بار عملیاتی قابل مشاهده و قابل قیمت‌گذاری باشد.

### Defer

قابلیت defer می‌شود اگر:

- ارزش دارد ولی prerequisite آماده نیست؛
- به integration خارجی ناپایدار وابسته است؛
- نیازمند ۲۴/۷ staffing است؛
- شواهد بالینی یا owner rule ناقص است؛
- frequency پایین و complexity بالا دارد؛
- فقط برای یک مشتری نیاز است و abstraction مشترک ندارد؛
- هنوز workflow دستی استاندارد نشده است؛
- economics یا payer مشخص نیست؛
- privacy/regulatory decision باز دارد.

### Kill

قابلیت یا segment kill می‌شود اگر:

- درد واقعی یا willingness-to-change تکرار نمی‌شود؛
- buyer حاضر به پرداخت برای outcome موردنظر نیست؛
- هیچ role مسئول نیست؛
- محصول بار staff را افزایش می‌دهد و value متناسب ایجاد نمی‌کند؛
- benefit فقط با claim غیرقابل‌آزمون توجیه می‌شود؛
- workflow ایمن بدون درمان خودکار یا liability نامتناسب ممکن نیست؛
- نیازمند credential sharing یا کنترل ضعیف PHI است؛
- custom fork شرط فروش است؛
- داده برای سنجش موفقیت در دسترس نیست؛
- پس از دو iteration پایلوت، adoption و fidelity پایدار نمی‌شود؛
- serious safety issue بدون remediation قابل‌قبول رخ می‌دهد.

---

## ۱۴. تصمیم‌های صریح این دور

### Build now

- CareLoop domain و closure contract؛
- owner/team/queue/SLA؛
- staff inbox و workload telemetry؛
- HTN/T2D follow-up workflow templates؛
- event model برای detection → closure؛
- portal identity foundation فقط در حد dependency طراحی؛
- research instrumentation؛
- onboarding و workflow mapping playbook.

### Build next, only after staff-loop gate

- Patient Today؛
- limited measurement submission؛
- refill/appointment/structured request؛
- response status؛
- caregiver grant؛
- accessible onboarding؛
- Clinical Program package و shadow CDS.

### Defer

- free-form chat؛
- broad patient social/community features؛
- device marketplace؛
- HF 24/7 monitoring؛
- automated titration؛
- predictive AI risk scoring؛
- full ERP / GL / AP؛
- broad inventory lot/expiry برای همهٔ tenants؛
- hospital-scale integrations؛
- payer population-health contract؛
- autonomous chatbot for medical advice.

### Kill as positioning

- «AI-first clinic»؛
- «همه‌چیز برای همهٔ مراکز»؛
- «اپ ثبت فشار و قند»؛
- «dashboard بهتر»؛
- «کاهش قطعی بستری/هزینه» پیش از داده؛
- «جایگزینی تیم درمان»؛
- «سیستم ERP کامل سلامت» در مرحلهٔ اول.

---

## ۱۵. GTM hypothesis

### Buyer

خریدار اقتصادی اولیه:

- clinic owner؛
- medical director؛
- مدیر اجرایی/عملیات؛
- در مراکز بزرگ‌تر، مدیر مالی به‌عنوان co-buyer.

### Champion

- پزشک علاقه‌مند به care continuity؛
- پرستار یا نقش مسئول follow-up؛
- مدیر عملیات که dropped work و fragmentation را می‌بیند.

### Land motion

```text
Migration / clinic core trust
→ staff Care Loop pilot
→ patient action layer
→ governed clinical program
→ multi-location / advanced finance expansion
```

### پیام فروش آزمایشی

> حلقه کمک می‌کند پیگیری بیماران مزمن از تماس و حافظهٔ افراد به یک جریان ownerدار، زمان‌دار و قابل‌اثبات تبدیل شود؛ بدون جداکردن پرونده، عملیات و مالی کلینیک.

### چیزهایی که در فروش ممنوع‌اند

- وعدهٔ outcome بالینی قطعی؛
- اعلام ROI بدون baseline و causal design؛
- معرفی CDS به‌عنوان تشخیص یا درمان خودکار؛
- پنهان‌کردن نیاز به staff و workflow change؛
- استفاده از آمار vendor رقبا به‌عنوان benchmark مستقل؛
- فروش capability قبل از آماده‌بودن operational support آن.

---

## ۱۶. research backlog قبل از commitment اجرایی

### Discovery کلینیک

- ۵ مصاحبه owner/manager؛
- ۵ مصاحبه پزشک؛
- ۵ مصاحبه nurse/follow-up/front desk؛
- ۳ مشاهدهٔ نیم‌روزه workflow؛
- ۳۰ case trace از detection تا outcome؛
- willingness-to-pay interview با price framing؛
- بررسی contract و data-export واقعی.

### Patient/caregiver

- ۸ بیمار دارای HTN/T2D با تنوع سن و سواد؛
- ۴ caregiver؛
- task-based usability برای Today، submission، status و request؛
- آزمون login/recovery؛
- آزمون زبان، trust و escalation comprehension؛
- سنجش fallback preference.

### Clinical governance

- انتخاب دقیق HTN/T2D scope؛
- evidence appraisal rule-by-rule؛
- owner/reviewer؛
- measurement protocol؛
- exclusion و multimorbidity conflict؛
- shadow dataset؛
- alert budget؛
- rollback criteria.

### Economics

- time-and-motion هر نقش؛
- staffing model؛
- cost per enrolled patient؛
- support cost per tenant؛
- implementation cost؛
- collection/revenue hypotheses؛
- pricing interview؛
- sensitivity analysis برای حجم و churn.

### Market

- demo ساختاریافتهٔ ۳ practice-management platform؛
- demo ساختاریافتهٔ ۲ chronic-care/RPM platform؛
- teardown onboarding و migration؛
- مصاحبه با ۵ خریدار سابق نرم‌افزار کلینیک؛
- تحلیل procurement و قرارداد داده؛
- mapping رقبای ایرانی فراتر از صفحات عمومی.

---

## ۱۷. ریسک‌های راهبرد

| ریسک | نشانهٔ زودهنگام | پاسخ |
|---|---|---|
| محصول به work generator تبدیل شود | backlog و after-hours بالا | scope patient channel، capacity guard و SLA admission control |
| پزشک owner اسمی باشد | taskها منتظر پزشک بمانند | role delegation، protocol و protected review time |
| کلینیک Care Loop نمی‌خواهد؛ فقط software می‌خواهد | workflow change رد می‌شود | disqualify یا فروش Core بدون claim chronic-care |
| بیمار portal را رها کند | activation بدون action | onboarding، caregiver، low-friction tasks، human feedback |
| CDS burden ایجاد کند | fire/dismiss/repeat بالا | shadow، suppression، tiering، rule retirement |
| هر tenant fork بخواهد | code branch برای هر مرکز | capability/policy model و kill customization |
| اقتصاد خدمت منفی باشد | support/staffing از قیمت بیشتر | scope، pricing، automation غیرکلینیکی و segment refinement |
| دادهٔ outcome ناقص باشد | closureهای بدون evidence | schema gate و metric completeness |
| claim زودهنگام | فروش از evidence جلو بزند | claim registry و review اجباری marketing |
| بیمار high-risk اشتباه وارد scope شود | escalation ambiguity | inclusion/exclusion، safety message و referral boundary |

---

## ۱۸. تصمیم‌های باز

این موارد هنوز بسته نشده‌اند:

1. اولین specialty دقیق: غدد، قلب، داخلی یا مرکز ترکیبی؛
2. نقش اصلی delivery: پرستار، care navigator یا پذیرش آموزش‌دیده؛
3. ساعات و SLA واقع‌بینانه؛
4. مدل قیمت: per clinic، per active patient، module یا hybrid؛
5. اینکه Core به‌تنهایی فروخته شود یا فقط همراه Care Loop؛
6. minimum panel size اقتصادی؛
7. حداقل/حداکثر complexity هر loop؛
8. سیاست non-digital patient؛
9. مرز messaging و clinical advice؛
10. مدل liability و escalation؛
11. data retention و export contract؛
12. برنامهٔ فارسی‌سازی evidence content و review حقوقی؛
13. قابلیت offline/low-connectivity موردنیاز؛
14. مالکیت implementation playbook در تیم؛
15. معیار دقیق توقف pilot پس از safety event.

---

## ۱۹. نامعلوم‌ها و محدودیت‌های پژوهش

- هیچ مصاحبه یا مشاهدهٔ میدانی در این دور انجام نشده است.
- scorecard و thresholdها فرضیه‌اند، نه دادهٔ بازار.
- شواهد digital chronic care ناهمگون‌اند و context ایران را مستقیماً ارزیابی نمی‌کنند.
- Consensus به‌دلیل مصرف سهمیهٔ ماهانه قابل استفاده نبود؛ replication پس از ۱ اوت ۲۰۲۶ باقی است.
- Scholar Gateway همهٔ ناشران را پوشش نمی‌دهد و summary باید در تصمیم بالینی با متن اصلی کنترل شود.
- صفحات vendor فقط capability و positioning را نشان می‌دهند؛ اثربخشی مستقل را ثابت نمی‌کنند.
- willingness-to-pay، procurement، compliance و economics محلی هنوز اندازه‌گیری نشده‌اند.
- قابلیت‌های runtime شاخه با پایلوت واقعی برابر نیستند.
- هیچ claim بالینی، اقتصادی یا رقابتی از این سند مجاز نمی‌شود.

---

## ۲۰. تصمیم نهایی موقت

```text
Primary ICP hypothesis
= small-to-mid outpatient specialty / multispecialty clinics
  with adult cardiometabolic chronic panels
  and an accountable follow-up role

Initial wedge
= staff-owned HTN/T2D Care Loops
  + measurable SLA/closure
  + limited patient actions
  + shadow governed CDS

Primary promise
= no important follow-up left unowned,
  unseen or unprovably closed

Moat
= trusted migration + clinic-native operations
  + longitudinal care-loop event graph
  + local revenue-cycle truth
  + governed clinical programs
  + repeatable implementation

Do not lead with
= AI, dashboards, devices, full ERP,
  24/7 RPM or unproven outcome claims
```

این تصمیم فقط پس از عبور از Gate A و Gate B باید به PRD اجرایی و backlog تبدیل شود.

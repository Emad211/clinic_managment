# پروتکل Field Research دور پنجم حلقه

**تاریخ:** ۲۰۲۶-۰۷-۱۵  
**هدف:** اعتبارسنجی ICP، workflow، operating model، UX، safety، workload و willingness-to-pay پیش از PRD اجرایی  
**وضعیت:** پروتکل پیشنهادی؛ اجرای میدانی هنوز انجام نشده است.

---

## ۱. پرسش‌های اصلی

1. کدام نوع مرکز بیشترین درد قابل‌حل و بیشترین کنترل بر workflow پیگیری دارد؟
2. پیگیری بیماران HTN/T2D امروز دقیقاً چگونه انجام می‌شود؟
3. چه کارهایی گم، دیر یا دوباره انجام می‌شوند؟
4. owner واقعی هر مرحله کیست، نه owner روی کاغذ؟
5. patient submission یا request چگونه triage و پاسخ داده می‌شود؟
6. تیم چه ظرفیت و چه ساعات پوششی دارد؟
7. کلینیک برای چه outcomeای حاضر به تغییر workflow و پرداخت است؟
8. کدام بخش محصول موجود ارزش فوری می‌دهد و کدام بخش burden ایجاد می‌کند؟
9. چه safety boundaryهایی برای پایلوت لازم‌اند؟
10. آیا این workflow در چند مرکز قابل‌تکرار است یا به custom project تبدیل می‌شود؟

---

## ۲. فرضیه‌هایی که باید تلاش کنیم رد کنیم

پژوهش خوب فقط دنبال تأیید نیست. این فرضیه‌ها باید فعالانه falsify شوند:

- کلینیک کوچک/متوسط ICP بهتر از مطب یا درمانگاه بزرگ است.
- HTN/T2D follow-up درد پرتکرار و قابل‌پرداخت است.
- یک nurse/follow-up role می‌تواند owner اصلی باشد.
- Care Loop staff-only پیش از portal ارزش ایجاد می‌کند.
- کلینیک حاضر است SLA و closure contract را رسمی کند.
- patient response visibility adoption را بهتر می‌کند.
- migration/accounting integration مزیت خرید است.
- workflow بدون ۲۴/۷ response قابل طراحی است.
- product می‌تواند بدون custom fork در چند مرکز تکرار شود.
- buyer برای کاهش dropped work یا بهبود continuity budget دارد.

### evidence مخالف مهم

- کار واقعاً گم نمی‌شود و workaround فعلی کافی است؛
- هیچ نقش ظرفیت پیگیری ندارد؛
- پزشک delegation را نمی‌پذیرد؛
- بیماران کانال دیجیتال را نمی‌خواهند؛
- ارزش فقط با outcome بالینی بلندمدت قابل مشاهده است؛
- buyer فقط نوبت/حسابداری می‌خواهد؛
- هر specialty workflow کاملاً متفاوت دارد؛
- هزینهٔ implementation از willingness-to-pay بیشتر است؛
- risk/liability بدون ۲۴/۷ coverage قابل کنترل نیست.

---

## ۳. نمونهٔ هدف

### ۳.۱ مراکز

حداقل ۵ مرکز برای discovery اولیه:

| نوع | تعداد هدف | دلیل |
|---|---:|---|
| کلینیک غدد/دیابت | ۲ | fit مستقیم با T2D و care gaps |
| کلینیک قلب/فشارخون | ۱ | HTN/ASCVD و escalation متفاوت |
| داخلی/چندتخصصی کوچک تا متوسط | ۱ | آزمون generalizability |
| مطب تک‌پزشک یا درمانگاه بزرگ به‌عنوان contrast | ۱ | جلوگیری از confirmation bias |

تنوع مطلوب:

- یک تا چند location؛
- حجم بیمار متفاوت؛
- paper-heavy و software-heavy؛
- nurse/follow-up role موجود و ناموجود؛
- owner-led و manager-led؛
- بیمه و پرداخت متفاوت.

### ۳.۲ نقش‌ها

در هر مرکز، در صورت وجود:

- owner/medical director؛
- پزشک؛
- پرستار یا مسئول پیگیری؛
- پذیرش؛
- مدیر عملیات؛
- مسئول مالی؛
- IT/data contact.

هدف کلی discovery:

```text
5 owner/manager interviews
5 physician interviews
5 nurse/follow-up/front-desk interviews
3 workflow observation sessions
30 de-identified case traces
```

### ۳.۳ بیمار و همراه

برای prototype phase:

- حداقل ۸ بیمار HTN/T2D؛
- حداقل ۴ caregiver؛
- تنوع سنی، سواد سلامت و سواد دیجیتال؛
- حداقل ۳ فرد ۶۵ سال یا بیشتر؛
- حداقل ۲ فرد با نیاز accessibility؛
- افراد دارای smartphone قوی و افراد با device/connectivity محدود؛
- بیمار با همراه فعال و بدون همراه.

اعداد بالا برای discovery و usability هستند، نه inference آماری.

---

## ۴. اصول اخلاقی و privacy

- هیچ PHI در سند پژوهش GitHub ثبت نشود.
- caseها با شناسهٔ تحقیقاتی مستقل ثبت شوند.
- نام، تلفن، کد ملی، نشانی، شماره پرونده و تصویر خام حذف شوند.
- recording فقط با رضایت صریح و storage امن.
- participant بداند پژوهش جای مراقبت یا پاسخ پزشکی نیست.
- abnormal finding در جلسهٔ پژوهش طبق protocol از پیش‌تعیین‌شده handle شود.
- کارکنان بدانند هدف ارزیابی فردی یا performance management نیست.
- compensation یا هدیه، در صورت استفاده، شفاف و یکسان باشد.
- withdrawal بدون پیامد ممکن باشد.
- نقل‌قول عمومی فقط de-identified و با رضایت.
- دادهٔ تحقیق در repo عمومی یا PR comment قرار نگیرد.

---

## ۵. روش‌ها

```text
Context interview
+ direct observation
+ de-identified case tracing
+ artifact review
+ time-and-motion sample
+ prototype usability
+ concept/pricing interview
+ weekly synthesis
```

### ۵.۱ Context interview

هدف: فهم intent، درد، role، constraint و economics؛ نه گرفتن feature request.

### ۵.۲ Observation

هدف: تفاوت work-as-imagined و work-as-done.

### ۵.۳ Case tracing

یک پیگیری واقعی از trigger تا outcome دنبال می‌شود.

### ۵.۴ Artifact review

در صورت اجازه:

- دفتر تماس؛
- spreadsheet؛
- پیام template؛
- فرم؛
- screenshot de-identified؛
- appointment list؛
- task list؛
- report؛
- invoice/financial workflow metadata.

### ۵.۵ Time-and-motion

زمان نمونه‌ای فعالیت‌ها، interruption و handoff ثبت می‌شود. هدف productivity scoring فرد نیست.

### ۵.۶ Usability

task-based و think-aloud؛ نه demo هدایت‌شده.

### ۵.۷ Pricing interview

از سؤال «چقدر می‌پردازید؟» به‌تنهایی استفاده نشود. current spend، consequence، budget path، trade-off و paid pilot بررسی شود.

---

## ۶. راهنمای مصاحبه owner / medical director

### Context

1. چه نوع بیمارانی بیشترین follow-up بین ویزیت نیاز دارند؟
2. آخرین موردی را تعریف کنید که پیگیری دیر شد یا گم شد.
3. چه کسی متوجه شد؟ چه پیامدی داشت؟
4. چه کارهایی امروز به حافظهٔ افراد وابسته‌اند؟
5. چه چیزی در پایان روز نمی‌توانید با اطمینان ببینید؟

### Operating model

6. چه کسی owner پیگیری است؟
7. اگر آن فرد نباشد چه می‌شود؟
8. چه مواردی حتماً باید پزشک ببیند؟
9. چه مواردی می‌تواند protocol-driven باشد؟
10. ساعات پاسخ چیست و بیمار چه انتظاری دارد؟

### Business

11. این مسئله چه هزینه، اتلاف، شکایت یا ریسک ایجاد می‌کند؟
12. برای حل آن امروز چه هزینه‌ای می‌کنید؟
13. چه کسی قرارداد نرم‌افزار را تأیید می‌کند؟
14. موفقیت بعد از سه ماه چه شکلی دارد؟
15. چه چیزی باعث لغو قرارداد می‌شود؟
16. آیا برای پایلوت پولی با scope و metric روشن آماده‌اید؟

### Switching

17. چه داده‌ای باید migrate شود؟
18. بزرگ‌ترین ترس از تغییر سیستم چیست؟
19. downtime قابل‌قبول چقدر است؟
20. چه integrationهایی day-one هستند و کدام نه؟

### Falsification

21. چرا ممکن است حلقه برای مرکز شما مناسب نباشد؟
22. اگر فقط یک بخش را بخرید، آن بخش چیست؟
23. چه چیزی را هرگز به نرم‌افزار واگذار نمی‌کنید؟

---

## ۷. راهنمای مصاحبه پزشک

1. آخرین follow-up پیچیده را قدم‌به‌قدم توضیح دهید.
2. چه چیزی باید قبل از رسیدن به شما triage شود؟
3. چه داده‌ای را قابل اعتماد می‌دانید؟
4. self-report چه زمانی باید verified شود؟
5. چه چیزی در inbox شما مزاحمت است؟
6. چه چیزی نباید notification شود؟
7. چه تصمیمی قابل delegation است و چه تصمیمی نیست؟
8. چگونه می‌فهمید recommendation از کجا آمده؟
9. چه explanationی برای اعتماد لازم است؟
10. چه missing dataای باید rule را متوقف کند؟
11. چه زمانی یک follow-up واقعاً بسته است؟
12. چه چیزی باید باعث reopen شود؟
13. چه شرایطی نیازمند escalation فوری است؟
14. چه scopeای را در ساعات کاری ایمن می‌دانید؟
15. چه چیزی در پایلوت باعث توقف فوری شما می‌شود؟

### Prompt ممنوع

- «آیا AI دوست دارید؟»
- «آیا dashboard مفید است؟»
- «آیا این feature خوب است؟»

به‌جای آن case و decision واقعی پرسیده شود.

---

## ۸. راهنمای مصاحبه nurse / follow-up / front desk

1. لیست کار امروزتان چگونه ساخته می‌شود؟
2. کدام کارها از تماس، پیام یا یادداشت می‌آیند؟
3. چگونه اولویت می‌دهید؟
4. چه زمانی نمی‌دانید باید چه کنید؟
5. برای گرفتن پاسخ پزشک چه می‌کنید؟
6. چند بار یک موضوع را دوباره ثبت می‌کنید؟
7. چه چیزی بعد از ساعت کاری باقی می‌ماند؟
8. بیمار چند بار برای status تماس می‌گیرد؟
9. چه نوع requestهایی پرتکرارند؟
10. کدام requestها باید ساختاریافته شوند؟
11. چه چیزی را می‌توانید طبق protocol انجام دهید؟
12. چه چیزی باید escalate شود؟
13. چه evidenceای برای closure لازم است؟
14. اگر system down باشد چه می‌کنید؟
15. اگر حجم submission دو برابر شود چه می‌شود؟
16. چه metricی را ناعادلانه می‌دانید؟
17. چه featureای workload را بدتر می‌کند؟

### مشاهدهٔ مهم

- تعداد tab/app؛
- copy/paste؛
- phone interruption؛
- waiting for doctor؛
- patient callback؛
- duplicate entry؛
- handwritten workaround؛
- shared credentials؛
- queue ownership؛
- end-of-day reconciliation.

---

## ۹. راهنمای مصاحبه مسئول مالی/عملیات

1. patient follow-up چگونه به appointment، service یا collection متصل می‌شود؟
2. چه چیزی از نظر مالی قابل مشاهده نیست؟
3. آیا no-show، unpaid item یا incomplete service به workflow clinical مرتبط است؟
4. کدام گزارش برای تصمیم روزانه لازم است؟
5. چه reconciliationای دستی است؟
6. چه داده‌ای باید immutable snapshot باشد؟
7. چه کسی به گزارش مالی دسترسی دارد؟
8. migration چه ریسک مبلغی دارد؟
9. آیا value مراقبتی به درآمد یا retention قابل اتصال است؟
10. چه claim اقتصادی را بدون داده نمی‌پذیرید؟
11. budget و contract path چیست؟
12. چه هزینهٔ implementation قابل‌قبول است؟

---

## ۱۰. راهنمای مصاحبه بیمار

### تجربهٔ واقعی

1. بعد از آخرین ویزیت چه کاری باید انجام می‌دادید؟
2. از کجا فهمیدید؟
3. اگر سؤال داشتید با چه کسی تماس گرفتید؟
4. از کجا فهمیدید پیام یا داده دیده شده؟
5. چه چیزی را فراموش کردید یا سخت بود؟
6. همراه شما چه کمکی می‌کند؟
7. آیا از رمز مشترک استفاده می‌کنید؟ چرا؟
8. چه چیزی باعث می‌شود به portal اعتماد نکنید؟
9. چه زمانی ترجیح می‌دهید تلفن بزنید؟
10. در شرایط فوری چه می‌کنید؟

### Concept test

سناریو نشان داده شود، نه feature list:

> امروز از شما خواسته شده فشار را طبق دستور ثبت کنید. پس از ارسال، وضعیت «دریافت شد» می‌بینید. تیم در ساعات اعلام‌شده آن را بررسی می‌کند و اگر نیاز باشد پاسخ می‌دهد.

سؤال‌ها:

- فکر می‌کنید الان چه اتفاقی افتاده؟
- آیا پزشک همین لحظه دیده است؟
- قدم بعد چیست؟
- اگر حالتان بد شد چه می‌کنید؟
- چه کسی باید status را ببیند؟

### عدم هدایت

به participant نگویید پاسخ صحیح چیست تا comprehension واقعی سنجیده شود.

---

## ۱۱. راهنمای مصاحبه caregiver

1. امروز چگونه به بیمار کمک می‌کنید؟
2. چه اطلاعاتی لازم دارید و چه اطلاعاتی نه؟
3. آیا با رمز بیمار وارد می‌شوید؟
4. بیمار چگونه رضایت می‌دهد؟
5. چه زمانی access باید منقضی یا لغو شود؟
6. آیا action شما باید از action بیمار قابل تشخیص باشد؟
7. چه notificationهایی لازم دارید؟
8. اگر چند caregiver وجود داشته باشد چه می‌شود؟
9. در conflict با بیمار چه باید کرد؟
10. چه چیزی privacy بیمار را نقض می‌کند؟

---

## ۱۲. Observation Guide

### شروع workflow

- trigger چیست؟
- چه کسی متوجه می‌شود؟
- trigger structured است یا شفاهی؟
- urgency چگونه تعیین می‌شود؟

### جریان

- چند handoff؟
- چند system؟
- چند بار patient contact؟
- چند بار wait؟
- owner در هر لحظه روشن است؟
- آیا duplicate work وجود دارد؟

### closure

- چه کسی می‌بندد؟
- با چه evidence؟
- آیا بیمار مطلع می‌شود؟
- next step ثبت می‌شود؟
- reopen چگونه رخ می‌دهد؟

### exceptions

- بیمار پاسخ ندهد؛
- پزشک در دسترس نباشد؛
- داده ناقص باشد؛
- abnormal value برسد؛
- request اشتباه route شود؛
- system unavailable باشد؛
- caregiver تماس بگیرد؛
- بدهی/بیمه مانع service شود.

---

## ۱۳. Case Trace Template

```yaml
case_id: R05-CASE-NNN
clinic_type: "..."
workflow_type: "post_visit|overdue_lab|refill|measurement|appointment|other"
trigger:
  event: "..."
  timestamp_relative: "T0"
  detected_by: "..."
patient_risk_scope: "low|moderate|excluded_from_pilot"
steps:
  - actor: "..."
    action: "..."
    channel: "..."
    elapsed_minutes: 0
    system: "..."
    handoff: "..."
    evidence: "..."
waits: []
workarounds: []
duplications: []
errors_or_near_misses: []
patient_contacts: 0
staff_minutes_estimate: 0
closure:
  closed: true
  owner: "..."
  evidence: "..."
  outcome: "..."
  next_step: "..."
  patient_informed: true
failure_points: []
researcher_notes: "PHI-free"
```

---

## ۱۴. Time-and-Motion Template

| timestamp relative | actor | activity | direct/indirect care | system/channel | interruption | wait | duration | duplicate? | note |
|---|---|---|---|---|---|---|---:|---|---|
| T+0 |  |  |  |  |  |  |  |  |  |

### دسته‌بندی activity

- detect؛
- search؛
- triage؛
- document؛
- contact patient؛
- contact clinician؛
- review؛
- decide؛
- schedule؛
- financial/admin؛
- wait؛
- rework؛
- close؛
- escalate.

---

## ۱۵. Artifact Inventory

| artifact | owner | purpose | frequency | PHI? | source of truth? | failure mode | migration relevance |
|---|---|---|---|---|---|---|---|
| دفتر تماس |  |  |  |  |  |  |  |
| spreadsheet |  |  |  |  |  |  |  |
| WhatsApp/message template |  |  |  |  |  |  |  |
| EHR task |  |  |  |  |  |  |  |
| paper form |  |  |  |  |  |  |  |

هیچ artifact خام دارای PHI در repo commit نشود.

---

## ۱۶. Prototype Test Plan

### Staff prototype

سناریوها:

1. پیگیری overdue lab؛
2. بیمار پاسخ نمی‌دهد؛
3. نیاز به doctor review؛
4. abnormal measurement محدود به scope؛
5. reassignment؛
6. closure با evidence؛
7. reopen؛
8. مشاهدهٔ workload/backlog.

### Patient prototype

1. ورود/recovery؛
2. فهم Today؛
3. submission؛
4. status؛
5. refill request؛
6. appointment request؛
7. emergency boundary؛
8. caregiver invitation/revoke.

### metricها

- completion؛
- error؛
- time-on-task؛
- hesitation؛
- help request؛
- comprehension؛
- trust؛
- perceived workload؛
- accessibility failure؛
- unsafe interpretation.

---

## ۱۷. Pricing and Purchase Interview

### current state

- نرم‌افزارهای فعلی؛
- هزینهٔ مستقیم؛
- staff time؛
- missed revenue یا rework؛
- switching event؛
- budget cycle.

### value framing

سه package concept بدون قیمت نهایی مقایسه شوند:

1. Clinic Core؛
2. Core + Care Loop؛
3. Core + Care Loop + Patient/Program.

### trade-off questions

- اگر فقط یک package را انتخاب کنید کدام؟
- چه metricی renewal را توجیه می‌کند؟
- چه implementation feeای منطقی/غیرمنطقی است؟
- per clinic یا per active patient کدام قابل‌فهم‌تر است؟
- چه چیزی باید در base باشد؟
- چه چیزی add-on است؟
- چه چیزی را competitor یا current workflow بهتر حل می‌کند؟

### evidence قوی خرید

- paid pilot؛
- budget owner حاضر؛
- timeline؛
- procurement steps؛
- data access؛
- staff allocation؛
- written success criteria.

LOI بدون budget/timeline evidence متوسط است، نه قطعی.

---

## ۱۸. Synthesis Framework

### ۱۸.۱ Weekly evidence wall

هر observation در یکی از این ستون‌ها:

```text
Pain
Current workaround
Owner
Trigger
Handoff
Failure
Safety
Patient need
Staff burden
Buyer/value
Data constraint
Counter-evidence
```

### ۱۸.۲ Pattern rule

یک pattern زمانی «تکرارشونده» ثبت شود که:

- در حداقل سه participant مستقل یا دو مرکز دیده شود؛ یا
- consequence بالا داشته باشد؛ یا
- با artifact/observation پشتیبانی شود.

### ۱۸.۳ Evidence card

```yaml
insight_id: INS-R05-NNN
statement: "..."
evidence:
  interviews: []
  observations: []
  cases: []
  artifacts: []
counter_evidence: []
segments: []
roles: []
frequency: "..."
severity: "..."
confidence: LOW|MEDIUM|HIGH
product_implication: "..."
research_next: "..."
```

---

## ۱۹. Decision Meeting

شرکت‌کنندگان:

- Product؛
- Clinical؛
- UX Research؛
- Engineering/Architecture؛
- Security/Privacy؛
- Implementation/Customer Success؛
- Finance/GTM.

### agenda

1. evidence و counter-evidence؛
2. segment score update؛
3. opportunity score update؛
4. operating model؛
5. safety/equity؛
6. economics؛
7. dependencies؛
8. decision.

### خروجی اجباری

```text
GO TO PRD
ITERATE DISCOVERY
NARROW SEGMENT
DEFER
KILL
```

بدون ثبت rationale و review date تصمیم معتبر نیست.

---

## ۲۰. Exit Criteria دور field research

Round 05 فقط زمانی برای PRD اجرایی کافی است که:

- ICP و contrast segment مقایسه شده باشند؛
- حداقل ۳۰ case trace وجود داشته باشد؛
- owner و SLA واقعی قابل تعریف باشند؛
- baseline workflow metric قابل ثبت باشد؛
- prototype critical error نداشته باشد؛
- patient/caregiver comprehension آزموده شده باشد؛
- staff capacity و workload تخمین زده شده باشد؛
- paid-pilot signal وجود داشته باشد؛
- safety boundary و stop rules توافق شده باشند؛
- dependency graph به backlog قابل آزمون تبدیل شده باشد؛
- counter-evidence مستند باشد.

اگر این شرایط برقرار نباشند، خروجی درست «پژوهش بیشتر» یا «kill/defer» است، نه PRD اجباری.

# دور دوم پژوهش عمیق محصول: حلقهٔ مراقبت، داشبورد بیمار و موتور پیشنهاد

**تاریخ:** ۱۵ ژوئیهٔ ۲۰۲۶  
**وضعیت:** سند پژوهشی و جهت‌دهنده؛ نه دستور درمان و نه ادعای outcome  
**دامنه:** بیماران مزمن با اولویت دیابت، فشارخون، بیماری قلبی و چندبیماری  
**دیدگاه‌های هم‌زمان:** پزشک، بیمار، همراه، پرستار، مدیر کلینیک، سرمایه‌گذار، مدیر محصول، طراح UX، مهندس و مسئول ایمنی

---

## ۱. جمع‌بندی اجرایی

تز دور اول این بود که «حلقه» نباید صرفاً پرونده، حسابداری، پورتال یا اپ پایش باشد؛ باید **سیستم‌عامل مراقبت پیوسته** باشد. دور دوم این تز را دقیق‌تر می‌کند:

> واحد واقعی ارزش در حلقه یک `Care Loop` است: مسئله‌ای که کشف می‌شود، به فرد مشخصی واگذار می‌شود، به اقدام بیمار و تیم تبدیل می‌شود، نتیجه‌اش دیده می‌شود و فقط با شواهد کافی بسته می‌شود.

داشتن داده، نمودار، reminder یا suggestion به‌تنهایی حلقه را نمی‌بندد. پژوهش‌های digital chronic care مرتباً نشان می‌دهند که مداخلات موفق، فناوری را با پاسخ انسانی، آموزش، coaching، workflow سازگار و مرور منظم داده ترکیب می‌کنند؛ فناوری مستقل نتایج نامتوازن دارد ([Mikkonen et al., 2022](https://doi.org/10.1111/jocn.16448)، [Kilfoy et al., 2024](https://doi.org/10.1111/jocn.17226)، [Samal et al., 2021](https://doi.org/10.1111/1475-6773.13860)).

بنابراین سه تصمیم محصولی این دور چنین‌اند:

1. **پیگیری از task list به Care Loop Engine ارتقا یابد.**
2. **داشبورد بیمار action-first باشد، نه feature-first یا chart-first.**
3. **موتور پیشنهاد یک سامانهٔ دانش نسخه‌دار، explainable، کم‌هشدار و human-in-the-loop باشد.**

---

## ۲. مسئله‌ای که باید حل کنیم

بیمار مزمن معمولاً با کمبود داده مواجه نیست؛ با شکاف‌های اجرایی مواجه است:

- نمی‌داند مهم‌ترین کار امروز چیست؛
- نمی‌داند نتیجه‌ای که ثبت کرده چه زمانی و توسط چه کسی دیده می‌شود؛
- چند توصیه از چند پزشک و بیماری با هم تعارض دارند؛
- درمان، آزمایش، دارو، بیمه و پیگیری در چند کانال جدا هستند؛
- در صورت عدم پاسخ یا عدم مراجعه، مسئول ادامهٔ پیگیری معلوم نیست؛
- «انجام شد» لزوماً به معنی حل مسئله نیست؛
- caregiver یا خانواده نقش واقعی دارند ولی دسترسی و مسئولیت‌شان مدل نشده است؛
- تیم درمان با alert، inbox و مستندسازی مضاعف فرسوده می‌شود.

از دید سرمایه‌گذار و مدیر کلینیک نیز مشکل فقط engagement نیست. اگر برنامه نتواند نشان دهد کدام بیماران به اقدام رسیدند، کدام حلقه‌ها در SLA بسته شدند و کجا کار متوقف شد، محصول قابل‌مدیریت و قابل‌مقیاس نیست.

---

## ۳. Care Loop دقیقاً چیست؟

### ۳.۱ تعریف پیشنهادی

یک Care Loop یک واحد زمان‌دار و قابل‌ممیزی از مراقبت است که این زنجیره را کامل می‌کند:

```text
Trigger
  → Triage
  → Care decision / Plan
  → Owner + Task
  → Patient / caregiver action
  → Data or response
  → Human review
  → Clinical / operational intervention
  → Outcome evidence
  → Closure, next review or reopen
```

نمونهٔ Trigger:

- فشارخون خانگی بسیار بالا یا روند رو به وخامت؛
- HbA1c عقب‌افتاده؛
- داروی در آستانهٔ اتمام؛
- عدم مراجعه؛
- افزایش وزن در بیمار قلبی؛
- پیشنهاد پذیرفته‌شدهٔ پزشک؛
- discharge یا نسخه‌ای که نیازمند کنترل بعدی است.

### ۳.۲ پنج عملکردی که حلقه باید پشتیبانی کند

ادبیات self-care سه عملکرد کلاسیک را متمایز می‌کند: maintenance، monitoring و management؛ بسیاری از ابزارها فقط دو مورد اول را پوشش می‌دهند ([Buck et al., 2020](https://doi.org/10.1002/nur.22073)). برای محصول عملیاتی دو لایهٔ دیگر لازم است:

1. **Maintenance:** رفتارهای روزمره، دارو، تغذیه، فعالیت و پیشگیری.
2. **Monitoring:** ثبت و مشاهدهٔ فشار، قند، وزن، علائم و آزمایش.
3. **Management:** تصمیم دربارهٔ پاسخ مناسب به تغییر یا علامت.
4. **Relational support:** پاسخ انسانی، coaching، آموزش و همراهی.
5. **System coordination:** مالکیت کار، زمان‌بندی، ارجاع، بیمه و بستن حلقه.

داشبوردی که فقط اندازه‌گیری را جمع کند، دو لایهٔ آخر را ندارد و نمی‌تواند Care OS باشد.

### ۳.۳ قرارداد بسته‌شدن حلقه

یک حلقه فقط وقتی `closed` می‌شود که تمام شرایط تعریف‌شدهٔ آن برقرار باشد:

- یک owner معتبر داشته باشد؛
- اقدام ضروری انجام یا با دلیل معتبر لغو شده باشد؛
- پاسخ یا دادهٔ مورد انتظار دریافت شده باشد؛
- در صورت نیاز، توسط فرد مجاز review شده باشد؛
- نتیجه یا closure code ثبت شده باشد؛
- evidence مورد نیاز قابل‌ارجاع باشد؛
- برنامهٔ بعدی، موعد بازبینی یا معیار reopen مشخص باشد؛
- بیمار یا caregiver در موارد لازم پیام را دریافت یا تصمیم را فهمیده باشد.

`status=done` در مدل فعلی کافی نیست.

---

## ۴. شکاف مدل فعلی Halqe

### ۴.۱ FollowupTask فعلی

مدل فعلی شامل موعد، متن، status، `assigned_to` متنی، call log و چند reference است. این مدل برای worklist اولیه مناسب است ولی برای عملیات مراقبت پیوسته کافی نیست.

کمبودها:

- شناسهٔ ساختاریافتهٔ owner و نقش او؛
- queue و team ownership؛
- SLA پاسخ و SLA حل؛
- severity/priority مستقل؛
- attempt history ساختاریافته؛
- وضعیت‌های waiting-on-patient / waiting-on-team / blocked؛
- escalation policy و escalation history؛
- required evidence؛
- closure code و outcome؛
- ارتباط مستقیم با CarePlan، Goal و Activity؛
- reopen reason؛
- acknowledgement بیمار؛
- کانال و receipt ارتباط.

### ۴.۲ SuggestionLog فعلی

`pending / accepted / dismissed` برای نمایش state اولیه مناسب است، اما یک suggestion ممکن است:

- suppress یا deduplicate شود؛
- snooze شود؛
- منقضی یا superseded شود؛
- به CarePlan یا Task تبدیل شود؛
- به دلیل contraindication متوقف شود؛
- پس از تغییر facts دوباره ارزیابی شود؛
- با override reason رد شود.

پذیرفتن suggestion نباید مساوی اجرای recommendation تلقی شود.

### ۴.۳ patient card و self-report فعلی

کارت عمومی فعلی minimum-necessary و امنیت‌محور است و self-report نیز token یک‌بارمصرف دارد. این‌ها سطح‌های مفیدی هستند، اما **داشبورد بیمار احراز هویت‌شده** نیستند.

فقدان‌های اصلی:

- حساب کاربری و session پایدار بیمار؛
- caregiver/proxy access؛
- consent و scope مدیریت‌شده؛
- inbox و messaging؛
- plan و goal؛
- taskهای بیمار؛
- آموزش contextual؛
- وضعیت بررسی داده؛
- توضیح «چه کسی و چه زمانی پاسخ می‌دهد»؛
- notification preferences؛
- دسترسی چندکلینیکی و چندمستاجری ایمن.

---

## ۵. مدل دامنهٔ هدف

### ۵.۱ موجودیت‌های اصلی

| موجودیت | مسئولیت |
|---|---|
| `CarePlan` | زمینهٔ مراقبت، بیماری‌ها، تیم، بازه و status |
| `CareGoal` | وضعیت مطلوب، target، زمان و معیار موفقیت |
| `CareLoop` | یک مسئله یا فرصت قابل‌بستن با trigger و outcome |
| `CareActivity` | اقدام برنامه‌ریزی‌شده در plan |
| `CareTask` | کار اجرایی با owner، queue، SLA و state machine |
| `PatientAction` | کار قابل‌فهم و قابل‌انجام برای بیمار یا همراه |
| `PatientResponse` | پاسخ، اندازه‌گیری، فرم یا acknowledgement |
| `ReviewDecision` | تصمیم انسانی دربارهٔ داده یا recommendation |
| `CommunicationRequest` | درخواست ارسال پیام/یادآوری/آموزش |
| `Communication` | رخداد واقعی ارسال/تحویل/خواندن/پاسخ |
| `OutcomeEvidence` | داده یا سند لازم برای اثبات نتیجه |
| `Escalation` | انتقال سطح، علت، گیرنده و زمان |
| `CaregiverAccess` | رابطه، scope، expiry و consent همراه |
| `KnowledgeRecommendation` | خروجی موتور دانش قبل از تبدیل به اقدام |

این مدل از مفاهیم استاندارد CarePlan، Goal، Task، CommunicationRequest، Consent و RelatedPerson الهام می‌گیرد، اما UI و API داخلی باید ساده و متناسب با عملیات کلینیک باقی بماند.

### ۵.۲ state machine پیشنهادی CareLoop

```text
detected
  → triaged
  → planned
  → active
  → awaiting_patient
  → awaiting_team
  → action_due
  → verification_due
  → closed

branch states:
  blocked
  escalated
  cancelled
  expired
  reopened
```

### ۵.۳ state machine پیشنهادی CareTask

```text
queued → assigned → accepted → in_progress
       → waiting_on_patient
       → waiting_on_team
       → completed
       → failed / cancelled
```

### ۵.۴ state machine پیشنهاد

```text
generated
  → suppressed / deduplicated
  → presented
  → accepted / dismissed / snoozed
  → converted_to_plan_or_task
  → completed / expired / superseded
```

تمام transitionها باید append-only event داشته باشند؛ projection جاری برای UI جدا باشد.

---

## ۶. چهار مثال از حلقهٔ حداقلی

### مثال A: فشارخون خانگی بالا

1. بیمار BP را ثبت می‌کند؛ مقدار ابتدا source و verification state دارد.
2. rule/triage سطح urgency را تعیین می‌کند، نه تشخیص نهایی.
3. CareLoop ساخته یا به loop فعال deduplicate می‌شود.
4. task برای queue مناسب با SLA تعیین می‌شود.
5. بیمار در داشبورد می‌بیند: «اندازه‌گیری شما دریافت شد؛ تا ساعت X بررسی می‌شود.»
6. تیم مقدار و context را review می‌کند.
7. تصمیم ثبت می‌شود: تکرار اندازه‌گیری، تماس، ویزیت، ارجاع یا اقدام فوری.
8. Communication و receipt ثبت می‌شود.
9. evidence بعدی جمع می‌شود.
10. loop با outcome یا برنامهٔ بعدی بسته می‌شود.

### مثال B: HbA1c عقب‌افتاده

- trigger از care gap؛
- پیام غیرترساننده و action واحد؛
- انتخاب مرکز/وقت یا upload نتیجه؛
- reminder با quiet hours؛
- escalation فقط پس از چند تلاش و با policy tenant؛
- closure با نتیجهٔ آزمایش معتبر یا documented exception.

### مثال C: تجدید دارو

- refill due صرفاً reminder نیست؛
- availability، نسخهٔ معتبر، payer و نیاز به review بررسی می‌شود؛
- patient action ممکن است تأیید موجودی یا درخواست تجدید باشد؛
- task به پزشک یا پذیرش می‌رود؛
- Communication تحویل و دریافت را ثبت می‌کند؛
- closure با صدور نسخه، تغییر برنامه یا documented refusal.

### مثال D: افزایش وزن بیمار نارسایی قلب

- trend و symptom context مهم‌تر از یک عدد منفرد است؛
- سیستم uncertainty و data quality را نشان می‌دهد؛
- rule می‌تواند پیشنهاد triage بدهد ولی خودکار دارو را تغییر نمی‌دهد؛
- caregiver در صورت consent می‌تواند action داشته باشد؛
- escalation path و response SLA از قبل تعریف می‌شوند.

---

## ۷. داشبورد بیمار: از «نمایش اطلاعات» به «هدایت مراقبت»

### ۷.۱ اصل مرکزی

صفحهٔ اول بیمار باید به این سؤال جواب دهد:

> «امروز برای سلامتی‌ام چه کاری باید انجام دهم و اگر انجام دهم چه اتفاقی می‌افتد؟»

نه اینکه تمام features را به‌طور مساوی نمایش دهد.

### ۷.۲ ساختار پیشنهادی صفحهٔ Today

1. **یک Primary Action** با متن ساده، زمان تقریبی و CTA واضح.
2. **وضعیت دریافت و پاسخ تیم:** دریافت شد، در انتظار بررسی، بررسی شد، نیازمند اقدام.
3. **Why this matters:** یک توضیح کوتاه و شخصی‌سازی‌شده.
4. **Next two actions:** حداکثر دو اقدام بعدی، نه فهرست بی‌انتها.
5. **Safety panel:** علائم هشدار و مسیر تماس فوری، با زبان غیرتشخیصی.
6. **Care team expectation:** چه کسی پاسخ می‌دهد و در چه بازه‌ای.
7. **Progress:** هدف و روند قابل‌فهم، نه صرفاً نمودار خام.

### ۷.۳ معماری اطلاعات پیشنهادی

```text
Today
Plan & Goals
Measurements
Medicines
Messages
Appointments
Results
Learn
Family & Access
Billing
```

Billing مهم است، اما نباید در صفحهٔ اول با اقدام‌های درمانی رقابت کند.

### ۷.۴ اصول UX برای بیمار مزمن و سالمند

بر اساس شواهد portal و سلامت دیجیتال:

- زبان ساده، مثال و visual aid؛
- فونت خوانا و touch target بزرگ؛
- navigation کم‌عمق و نام‌های مستقیم؛
- login و recovery ساده ولی ایمن؛
- نمایش «چرا»، «حالا چه کنم» و «چه زمانی پاسخ می‌گیرم»؛
- امکان caregiver-assisted onboarding؛
- multilingual و low-data؛
- عدم وابستگی به رنگ به‌تنهایی؛
- tooltip و help در محل کار؛
- عدم نمایش score یا prediction بدون context؛
- عدم ایجاد اضطراب با alertهای مکرر؛
- امکان notification quiet hours و channel preference؛
- نمایش status بررسی self-report.

شواهد portal نشان می‌دهند usefulness، ease of use، self-efficacy و privacy concern از عوامل کلیدی adoption هستند؛ navigation پیچیده و jargon به‌ویژه برای سالمندان و افراد با literacy پایین مانع‌اند ([Son et al., 2021](https://doi.org/10.1111/jnu.12633)، [Norouzi Aval et al., 2025](https://doi.org/10.1002/hsr2.70520)).

### ۷.۵ caregiver mode

همراه باید یک کاربر واقعی با رابطه و scope باشد، نه اشتراک password.

حداقل نیازها:

- invitation و consent بیمار؛
- نوع رابطه و expiry؛
- سطح دسترسی مستقل برای مشاهده، اقدام، پیام و داده؛
- audit جداگانه؛
- امکان revoke فوری؛
- نمایش واضح اینکه کار توسط بیمار یا همراه انجام شده است.

---

## ۸. Workbench تیم درمان

### ۸.۱ Inbox باید بر اساس «کار قابل‌اقدام» باشد

دسته‌بندی پیشنهادی:

- نیازمند triage فوری؛
- منتظر review داده؛
- overdue نسبت به SLA؛
- منتظر پاسخ بیمار؛
- blocked؛
- بدون owner؛
- آمادهٔ closure؛
- reopened؛
- cohort care gaps.

### ۸.۲ sort و priority

priority فقط severity پزشکی نیست. تابع ترکیبی پیشنهادی:

```text
priority = clinical urgency
         + time overdue
         + vulnerability/equity modifier
         + loop aging
         + failure attempts
         + uncertainty/data-quality penalty
```

این فرمول باید ابتدا rule-based و explainable باشد.

### ۸.۳ کاهش بار تیم

- batch assign و batch outreach؛
- templates و structured outcomes؛
- auto-documentation از eventهای سیستم، نه متن‌نویسی دوباره؛
- suppression و dedup؛
- inbox واحد به‌جای alertهای پراکنده؛
- task queueهای role-based؛
- exception report برای «چه چیزی گیر کرده؟»؛
- اندازه‌گیری alert burden و time-to-action.

---

## ۹. موتور پیشنهاد علمی و ایمن

### ۹.۱ معماری لایه‌ای

```text
Evidence Registry
  → Versioned Guideline Pack
  → Computable Knowledge / Rules
  → Patient Fact Bundle
  → Eligibility + Contraindication + Conflict checks
  → Suppression / Dedup / Priority
  → Recommendation with rationale and uncertainty
  → Human review
  → CarePlan / Task / PatientAction
  → Outcome + feedback events
```

### ۹.۲ تفکیک ضروری

سه نوع engine نباید مخلوط شوند:

1. **Knowledge-based rules:** قواعد قابل‌توضیح و نسخه‌دار.
2. **Risk models:** خروجی احتمالی با calibration و validation مستقل.
3. **Generative explanation:** خلاصه یا ترجمه، بدون اختیار تصمیم درمانی.

در فازهای اولیه، recommendation بالینی باید از قواعد دانش‌محور و دادهٔ تأییدشده بیاید. مدل زبانی می‌تواند توضیح را ساده کند، ولی منبع تصمیم نباشد.

### ۹.۳ schema پیشنهادی Rule Artifact

هر rule باید حداقل این metadata را داشته باشد:

```text
rule_code
version
status: draft | shadow | active | retired
condition_scope
population / inclusion / exclusion
required_facts
trigger expression
contraindications
conflict groups
severity / urgency
recommended action
patient-facing explanation
clinician rationale
monitoring requirements
required follow-up
expiry / re-evaluation interval
source citations
source publication/version/date
local adaptation
reviewed_by / approved_by / approved_at
validation dataset/version
shadow metrics
rollback version
```

### ۹.۴ حاکمیت علمی

- evidence register مرکزی؛
- هر guideline pack دارای owner پزشکی؛
- review دوره‌ای و expiry؛
- test caseهای مثبت، منفی، boundary و multimorbidity؛
- shadow mode پیش از نمایش؛
- tenant localization فقط در محدودهٔ مجاز؛
- baseline safety rule غیرقابل‌غیرفعال‌کردن توسط tenant؛
- audit کامل source facts، rule version و decision؛
- override reason ساختاریافته؛
- monitoring drift و نرخ acceptance/dismissal؛
- rollback سریع rule pack.

WHO SMART Guidelines بر machine-readable، testable و software-neutral بودن دانش تأکید می‌کند و CQL/ELM می‌تواند برای تبادل دانش محاسبه‌پذیر الهام‌بخش باشد. Halqe لازم نیست از روز اول CQL کامل پیاده کند، اما DSL داخلی باید versioned، deterministic و قابل‌تبدیل باشد.

### ۹.۵ بودجهٔ alert

همهٔ recommendationها popup نیستند.

| Tier | رفتار |
|---|---|
| 0 | silent analytics / cohort insight |
| 1 | patient education یا suggestion غیرزمانی |
| 2 | non-interruptive clinician inbox |
| 3 | urgent interruptive alert با action روشن |
| 4 | hard stop فقط برای خطر فوری، confidence بالا و مسیر override |

مطالعات CDSS اثرهای متغیر و گاه کوچک بر رفتار و outcome نشان می‌دهند؛ relevance، workflow fit و alert profile حیاتی‌اند ([Ronan et al., 2022](https://doi.org/10.1002/jhm.12825)، [Jia et al., 2018](https://doi.org/10.1111/jep.12968)). شواهد جدید ایران نیز نشان می‌دهد alert غیرinterruptive و workflow-aligned می‌تواند برای ایمنی دارویی مفید باشد ([Aminzade et al., 2026](https://doi.org/10.1111/jgs.70379)).

### ۹.۶ explainability موردنیاز

هر recommendation در UI پزشک باید نشان دهد:

- چرا اکنون ظاهر شده است؛
- facts مؤثر کدام‌اند و تاریخ‌شان چیست؛
- دادهٔ missing یا unverified چیست؛
- guideline و version؛
- contraindication و conflict checks؛
- action پیشنهادی؛
- certainty/limitation؛
- چه چیزی باعث dismiss/snooze می‌شود؛
- زمان re-evaluation.

برای بیمار، توضیح باید ساده‌تر باشد و prediction یا differential diagnosis خام نمایش داده نشود.

---

## ۱۰. راهبرد بیماری‌ها

### فاز ۱: هستهٔ cardiometabolic

دیابت و فشارخون به‌جای دو اپ جدا، روی ماژول‌های مشترک ساخته شوند:

- home measurements؛
- medication/adherence؛
- آزمایش‌های دوره‌ای؛
- وزن و lifestyle؛
- renal function؛
- lipids و cardiovascular risk factors؛
- smoking؛
- appointments/follow-up؛
- patient education؛
- care gaps.

### فاز ۲: بیماری قلبی

- ASCVD secondary prevention؛
- heart failure monitoring؛
- symptoms/weight/BP context؛
- medication safety و polypharmacy؛
- post-discharge loops؛
- caregiver involvement؛
- escalation paths.

### اصل multimorbidity

Ruleها نباید صرفاً با هم جمع شوند. موتور باید conflict، burden و priority را مدیریت کند. پژوهش multimorbidity نشان می‌دهد guidelineهای تک‌بیماری می‌توانند تعارض یا treatment burden ایجاد کنند؛ ابزارهای مفید باید گزینه‌ها را یکجا و قابل‌اولویت‌بندی نمایش دهند ([Samal et al., 2021](https://doi.org/10.1111/1475-6773.13860)).

---

## ۱۱. چندمستاجری و عمومی‌سازی محصول

### ۱۱.۱ چیزهایی که tenant می‌تواند تنظیم کند

- branding و زبان؛
- location و ساعات؛
- تیم‌ها و queueها؛
- roleها و permissions؛
- SLA profile؛
- message channels و quiet hours؛
- service catalog و accounting policy؛
- payer/insurance configuration؛
- device adapters؛
- care pathway templates؛
- local education content؛
- escalation contacts؛
- report/dashboard preferences.

### ۱۱.۲ چیزهایی که نباید آزادانه غیرفعال شوند

- tenant isolation و audit؛
- unverified-data gate؛
- consent requirements؛
- high-risk safety baseline؛
- rule provenance؛
- immutable event history؛
- closure evidence requirements برای loopهای safety-critical؛
- PHI minimum-necessary boundaries.

### ۱۱.۳ حسابداری عمومی

حسابداری باید از workflow یک درمانگاه خاص جدا شود و configuration-driven باشد:

- نوع مرکز: مطب، کلینیک چندتخصصی، درمانگاه، مرکز procedure؛
- service/tariff catalog؛
- payer و قرارداد؛
- performer role و revenue share؛
- location/shift؛
- tax/payroll profile؛
- invoice lifecycle policy؛
- payment method و settlement؛
- report dimensions؛
- integration boundaries.

Care Loop نباید به نوع خاص invoice وابسته باشد؛ فقط در صورت نیاز reference مالی داشته باشد.

---

## ۱۲. رقابت و جایگاه Halqe

بازار فعلی به چند گروه تقسیم می‌شود:

- **MyChart:** پورتال گستردهٔ پرونده، appointment، results، bills و family access.
- **Omada / Dario:** تجربهٔ multi-condition، coaching، device و رفتار.
- **Welldoc:** insightهای cardiometabolic و AI شخصی‌سازی‌شده.
- **Cadence:** remote monitoring، تیم بالینی، triage و titration در workflow پزشک.
- **Huma:** زیرساخت و اپ‌های configurable برای RPM و care pathways.

شکاف استراتژیک قابل‌دفاع Halqe:

> یک پلتفرم multi-tenant و clinic-native که پرونده، عملیات، حسابداری، مراقبت مزمن حلقه‌بسته، تجربهٔ بیمار/همراه و موتور دانش علمی را در یک مدل واحد به هم متصل کند؛ با بومی‌سازی زبان، بیمه و workflow منطقه.

این مزیت فقط زمانی واقعی است که Halqe «عملیات انسانیِ پشت dashboard» را نیز محصول کند. dashboard زیبا بدون response service و ownership مزیت پایدار نیست.

---

## ۱۳. معیارهای محصول

### North Star پیشنهادی

```text
درصد Care Loopهای واجد شرایط که
در SLA تعریف‌شده، با evidence کافی و outcome معتبر بسته شده‌اند.
```

### Leading indicators

- زمان trigger تا triage؛
- زمان triage تا owner؛
- زمان تا اولین outreach؛
- patient action completion؛
- response SLA تیم؛
- درصد loopهای بدون owner؛
- overdue/blocked aging؛
- suggestion-to-plan conversion؛
- self-report review latency؛
- closure without evidence rate؛
- reopen rate؛
- delivery/read/reply rate ارتباط.

### Outcome metrics

- کنترل BP؛
- تغییر HbA1c؛
- care-gap closure؛
- adherence و persistence؛
- no-show و follow-up return؛
- hospitalization/readmission در cohortهای مناسب؛
- کیفیت زندگی و patient-reported burden.

این outcomeها باید در pilot و مطالعهٔ pragmatic سنجیده شوند و پیش از آن claim بازاریابی نشوند.

### Guardrails

- alert burden per clinician؛
- override/dismiss rate؛
- false escalation؛
- unreviewed high-risk data؛
- patient anxiety/complaints؛
- inequity بر اساس سن، literacy، location و connectivity؛
- caregiver access misuse؛
- PHI/consent incidents؛
- clinician time per closed loop.

---

## ۱۴. ترتیب ساخت پیشنهادی حاصل از پژوهش

### مرحلهٔ A — foundation

- CareLoop، CareTask و event model؛
- owner/queue/SLA/escalation؛
- closure evidence؛
- migration از FollowupTask فعلی؛
- unified staff inbox.

### مرحلهٔ B — patient surround

- authenticated patient identity؛
- Today dashboard؛
- tasks و plan؛
- status بررسی self-report؛
- messaging/communication receipts؛
- notification preferences؛
- caregiver proxy + consent.

### مرحلهٔ C — scientific knowledge platform

- evidence registry؛
- guideline pack/version/release؛
- DSL و test harness؛
- suppression/dedup/alert tiers؛
- shadow mode و monitoring؛
- clinician explanation panel.

### مرحلهٔ D — disease packs

1. diabetes + hypertension؛
2. ASCVD/heart failure؛
3. CKD/lipids/obesity as shared modules؛
4. توسعهٔ تدریجی بر اساس evidence و capacity.

### مرحلهٔ E — population operations

- cohort workbench؛
- exception reports؛
- campaign-safe outreach؛
- capacity forecasting؛
- outcome/equity analytics؛
- value-based reporting در صورت وجود مدل قرارداد.

---

## ۱۵. آزمایش‌های محصول قبل از توسعهٔ بزرگ

1. **Concierge loop test:** ده بیمار، پیگیری دستی با مدل پیشنهادی؛ اندازه‌گیری bottleneckها.
2. **Patient Today prototype:** تست usability با بیمار، سالمند و caregiver.
3. **Clinician inbox prototype:** مقایسهٔ queue مبتنی بر urgency/SLA با worklist فعلی.
4. **Alert budget experiment:** non-interruptive در برابر popup.
5. **Diabetes/HTN pathway simulation:** test caseهای چندبیماری و conflict.
6. **Notification experiment:** channel، زمان و متن با opt-out و fatigue measurement.
7. **Caregiver access usability/security test.**
8. **Shadow rule evaluation:** sensitivity، precision، duplication و workload قبل از نمایش.

---

## ۱۶. تصمیم‌های قفل‌شدهٔ این دور

- Care Loop واحد ارزش و telemetry است.
- closure بدون evidence ممنوع است.
- patient dashboard action-first است.
- بیمار باید status بررسی و response expectation را ببیند.
- caregiver یک principal مستقل با consent است.
- پیشنهاد، task و care plan موجودیت‌های جدا هستند.
- rule engine، risk model و generative explanation جدا هستند.
- موتور در فاز اولیه خودکار نسخه یا titration انجام نمی‌دهد.
- alert interruptive یک منبع کمیاب است و budget دارد.
- knowledge artifactها versioned، tested، cited و rollbackable هستند.
- tenant customization نمی‌تواند safety baseline را خاموش کند.
- outcome claims فقط پس از pilot و ارزیابی معتبر مجازند.

---

## ۱۷. سؤال‌های باز برای دور بعد

- مدل دقیق سرویس انسانی: nurse-led، care navigator یا hybrid؟
- SLA اقتصادی و عملیاتی برای هر tenant چگونه قیمت‌گذاری شود؟
- بیمار چه اندازه‌ای از clinical rationale را باید ببیند؟
- مرز messaging عمومی و medical advice چیست؟
- چگونه guidelineهای ایران، راهنماهای بین‌المللی و local formulary با هم version شوند؟
- چه داده‌هایی برای heart failure در فاز اول واقعاً قابل‌اتکا هستند؟
- caregiver access در بیمار کم‌توان یا دارای اختلاف خانوادگی چگونه مدیریت شود؟
- چه مدل کسب‌وکاری workload مراقبت پیوسته را پایدار می‌کند؟
- آیا patient app باید native، PWA یا multi-channel باشد؟
- حداقل cohort و مدت pilot برای ادعاهای outcome چیست؟

---

## منابع منتخب این دور

- [Kilfoy et al. — nurse-led remote digital support](https://doi.org/10.1111/jocn.17226)
- [Granath et al. — patient–nurse relationship in remote monitoring](https://doi.org/10.1111/scs.70166)
- [Samal et al. — health IT for multiple chronic conditions](https://doi.org/10.1111/1475-6773.13860)
- [Mikkonen et al. — technology-supported lifestyle interventions](https://doi.org/10.1111/jocn.16448)
- [Buck et al. — self-care theory and mHealth](https://doi.org/10.1002/nur.22073)
- [Jia et al. — CDSS in diabetes](https://doi.org/10.1111/jep.12968)
- [Ronan et al. — CDSS and provider behavior](https://doi.org/10.1002/jhm.12825)
- [Gholamzadeh et al. — knowledge-based CDSS](https://doi.org/10.1155/2023/8550905)
- [Aminzade et al. — non-interruptive prescribing alerts in Iran](https://doi.org/10.1111/jgs.70379)
- [Norouzi Aval et al. — patient portal features](https://doi.org/10.1002/hsr2.70520)
- [Son et al. — model of patient portal use](https://doi.org/10.1111/jnu.12633)
- [Alcántara-Porcuna et al. — diabetes technology lived experience](https://doi.org/10.1111/nhs.70348)
- [Chen et al. — older adults, caregivers and heart-failure mHealth](https://doi.org/10.1002/nop2.70356)
- [WHO SMART Guidelines](https://www.who.int/teams/digital-health-and-innovation/smart-guidelines)
- [HL7 FHIR CarePlan](https://hl7.org/fhir/careplan.html)
- [HL7 FHIR Goal](https://hl7.org/fhir/goal.html)
- [HL7 FHIR Task](https://hl7.org/fhir/task.html)
- [HL7 FHIR Consent](https://hl7.org/fhir/consent.html)
- [HL7 CQL](https://cql.hl7.org/)
- [FDA Clinical Decision Support Software Guidance](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software)
- [NICE Evidence Standards Framework](https://www.nice.org.uk/corporate/ecd7)

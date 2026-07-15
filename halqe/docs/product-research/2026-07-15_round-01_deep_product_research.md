# دور اول پژوهش عمیق محصول — حلقهٔ بستهٔ مراقبت مزمن

**تاریخ پژوهش:** ۲۰۲۶-۰۷-۱۵  
**شاخهٔ مبنا:** `agent/halqe-unified-migration-audit`  
**وضعیت:** پژوهش و فرضیهٔ محصول؛ نه roadmap نهایی و نه دستور بالینی  
**تمرکز:** دیابت، فشارخون، بیماری قلبی‌عروقی، داشبورد بیمار، موتور پیشنهاد، چندمستأجری و عمومی‌سازی عملیات/حسابداری

---

## ۱. تز اصلی محصول

حلقه نباید «یک نرم‌افزار مطب با چند صفحهٔ بیشتر» یا «ترکیب حسابداری و پرونده» تعریف شود. تز قوی‌تر این است:

> **حلقه، سیستم‌عامل مراقبت مستمر برای کلینیک‌های ایرانی است؛ سامانه‌ای که بین ویزیت‌ها بیمار را رها نمی‌کند و هر داده، پیشنهاد، تماس، نوبت و اقدام را تا بسته‌شدن حلقه دنبال می‌کند.**

واحد ارزش محصول نه صفحه، پیام یا حتی ویزیت است؛ واحد ارزش باید **Care Loop** باشد:

```text
نیاز مراقبتی شناسایی شد
→ مسئول و موعد تعیین شد
→ بیمار فهمید چه کاری باید انجام دهد
→ داده/اقدام ثبت شد
→ تیم درمان آن را دید و در صورت لزوم پاسخ داد
→ نتیجه تأیید شد
→ برنامهٔ مراقبت به‌روز شد
→ حلقه بسته شد یا با علت مشخص باز ماند
```

این تعریف هم‌زمان برای پنج ذی‌نفع ارزش دارد:

- **بیمار:** می‌داند امروز چه کاری مهم است و چرا.
- **پزشک:** مهم‌ترین استثناها را می‌بیند، نه سیل دادهٔ خام را.
- **مدیر کلینیک:** می‌بیند کدام مراقبت‌ها انجام نشده و کجا ظرفیت تیم هدر می‌رود.
- **سرمایه‌گذار:** محصول دارای موتور retention و دادهٔ longitudinal می‌شود، نه یک ابزار episodic.
- **توسعه‌دهنده:** دامنه حول state machine و outcome قابل‌آزمون ساخته می‌شود، نه مجموعه‌ای از CRUDهای پراکنده.

---

## ۲. واقعیت فعلی محصول، بدون خوش‌بینی کاذب

### ۲.۱ سطح کارکنان

صفحهٔ پروندهٔ کارکنان در `halqe/web/src/app/patients/[uuid]/page.tsx` یک safety cockpit واقعی دارد: دادهٔ اصلی، پروندهٔ ساختاریافته، پیشنهادها، timeline غربالگری، حساسیت، verification inbox، ویزیت و تب‌های overview/trends/meds/record. این پایهٔ خوبی برای تجربهٔ پزشک است؛ اما هنوز باید از منظر «اقدام بعدی، دلیل اولویت و بسته‌شدن حلقه» یکپارچه‌تر شود.

### ۲.۲ سطح بیمار

سطح فعلی بیمار **پرتال بیمار نیست**:

- `halqe/web/src/app/card/[token]/page.tsx:3-18` یک کارت عمومی، token-based و کاملاً read-only است.
- همان صفحه فقط شاخص‌های منتخب، یادآور خنثی و نوبت بعدی را نشان می‌دهد (`:206-284`).
- `halqe/clinical/api/self_report.py:3-29` یک مسیر عمومی با token یک‌بارمصرف برای ثبت self-report دارد.
- whitelist فعلی self-report فقط FBS و فشار سیستولیک/دیاستولیک است (`self_report.py:78-89`).
- دادهٔ بیمار با `verified=FALSE` ذخیره و تا تأیید پزشک از موتور و کارت کنار گذاشته می‌شود؛ این گارد ایمنی درست است.

نتیجه: **کارت عمومی و self-report یک‌بارمصرف باید حفظ شوند، ولی داشبورد احراز‌شدهٔ بیمار یک bounded context مستقل است.** گسترش دادن کارت عمومی به یک پرتال کامل، سطح حمله، مدل رضایت و تجربهٔ کاربری را مخدوش می‌کند.

### ۲.۳ حسابداری و عملیات

طبق `halqe/docs/UNIFIED_MIGRATION_AUDIT_REPORTING_UPDATE.md`، عملیات حسابداری، تنظیمات، گزارش، payroll، audit، ETL، verifier، backup/restore، dual-run و release gate از نظر runtime تکمیل شده‌اند؛ اما rehearsal واقعی و sign-off بیرونی باقی است.

بااین‌حال «وفاداری به برنامهٔ قدیمی» با «عمومی‌بودن برای تمام کلینیک‌ها» یکی نیست. مدل فعلی هنوز باید برای تنوع زیر طراحی شود:

- مطب تک‌پزشک در برابر درمانگاه چندشیفت؛
- کلینیک تک‌شعبه در برابر سازمان چندشعبه؛
- صندوق واحد در برابر چند cashier/register؛
- خدمات نقدی، بیمه‌ای، بسته‌ای، اشتراکی و قراردادی؛
- نقش‌های متفاوت پزشک، پرستار، ماما، تکنسین، منشی، حسابدار و مدیر؛
- workflowهای تخصصی متفاوت، بدون fork کردن محصول.

---

## ۳. سنتز تیم چندنقشی

### ۳.۱ صدای پزشک

یک پزشک شلوغ محصولی را می‌پذیرد که در کمتر از چند ثانیه پاسخ دهد:

1. این بیمار اکنون در چه وضعیتی است؟
2. خطر فوری چیست؟
3. چه داده‌ای قابل اعتماد و چه داده‌ای تأییدنشده است؟
4. امروز چه تصمیمی باید بگیرم؟
5. چه چیزی را می‌توانم به تیم واگذار کنم؟
6. اگر کاری نکنم، کدام حلقه باز می‌ماند؟

نمایش ده‌ها alert هم‌ارز ایمنی نیست. پیشنهاد باید در لحظهٔ مرتبط، با rationale، شواهد، دادهٔ محرک، contraindication و اقدام‌های ممکن نمایش داده شود.

### ۳.۲ صدای بیمار

بیمار مزمن معمولاً دنبال «همهٔ اطلاعات پزشکی» نیست. سؤال‌های اصلی او ساده‌ترند:

- امروز چه کار کنم؟
- دارویم را چگونه ادامه دهم؟
- چه زمانی اندازه‌گیری کنم؟
- نتیجه‌ام خوب است یا باید تماس بگیرم؟
- نوبت یا آزمایش بعدی چیست؟
- آیا اطلاعاتم دیده شده است؟
- اگر گوشی یا سواد دیجیتال کافی ندارم، چه کسی کمکم می‌کند؟

داشبوردی که با نمودار و اصطلاحات تخصصی آغاز شود، ممکن است از نظر بصری جذاب و از نظر رفتاری ناموفق باشد.

### ۳.۳ صدای همراه/مراقب

بسیاری از بیماران سالمند یا چندبیماری عملاً با کمک فرزند یا caregiver مراقبت را مدیریت می‌کنند. دسترسی همراه باید:

- با رضایت صریح بیمار ایجاد شود؛
- scope مشخص داشته باشد؛
- مستقل از رمز بیمار باشد؛
- تاریخ انقضا/ابطال داشته باشد؛
- audit شود؛
- بین «دیدن»، «ثبت داده»، «مدیریت نوبت» و «پیام‌دادن» تفکیک کند.

### ۳.۴ صدای مدیر کلینیک

مدیر به جای تعداد پیام‌ها یا logins به این موارد نیاز دارد:

- چند بیمار فعال مزمن داریم؟
- چند حلقه باز، overdue، blocked یا بدون owner است؟
- چند self-report هنوز بررسی نشده؟
- زمان پاسخ تیم به red flag چقدر است؟
- کدام cohort نیازمند ظرفیت بیشتر است؟
- چند بیمار پس از outreach به اقدام/ویزیت رسیدند؟
- کیفیت داده و adherence هر ماژول چگونه است؟
- بار کاری هر role چقدر است؟

### ۳.۵ صدای سرمایه‌گذار

خندق رقابتی حلقه صرفاً rule engine یا حسابداری نیست. moat بالقوه از ترکیب این موارد ساخته می‌شود:

1. workflow روزانهٔ کلینیک؛
2. دادهٔ longitudinal با provenance؛
3. care-plan و task graph چندبیماری؛
4. feedback پزشک روی پیشنهادها؛
5. adaptation بومی به زبان، بیمه، نقش‌ها و واقعیت عملیاتی ایران؛
6. switching cost ناشی از بسته‌شدن واقعی حلقه‌ها، نه قفل‌کردن داده.

اما هیچ‌کدام پیش از استفادهٔ واقعی، retention و outcome قابل‌اندازه‌گیری «اثبات‌شده» نیست.

---

## ۴. مهم‌ترین نتیجهٔ شواهد علمی

### ۴.۱ دادهٔ بیشتر به‌تنهایی درمان نیست

شواهد دیابت، فشارخون و نارسایی قلبی یک الگوی مشترک نشان می‌دهند: مداخله‌های دیجیتال زمانی معنادارترند که **multicomponent** باشند؛ یعنی self-monitoring را به آموزش، feedback، coaching/case management و تغییر برنامهٔ مراقبت وصل کنند.

- meta-analysis سال ۲۰۲۵ روی mHealth برای بزرگسالان مبتلا به دیابت نوع ۲، اثر متوسط و نه معجزه‌آسای HbA1c را گزارش کرد؛ سایر پیامدها نامطمئن‌تر بودند ([Versluis et al., 2025](https://doi.org/10.1111/dme.70002)).
- در فشارخون، meta-analysis سال ۲۰۲۳ بهبود کنترل و کاهش فشار را گزارش کرد، ولی مرورهای حوزه تأکید می‌کنند self-monitoring بدون co-intervention معمولاً کافی نیست ([Zhou et al., 2023](https://doi.org/10.1111/jch.14690)، [Wang et al., 2021](https://doi.org/10.1111/jch.14194)).
- در نارسایی قلبی، meta-analysis سال ۲۰۲۵ مؤلفه‌های مؤثرتر را self-management، آموزش و ارتباط ویدیویی دانست؛ heterogeneity همچنان مهم است ([De Lathauwer et al., 2025](https://doi.org/10.1002/ejhf.3568)).
- در جمعیت‌های عرب، مداخلات شخصی‌سازی‌شده و تماس مستقیم بهتر از remote monitoring غیرشخصی گزارش شدند؛ این یافته برای بومی‌سازی فرهنگی ایران قابل‌توجه است، ولی معادل‌سازی مستقیم جمعیت‌ها مجاز نیست ([Abd Elqader & Srulovici, 2024](https://doi.org/10.1111/jan.16423)).

**پیام محصولی:** حلقه نباید به «جمع‌کنندهٔ فشار و قند» تقلیل یابد. هر داده باید مسیر پاسخ، owner، SLA و نتیجه داشته باشد.

### ۴.۲ تکنولوژی باید بار را کاهش دهد، نه منتقل کند

مطالعات multimorbidity نشان می‌دهند portal یا ePRO اگر با workflow پزشک یکپارچه نباشد، می‌تواند مستندسازی و مقاومت تیم را افزایش دهد ([Samal et al., 2021](https://doi.org/10.1111/1475-6773.13860)).

**پیام محصولی:** هر قابلیت بیمار-facing باید هم‌زمان پاسخ دهد «این داده در صف چه کسی می‌نشیند، چه زمانی دیده می‌شود و چه چیزی از کار قبلی حذف می‌کند؟»

### ۴.۳ طراحی برای سالمند، caregiver و سواد محدود یک feature جانبی نیست

مرورهای جدید بر نیازهای سالمندان بر onboarding تدریجی، پشتیبانی مداوم، رابط کم‌بار و مشارکت خانواده تأکید دارند ([Kim & Ha, 2026](https://doi.org/10.1111/opn.70062)، [Wang et al., 2025](https://doi.org/10.1111/wvn.70030)).

**پیام محصولی:** voice، فونت بزرگ، زبان ساده، گزینهٔ تماس، proxy access و fallback غیرهوشمند بخشی از core UX هستند.

### ۴.۴ موتور پیشنهاد باید اثرش را اثبات کند

مرورهای CDSS نشان می‌دهند بهبود process-of-care از outcome بالینی منظم‌تر است و adoption پزشک همیشه بالا نمی‌رود ([Jia et al., 2018](https://doi.org/10.1111/jep.12968)، [Ronan et al., 2022](https://doi.org/10.1002/jhm.12825)).

**پیام محصولی:** موفقیت موتور با «تعداد ruleهای fired» سنجیده نمی‌شود. باید precision، actionability، override reason، time-to-action و downstream completion سنجیده شوند.

---

## ۵. مدل دامنهٔ پیشنهادی

حلقه باید حداقل این bounded contextها را صریح نگه دارد:

```text
Identity & Consent
Tenant / Organization / Location
Clinical Record
Care Plan & Goals
Observation & Device Data
Medication Management
Recommendation & Evidence
Task / Follow-up / Worklist
Communication & Engagement
Appointment / Encounter
Accounting & Revenue Cycle
Patient & Caregiver Experience
Analytics / Experimentation
Audit / Safety / Governance
```

### مرز مهم

- **Clinical Record** واقعیت ثبت‌شده را نگه می‌دارد.
- **Care Plan** قصد، هدف، owner و برنامهٔ patient-specific را نگه می‌دارد.
- **Recommendation** پیشنهاد موقت موتور است و تا تأیید پزشک plan/order نیست.
- **Task/Follow-up** کار قابل انجام با deadline و state machine است.
- **Engagement** کانال ارسال است، نه منبع حقیقت مراقبت.
- **Accounting** ارزش مالی را ثبت می‌کند، ولی نباید تصمیم بالینی را شکل دهد یا مراقبت ضروری را محدود کند.

برای شکل care plan می‌توان از مفاهیم FHIR الهام گرفت: CarePlan بیمارمحور می‌تواند conditions، goals، care team و activities را گروه‌بندی کند؛ protocol عمومی باید جدا از plan بیمار باشد. این استفاده فعلاً **conceptual alignment** است، نه تعهد به ساخت FHIR server.

---

## ۶. Blueprint داشبورد بیمار

### ۶.۱ اصل طراحی

صفحهٔ اول بیمار باید پاسخ «امروز چه کنم؟» باشد، نه نسخهٔ ساده‌شدهٔ پروندهٔ پزشک.

### ۶.۲ معماری اطلاعات سطح اول

```text
امروز
برنامهٔ مراقبت
ثبت اندازه‌گیری
داروها
نوبت‌ها و درخواست‌ها
پیام‌ها
آموزش من
پرونده و نتایج
دسترسی همراه و حریم خصوصی
```

### ۶.۳ صفحهٔ «امروز»

ترتیب پیشنهادی:

1. **وضعیت ارتباط:** «دادهٔ شما دریافت شد / در انتظار بررسی / دیده شد».
2. **حداکثر سه اقدام اولویت‌دار:** با زمان، دلیل ساده و CTA روشن.
3. **هشدار ایمنی:** فقط red flag واقعی، با دستور تماس/اورژانس از متن تأییدشدهٔ پزشکی؛ نه تشخیص خودکار.
4. **اندازه‌گیری بعدی:** دستگاه/روش/زمان و کیفیت داده.
5. **دارو و refill:** بدون تغییر دوز خودکار.
6. **نوبت یا کار بعدی:** آزمایش، ویزیت، تماس یا آموزش.
7. **پیشرفت هدف:** محدود، قابل فهم و بدون ایجاد احساس شکست.

### ۶.۴ ثبت داده

برای فشارخون، ثبت یک عدد کافی نیست. UX باید بتواند protocol ثبت را پشتیبانی کند:

- زمان و context اندازه‌گیری؛
- امکان ثبت جفت reading؛
- validation فیزیولوژیک و validation workflow؛
- راهنمای کوتاه وضعیت بدن/کاف، بدون ادعای تشخیصی؛
- نمایش source و verification status؛
- حالت device-connected و manual؛
- offline queue و sync conflict handling در آینده.

برای دیابت:

- نوع reading مانند fasting/post-meal باید صریح باشد؛
- medication/meal context اختیاری و با کمترین بار؛
- hypoglycemia safety flow باید مستقل از نمودار معمول باشد؛
- بیمار نباید از روی dashboard دوز خود را بدون plan مصوب تغییر دهد.

برای نارسایی قلبی/قلبی:

- وزن، فشار، ضربان و symptom check می‌توانند بخشی از plan باشند؛
- protocol فقط برای cohort تأییدشده فعال شود؛
- دادهٔ abnormal بدون تیم پاسخ‌گو و SLA نباید جمع‌آوری شود.

### ۶.۵ زبان و سواد سلامت

سه سطح نمایش لازم است:

1. **ساده:** اقدام و معنای عمومی.
2. **بیشتر بدانید:** توضیح آموزشی کوتاه.
3. **جزئیات پزشکی:** داده و provenance برای بیمار علاقه‌مند، بدون تبدیل پیشنهاد به دستور درمان.

اصول UI:

- Persian-first، RTL واقعی و تاریخ جلالی؛
- عدد، واحد و بازه همیشه کنار هم؛
- رنگ هرگز تنها سیگنال نباشد؛
- target لمسی مناسب، focus قابل‌دیدن و error قابل اصلاح؛
- اصطلاحات ثابت و قابل شنیدن با screen reader؛
- حالت high-contrast، فونت بزرگ و reduced motion؛
- voice/paper/call fallback برای بیمار کم‌سواد یا بدون گوشی هوشمند.

هدف حداقل باید WCAG 2.2 AA باشد، به‌اضافهٔ تست انسانی سالمند و کاربر کم‌سواد؛ conformance خودکار به‌تنهایی کافی نیست.

### ۶.۶ دسترسی همراه

مدل پیشنهادی:

```text
Patient Account
  └── grants
      ├── caregiver A: appointments + reminders
      ├── caregiver B: view care plan + submit readings
      └── revoke / expire / audit
```

هر grant باید tenant، patient، grantee identity، scopes، consent evidence، issued_at، expires_at و revoked_at داشته باشد.

### ۶.۷ اعتماد

داشبورد باید صریح نشان دهد:

- چه کسی داده را می‌بیند؛
- کدام داده هنوز تأیید نشده؛
- چرا یک پیشنهاد ظاهر شده؛
- محصول جای پزشک تصمیم نمی‌گیرد؛
- بیمار چگونه consent و دسترسی caregiver را کنترل می‌کند؛
- در حالت بحران چه کانالی معتبر است.

---

## ۷. موتور پیشنهاد علمی: از rule catalog به Evidence-governed CDS

### ۷.۱ اصل

موتور نباید «پاسخ پزشکی» تولید کند؛ باید یک **recommendation object قابل ممیزی** بسازد:

```text
recommendation_id
patient + tenant
clinical intent
triggered_by facts with provenance
population eligibility
exclusions / contraindications
recommendation text
candidate actions
urgency and interruption policy
evidence package + version
uncertainty / missing data
created_at + expires_at
clinician decision + reason
resulting task/order/plan reference
```

### ۷.۲ رجیستر شواهد

هر rule یا protocol باید به یک Evidence Package متصل شود:

- guideline/paper title؛
- organization/journal؛
- publication year و version؛
- DOI/URL؛
- recommendation strength/certainty در صورت وجود؛
- target population؛
- exclusions؛
- effective_from و review_due_at؛
- clinical owner و reviewer؛
- local adaptation rationale؛
- change log.

گایدلاین‌ها mutable هستند؛ rule بدون version pin یک بدهی ایمنی است.

### ۷.۳ pipeline انتشار rule

```text
Draft
→ evidence review
→ specialist review
→ pharmacist/safety review when relevant
→ executable tests
→ retrospective replay on synthetic/de-identified cohorts
→ shadow mode
→ limited tenant rollout
→ monitoring
→ active
→ superseded/retired
```

هیچ مدیر tenant نباید بتواند یک threshold یا rule بالینی را بدون workflow تأیید و audit آزادانه تغییر دهد. customization محلی باید بین این سه دسته تفکیک شود:

- presentation/workflow policy؛
- target قابل فردی‌سازی توسط پزشک برای بیمار؛
- clinical knowledge که فقط از مسیر governance منتشر می‌شود.

### ۷.۴ مدیریت alert fatigue

پیشنهادها باید tier شوند:

- **Interruptive safety alert:** نادر، high-specificity و نیازمند پاسخ فوری.
- **Inline recommendation:** در context ویزیت یا review.
- **Worklist task:** قابل واگذاری و زمان‌بندی.
- **Digest/cohort insight:** برای مدیر یا تیم جمعیت.
- **Silent analytics:** فقط برای سنجش کیفیت؛ بدون مزاحمت.

برای هر rule اندازه‌گیری شود:

```text
fire rate
unique-patient rate
accept / dismiss / defer
reason distribution
time to review
time to action
repeat burden
false-positive review
missing-data rate
care-loop completion
safety event / near miss
```

### ۷.۵ AI/LLM

کاربرد نزدیک‌مدت مناسب:

- خلاصه‌سازی با citation به دادهٔ منبع؛
- تبدیل متن پزشک به draft ساختاریافته برای تأیید؛
- جستجوی evidence registry؛
- توضیح سادهٔ plan مصوب به بیمار؛
- پیشنهاد template پیام، با review انسانی.

کاربرد نامناسب در فاز فعلی:

- تشخیص قطعی؛
- تغییر دارو یا دوز خودکار؛
- triage مستقل بدون مسیر ایمنی؛
- تولید guideline rule بدون review؛
- استفاده از متن hallucinated به‌عنوان clinical fact.

راهنمای WHO بر قراردادن اخلاق و حقوق انسان در مرکز طراحی و پاسخ‌گویی ذی‌نفعان تأکید دارد. راهنمای CDS FDA نیز، هرچند برای ایران الزام حقوقی مستقیم نیست، یادآور می‌شود که patient/caregiver-facing software و امکان بررسی مستقل مبنای پیشنهاد می‌توانند مرز رگولاتوری را تغییر دهند. برای حلقه این‌ها باید به‌عنوان **design constraint محافظه‌کارانه** استفاده شوند، نه ادعای انطباق آمریکا.

---

## ۸. عمومی‌سازی چندمستأجره برای همهٔ کلینیک‌ها

### ۸.۱ tenant با organization برابر نیست

مدل پیشنهادی:

```text
Tenant
└── Organization
    ├── Locations / branches
    │   ├── departments
    │   ├── rooms / stations
    │   ├── schedules / shifts
    │   └── cash registers
    ├── staff memberships + roles
    ├── clinical programs
    ├── payer contracts
    ├── service catalogs
    └── communication policies
```

در پایلوت ممکن است Tenant=Organization=Location باشد، ولی schema و authorization نباید این هم‌ارزی را دائمی فرض کنند.

### ۸.۲ capability profile، نه clinic-type branching

`office/clinic/polyclinic` برای onboarding و defaults مفید است، اما منطق محصول نباید پر از شرط نوع مرکز شود. بهتر است هر tenant مجموعهٔ capability داشته باشد:

```text
appointments
chronic-care
nursing-station
procedures
inventory
insurance
payroll
patient-portal
remote-monitoring
multi-location
```

پکیج تجاری می‌تواند capability را فعال کند، ولی دسترسی به مراقبت ضروری و export داده نباید گروگان subscription شود.

### ۸.۳ gapهای حسابداری برای عمومی‌شدن

حتی با runtime کامل فعلی، این قابلیت‌ها باید جداگانه ارزیابی شوند:

- branch/location و cost center؛
- numbering policy فاکتور/رسید per location؛
- cashier shift و cash reconciliation؛
- refund، void، credit note و deposit؛
- discount policy و authorization؛
- قرارداد payer با تاریخ اعتبار و ruleهای coverage؛
- claim lifecycle و denial/rework در صورت ورود به scope؛
- service bundle/package؛
- inventory با lot/expiry/procurement اگر دارو/مصرفی واقعی مدیریت شود؛
- tax/legal invoice configuration؛
- chart of accounts و double-entry فقط اگر واقعاً محصول accounting کامل هدف باشد؛
- export و data portability؛
- segregation of duties و approval matrix؛
- audit خوانا برای مدیر غیرتکنیکی.

تصمیم مهم محصول: حلقه می‌تواند «revenue-cycle و عملیات مالی کلینیک» باشد بدون اینکه در فاز اول یک ERP یا دفترکل عمومی کامل شود. این مرز باید آگاهانه قفل شود.

### ۸.۴ ایزولاسیون چندمستأجره

RLS شرط لازم است، نه کافی. تست‌ها باید پوشش دهند:

- cross-tenant direct-object access؛
- background jobs و scheduler؛
- exports/reports؛
- cache keys؛
- object storage paths؛
- notification routing؛
- search indexes و analytics؛
- support/admin impersonation؛
- backup/restore یک tenant؛
- caregiver linked to patients across organizations؛
- tenant-specific clinical policy without contaminating global evidence.

---

## ۹. خوانش رقبا و جای خالی حلقه

### ۹.۱ رقبای بین‌المللی

- MyChart تجربهٔ portal عمومی را حول نوبت، نتایج، دارو، صورتحساب، پیام پزشک و مدیریت خانواده استاندارد کرده است.
- Omada و Teladoc chronic care را با connected device، coaching و care plan ترکیب می‌کنند.
- Welldoc و Dario روی cardiometabolic multi-condition و personalization متمرکزند.
- Huma و Cadence remote monitoring را با workflow تیم مراقبت و استقرار سازمانی ترکیب می‌کنند.

### ۹.۲ بازیگران ایرانی بررسی‌شده

پذیرش۲۴، دکتردکتر/دکتورتو و دکترساینا عمدتاً در discovery، نوبت، مشاورهٔ آنلاین و خدمات دسترسی قوی‌اند. این‌ها معیار UX رزرو و دسترسی هستند، اما بر اساس صفحات عمومی بررسی‌شده، جایگاه اصلی آن‌ها «سیستم‌عامل داخلی care-loop کلینیک» نیست.

### ۹.۳ تمایز قابل دفاع حلقه

نه «داشتن هوش مصنوعی» و نه «داشتن پرونده» به‌تنهایی تمایز نیست. ترکیب زیر می‌تواند تمایز باشد:

```text
Clinic-owned workflow
+ local accounting/operations
+ disease-specific longitudinal record
+ verified home data
+ evidence-governed recommendation
+ team worklist and SLA
+ patient/caregiver action dashboard
+ measurable closed-loop completion
```

### ۹.۴ قابلیت‌هایی که بازار آن‌ها را baseline کرده ولی حلقه هنوز کامل ندارد

- حساب احراز‌شدهٔ بیمار؛
- proxy/caregiver access؛
- secure messaging؛
- refill/request workflow؛
- patient-facing care plan و goals؛
- connected-device onboarding؛
- notification preference center؛
- data export و consent center؛
- onboarding نقش‌محور و help؛
- چندشعبه و capability configuration؛
- clinical content lifecycle UI؛
- integration framework با lab/pharmacy/insurance/devices؛
- support/incident experience برای tenant.

---

## ۱۰. gap map منطقی

### P0 — پیش از ساخت dashboard جذاب

1. تعریف account و authentication بیمار، recovery و session security.
2. تعریف consent، caregiver/proxy و audit.
3. مدل patient-specific CarePlan/Goal/Activity.
4. مدل task owner، SLA، escalation و closure reason.
5. تعریف red-flag response protocol و مسئولیت کلینیک.
6. evidence registry و versioning ruleها.
7. تفکیک notification، clinical recommendation و administrative reminder.
8. مشخص‌کردن مرز دقیق accounting product: revenue-cycle یا general ledger.

### P1 — ستون فقرات تجربه

1. patient portal shell و صفحهٔ «امروز».
2. care-plan view و next-best-actions مصوب.
3. self-monitoring protocol-aware با verification status.
4. inbox واحد تیم برای داده/پیام/درخواست بیمار.
5. caregiver access.
6. tenant capability/location model.
7. recommendation explainability و feedback taxonomy.
8. cohort workbench با assignment و escalation.

### P2 — رشد و تمایز

1. device adapters؛
2. secure messaging و asynchronous care؛
3. personalized education؛
4. behavioral experiments و adaptive engagement؛
5. FHIR-compatible export/integration؛
6. multi-location operations؛
7. patient-reported outcomes؛
8. ML risk models پس از ایجاد dataset و governance مناسب.

---

## ۱۱. معیارهای محصول

### North-star پیشنهادی

**نرخ حلقه‌های مراقبت واجد شرایط که در بازهٔ تعریف‌شده، با evidence کافی و نتیجهٔ ثبت‌شده بسته می‌شوند.**

این metric باید با safety guardrail همراه باشد؛ بستن سریع ولی اشتباه ارزش نیست.

### metric tree

```text
Eligible active chronic patients
→ care plans active
→ due activities created
→ patient reached / data submitted
→ reviewed within SLA
→ action completed
→ loop closed
→ sustained control / patient-reported benefit (later, with valid design)
```

### Guardrail metrics

- red flag missed/escalation delay؛
- unreviewed self-report age؛
- alert burden per clinician؛
- duplicate/unnecessary contact؛
- opt-out و complaint rate؛
- caregiver/privacy incident؛
- clinician override without reason؛
- cross-tenant security findings؛
- patient dropout و accessibility failure؛
- inequity by age/device/digital literacy.

### ادعاهای ممنوع پیش از مطالعه

- «کاهش قطعی عوارض»؛
- «کاهش بستری»؛
- «بهبود HbA1c/BP به مقدار مشخص»؛
- «افزایش درآمد تضمینی»؛
- «تشخیص هوشمند»؛
- «جایگزین پزشک».

برای pilot ابتدا adoption، timeliness، completion و usability سنجیده شوند؛ outcome بالینی با baseline، comparator/holdout و زمان کافی.

---

## ۱۲. آزمایش‌های محصول پیشنهادی پیش از توسعهٔ سنگین

1. **مصاحبهٔ workflow:** حداقل پزشک، منشی/پرستار، مدیر، بیمار و caregiver از چند نوع مرکز.
2. **Service blueprint:** یک هفتهٔ واقعی بیمار دیابت/فشار/قلب از ویزیت تا follow-up.
3. **Prototype test:** صفحهٔ «امروز» با کاربر سالمند و کم‌سواد؛ task completion و comprehension.
4. **Alert review workshop:** ۵۰ پیشنهاد واقعی/مصنوعی با پزشکان؛ actionable، redundant، unsafe، missing-context.
5. **Shadow care-loop:** تولید task بدون تماس واقعی؛ بررسی owner/SLA/حجم کار.
6. **Tenant variability study:** مطب تک‌پزشک، کلینیک تخصصی و درمانگاه چندشیفت.
7. **Accounting boundary workshop:** تصمیم revenue-cycle در برابر ERP/general-ledger.
8. **Caregiver consent test:** مدل grant و revoke با سناریوهای واقعی خانواده.
9. **Evidence traceability drill:** از کارت پیشنهاد تا guideline و rule version.
10. **Accessibility audit:** keyboard، screen reader، zoom، contrast، motor/cognitive load و گوشی ضعیف.

---

## ۱۳. دیدگاه‌های متعارض که باید حفظ شوند

### «داشبورد باید غنی باشد» در برابر «داشبورد باید ساده باشد»

حل: progressive disclosure؛ صفحهٔ اول action-first، جزئیات در لایه‌های بعد.

### «اتوماسیون بیشتر» در برابر «مسئولیت پزشک»

حل: اتوماسیون جمع‌آوری، اولویت‌بندی و draft؛ تصمیم درمانی human-in-the-loop و audit‌شده.

### «عمومی برای همهٔ کلینیک‌ها» در برابر «محصول بی‌هویت و قابل‌پیکربندی افراطی»

حل: هستهٔ ثابت care-loop + capability modules + program templates؛ نه workflow builder آزاد در فاز اول.

### «دادهٔ زیاد برای هوش آینده» در برابر «کمینه‌سازی داده»

حل: هر داده فقط با purpose، consent، retention و owner مشخص؛ telemetry محصول از PHI جدا.

### «درآمد تکرارشوندهٔ کلینیک» در برابر «اخلاق مراقبت»

حل: metric اصلی completion مراقبت؛ درآمد نتیجهٔ خدمت واقعی است، نه ایجاد تماس یا ویزیت غیرضروری.

---

## ۱۴. تصمیم‌های موقت این دور

این‌ها فرضیه‌های قوی برای دور بعد هستند، نه تصمیم معماری نهایی:

1. Patient Portal bounded context مستقل ساخته شود؛ کارت عمومی حفظ و محدود بماند.
2. CarePlan/Goal/Activity به هستهٔ دامنه افزوده شود؛ follow-up صرفاً task پراکنده نباشد.
3. موتور rule-based فعلی حفظ ولی با evidence registry، lifecycle و observability احاطه شود.
4. LLM ابتدا برای summarization/drafting/explanation استفاده شود، نه treatment selection.
5. Patient dashboard action-first و caregiver-aware طراحی شود.
6. چندمستأجری به location/capability/policy گسترش یابد.
7. accounting به‌عنوان clinic revenue-cycle تعریف شود مگر مالک عمداً general ledger کامل را انتخاب کند.
8. دیابت و فشارخون اولین programهای production-quality باشند؛ قلب با یک scope محدود و روشن مثل HF follow-up یا cardiometabolic risk شروع شود، نه عنوان مبهم «بیماری قلبی».
9. هر program باید clinical content package، care plan template، patient UX، team workflow، metrics و sign-off مستقل داشته باشد.

---

## ۱۵. نامعلوم‌های نیازمند دور بعد

- اولین ICP دقیق: مطب غدد، کلینیک cardiometabolic یا درمانگاه عمومی؟
- چه کسی در کلینیک واقعاً inbox بیمار را پاسخ می‌دهد؟
- SLA red flag و ساعت پوشش چیست؟
- آیا patient portal ابتدا اینترنتی، LAN، PWA یا ترکیبی است؟
- recovery بیمار در ایران با چه identity proofing عملی است؟
- scope بیماری قلبی در نسخهٔ اول دقیقاً چیست: HTN/ASCVD risk، HF، post-MI یا مجموعه‌ای مرحله‌ای؟
- آیا کلینیک حاضر به تأمین device است یا BYOD؟
- پیامک، تماس و push چگونه با consent و هزینه ترکیب می‌شوند؟
- pricing بر پایهٔ مرکز، staff، patient active یا program باشد؟
- کدام قابلیت حسابداری برای فروش عمومی ضروری و کدام باعث scope explosion است؟
- دادهٔ واقعی برای ارزیابی rule precision و workload چقدر داریم؟

---

## ۱۶. پیشنهاد موضوع دور دوم پژوهش

دور دوم بهتر است هم‌زمان سه artifact تولید کند:

1. **Patient Portal PRD + clickable information architecture**؛
2. **Clinical Program Contract برای دیابت و فشارخون** شامل dataset، plan، rule، workflow و metric؛
3. **Clinic Operating Model Matrix** برای مطب/کلینیک/درمانگاه و single/multi-location.

تا پیش از این سه artifact، شروع مستقیم UI نهایی خطر بازطراحی مجدد و ساخت dashboard زیبا ولی بی‌حلقه را دارد.

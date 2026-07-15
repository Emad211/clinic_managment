# دفتر پژوهش محصول حلقه

این پوشه حافظهٔ نسخه‌دار پژوهش محصول «حلقه» است. هر دور پژوهش باید پیش از تبدیل‌شدن به roadmap یا کد، در یک سند تاریخ‌دار ثبت و روی شاخهٔ فعال commit شود تا تصمیم‌ها به حافظهٔ گفتگو وابسته نباشند.

## هدف

حلقه باید از ادغام دو برنامهٔ قدیمی فراتر برود و به یک **سیستم‌عامل چندمستأجرهٔ مراقبت مزمن برای مطب، کلینیک و درمانگاه** تبدیل شود؛ با تمرکز آغازین بر دیابت، فشارخون و بیماری‌های قلبی‌عروقی، اما با معماری قابل‌گسترش به بیماری‌های دیگر.

تمایز موردنظر محصول:

```text
پرونده + عملیات کلینیک + حسابداری + برنامهٔ مراقبت
+ خودپایش بیمار + پیگیری انسانی + موتور پیشنهاد علمی
= حلقهٔ بستهٔ مراقبت
```

## روش هر دور پژوهش

هر دور باید حداقل این پنج زاویه را پوشش دهد:

1. **بیمار و همراه:** فهم‌پذیری، بار روزانه، اعتماد، دسترس‌پذیری، سواد سلامت و حق انتخاب.
2. **پزشک و تیم درمان:** ایمنی، واقع‌گرایی workflow، alert fatigue، قابلیت توضیح و مسئولیت انسانی.
3. **مدیر محصول و سرمایه‌گذار:** مسئلهٔ واقعی، تمایز، adoption، retention، unit economics و قابلیت فروش.
4. **معماری و مهندسی:** bounded context، چندمستأجری، امنیت، مقیاس، قابلیت آزمون و مهاجرت امن.
5. **بازار و رقبا:** قابلیت‌های استاندارد بازار، جای خالی واقعی و ادعاهایی که هنوز نیازمند اثبات‌اند.

## سلسله‌مراتب منبع

از قوی‌تر به ضعیف‌تر:

1. گایدلاین رسمی و استاندارد فنی؛
2. systematic review / meta-analysis / RCT؛
3. مطالعهٔ implementation، qualitative و usability؛
4. مستندات رسمی vendor برای شناخت قابلیت، نه اثبات اثر؛
5. مقالهٔ بازاری، خبر یا ادعای تبلیغاتی؛ فقط به‌عنوان فرضیه.

هر ادعای اثر بالینی یا اقتصادی باید از ادعای قابلیت محصول جدا شود. آمار vendor تا زمانی که مستقل تأیید نشده، با برچسب **vendor-reported** ثبت می‌شود.

## قرارداد تصمیم‌گیری

- موتور بالینی همیشه **suggestion-only** است؛ اقدام درمانی خودکار نمی‌شود.
- دادهٔ تأییدنشدهٔ بیمار وارد پیشنهاد بالینی نمی‌شود.
- هر rule باید منبع، نسخه، جمعیت هدف، موارد منع، تاریخ بازبینی و owner بالینی داشته باشد.
- dashboard بیمار باید «اقدام بعدی» را ساده کند، نه اینکه پروندهٔ پزشک را کوچک‌شده نمایش دهد.
- caregiver access باید رسمی، قابل ابطال و audit‌شده باشد؛ اشتراک رمز بیمار پذیرفته نیست.
- چندمستأجری فقط `tenant_id` نیست؛ تنظیم workflow، نقش، شعبه، کاتالوگ، payer و سیاست ارتباط نیز tenant-scoped است.
- Care Loop بدون owner، SLA، evidence و closure code کامل محسوب نمی‌شود.
- suggestion، decision، care plan و task موجودیت‌های جدا هستند.
- interruptive alert یک منبع کمیاب است و باید tier، suppression و budget داشته باشد.
- هیچ نتیجهٔ سلامت، ROI یا superiority پیش از دادهٔ پایلوت ادعا نمی‌شود.
- feature shipped با workflow adopted، service delivered، outcome improved یا economics sustainable برابر نیست.
- roadmap باید با evidence gate جلو برود، نه با تاریخ یا تعداد قابلیت.

## اسناد پژوهش

### دور اول

- [`2026-07-15_round-01_deep_product_research.md`](2026-07-15_round-01_deep_product_research.md): سنتز کلان محصول، UX، موتور بالینی، رقبا، چندمستأجری و gap map.

### دور دوم

- [`2026-07-15_round-02_closed_loop_dashboard_cds.md`](2026-07-15_round-02_closed_loop_dashboard_cds.md): سنتز عمیق Care Loop، داشبورد action-first، staff workbench، موتور علمی، multi-tenancy و ترتیب ساخت.
- [`2026-07-15_round-02_patient_portal_prd.md`](2026-07-15_round-02_patient_portal_prd.md): PRD پژوهشی پرتال احراز‌شدهٔ بیمار، صفحهٔ امروز، care plan، self-monitoring، پیام امن و caregiver access.
- [`CARE_LOOP_PRODUCT_BLUEPRINT.md`](CARE_LOOP_PRODUCT_BLUEPRINT.md): مفاهیم دامنه، stateها، closure contract، مسیر مهاجرت از FollowupTask و MVP حلقه‌بسته.
- [`COMPETITOR_CAPABILITY_MATRIX_2026.md`](COMPETITOR_CAPABILITY_MATRIX_2026.md): ماتریس MyChart، Omada، Dario، Welldoc، Cadence، Huma، Halqe فعلی و Halqe هدف.

### دور سوم

- [`2026-07-15_round-03_clinical_program_and_cds_governance.md`](2026-07-15_round-03_clinical_program_and_cds_governance.md): مدل Clinical Program، Evidence Package، Rule Version، Recommendation Instance، lifecycle علمی، shadow/pilot و governance چندبیماری.

### دور چهارم

- [`2026-07-15_round-04_multitenant_clinic_operating_model.md`](2026-07-15_round-04_multitenant_clinic_operating_model.md): مدل Tenant → Organization → Location → Department، capability packs، onboarding، revenue-cycle boundary، compensation و inventory اختیاری.

### دور پنجم

- [`2026-07-15_round-05_icp_strategy_roadmap_gates.md`](2026-07-15_round-05_icp_strategy_roadmap_gates.md): انتخاب موقت ICP، wedge، مزیت رقابتی، Product Pillars، dependency graph، roadmap outcome-based و build/defer/kill criteria.
- [`STRATEGY_SCORECARD_AND_RESEARCH_GATES.md`](STRATEGY_SCORECARD_AND_RESEARCH_GATES.md): scorecard segment و opportunity، gateهای problem/workflow/usability/pilot/CDS/repeatability/economics و template تصمیم.
- [`ROUND_05_FIELD_RESEARCH_PROTOCOL.md`](ROUND_05_FIELD_RESEARCH_PROTOCOL.md): نمونه‌گیری، راهنمای مصاحبه و مشاهده، case trace، time-and-motion، usability، pricing research و exit criteria اعتبارسنجی میدانی.

### رجیستر شواهد

- [`EVIDENCE_REGISTER.md`](EVIDENCE_REGISTER.md): رجیستر پایهٔ شواهد علمی، استانداردها، صفحات رسمی رقبا و شواهد کد.
- [`EVIDENCE_REGISTER_ROUND_02.md`](EVIDENCE_REGISTER_ROUND_02.md): الحاقیهٔ شواهد عملیات حلقه‌بسته، UX بیمار/همراه، حاکمیت CDS و gapهای مدل فعلی.
- [`EVIDENCE_REGISTER_ROUND_05.md`](EVIDENCE_REGISTER_ROUND_05.md): شواهد implementation، workload، economics، patient/caregiver adoption، pilot science و capability baseline جاری.

## وضعیت تصمیم راهبردی فعلی

فرضیهٔ اصلی دور پنجم:

```text
Primary ICP
= کلینیک تخصصی/چندتخصصی کوچک تا متوسط
  با پنل بالغ HTN/T2D یا cardiometabolic
  و یک نقش پاسخ‌گوی واقعی برای پیگیری

Initial wedge
= staff-owned Care Loops
  + owner / queue / SLA / evidence / closure
  + limited patient actions
  + governed CDS in shadow mode
```

این فرضیه هنوز با مصاحبه، مشاهده، usability، paid-pilot signal یا دادهٔ بازار ایران تأیید نشده است و نباید به‌عنوان PMF اعلام شود.

## وضعیت ابزار پژوهش

- کد و اسناد پروژه از شاخهٔ `agent/halqe-unified-migration-audit` خوانده شد.
- پژوهش دانشگاهی با Scholar Gateway انجام شد.
- سهمیهٔ جستجوی Consensus در این حساب تا ۱ اوت ۲۰۲۶ مصرف شده بود؛ replication با Consensus پس از بازشدن سهمیه در برنامه می‌ماند.
- منابع رسمی وب برای استانداردها، حاکمیت و capability mapping رقبا استفاده شدند.
- ادعاهای vendor از شواهد peer-reviewed جدا ثبت شدند.
- هیچ field interview، workflow observation، competitor demo یا usability study واقعی تا پایان Round 05 انجام نشده است.

## نحوهٔ افزودن دور بعدی

نام فایل:

```text
YYYY-MM-DD_round-NN_<topic>.md
```

هر دور باید این بخش‌ها را داشته باشد:

```text
سؤال پژوهش
وضعیت واقعی محصول
یافته‌های شواهد
دیدگاه‌های متعارض تیم
فرضیه‌های محصول
تصمیم‌های موقت
نامعلوم‌ها
آزمایش/تحقیق بعدی
```

هر تصمیم اجرایی باید علاوه بر سند پژوهش، یک Decision Unit، evidence level، metric، stop rule، owner و review date داشته باشد.

اسناد پژوهش، roadmap اجرایی یا دستور بالینی نیستند. تبدیل هر فرضیه به قابلیت نیازمند acceptance criteria، طراحی UX، threat model، review بالینی، evidence appraisal، instrumentation، آزمایش و تست است.

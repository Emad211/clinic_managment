# برنامهٔ سخت‌سازی موتور بالینی و کل Specialist Clinic

> وضعیت: در حال اجرا  
> مبنا: Clinical Engine v2 موجود در `specialist_clinic/`  
> اصل ثابت: تصمیم‌یار است، نه مجری خودکار تشخیص، نسخه، ارجاع یا درمان  
> خارج از اولویت فعلی: توسعهٔ Rule Library و افزودن محتوای بالینی جدید

## ۱. هدف

این برنامه فقط بازنویسی evaluator نیست. هدف آن است که کل اپلیکیشن، از لحظهٔ ثبت داده تا نمایش پیشنهاد، تصمیم پزشک، ایجاد task، پیامک، نوبت، audit، backup و rollback، دارای رفتار قابل‌تکرار، قابل‌ممیزی و fail-closed باشد.

اپ برای بیماری‌های عمومی و مزمن استفاده می‌شود؛ مسیر بیماری مزمن باید عمیق‌تر، طولی‌تر و دقیق‌تر باشد، اما هیچ rule عمومی یا مزمنی نباید بدون قرارداد داده، provenance، freshness و activation مشخص اجرا شود.

## ۲. اصول غیرقابل مذاکره

1. **هیچ خروجی قدیمی نمایش داده نمی‌شود.** هر output باید به revision فعلی پرونده، build فعلی موتور و ruleset دقیق bind باشد.
2. **نبود داده با منفی‌بودن یکی نیست.** `UNKNOWN / NOT_ASKED / ABSENT / STALE / CONFLICTING / ERROR` از هم جدا می‌مانند.
3. **هر اقدام بالینی واقعی رویداد مستقل دارد.** قبول پیشنهاد مساوی با اجرای درمان نیست.
4. **مسیرهای ایمنی fail-closed هستند.** خطای داده یا زیرسامانه نباید خروجی روتینِ ظاهراً مطمئن تولید کند.
5. **نسخه‌های Rule و Ruleset immutable هستند.** artifact قبلی اصلاح درجا نمی‌شود.
6. **تست و activation به همان artifact و build متصل‌اند.** تغییر compiler، adapter یا evaluator، شواهد قبلی را معتبر نگه نمی‌دارد.
7. **منطق بالینی خارج از v2 نیز inventory و govern می‌شود.** analytics، risk score، dosage guidance و engagement threshold استثنا نیستند.
8. **SQL state-changing در repository می‌ماند.** route فقط orchestration درخواست/پاسخ است.
9. **زمان تهران، تاریخ ذخیره‌شدهٔ میلادی و UI جلالی حفظ می‌شود.**
10. **Rollback باید فوری، قابل‌آزمون و بدون حذف audit باشد.**

---

# فاز ۰ — خط مبنا، شاخه و ایمنی تغییر

## کارها

- شاخهٔ مستقل برای هر tranche و Draft PR.
- اجرای کامل pytest برای `specialist_clinic` و `webapp` در CI.
- ثبت commit/build hash در گزارش تغییر.
- ممنوعیت merge با test failure یا migration بدون تست copied-existing-DB.
- هر migration فقط additive و idempotent.

## معیار پذیرش

- [ ] هر دو suite در CI سبز است.
- [ ] هیچ تستی دیتابیس واقعی یا provider واقعی پیامک را لمس نمی‌کند.
- [ ] rollback کد و rollback runtime جداگانه مستند است.

---

# فاز ۱ — Runtime Freshness و Current-Run Contract

## مسئله

پیش از این، آخرین run پایگاه داده می‌توانست با وجود تغییر پرونده، ruleset دیگر یا حتی legacy import به UI و decision/follow-up برسد.

## طراحی

### ۱.۱ Clinical Data Revision

برای هر بیمار یک شمارندهٔ monotonic:

```text
patient_links.clinical_data_revision
```

منابعی که revision را افزایش می‌دهند:

- هویت بالینی مؤثر: تاریخ تولد، جنس
- diagnosisها
- medicationها
- allergyها
- clinical flagها
- vitalها
- labها

تغییر revision باید با trigger دیتابیس انجام شود تا هیچ route، importer، seed یا job نتواند آن را فراموش کند.

### ۱.۲ CurrentRunKey

```text
patient_link_id
+ clinical_data_revision
+ engine_version/build_hash
+ ruleset_id/content_hash
```

### ۱.۳ مصرف‌کنندگان مجاز

فقط این قرارداد می‌تواند توسط موارد زیر مصرف شود:

- صفحهٔ بیمار
- ثبت تصمیم پزشک
- ساخت clinical follow-up
- گزارش activation
- APIهای آینده

### ۱.۴ race safety

Presentation، decision و task creation باید در transaction قفل‌دار، revision واقعی بیمار را دوباره بررسی کنند.

## معیار پذیرش

- [x] revision و triggerهای منابع بالینی
- [x] snapshot شامل revision
- [x] run selection بر اساس engine/ruleset/revision
- [x] legacy import نمی‌تواند run جاری را mask کند
- [x] presentation stale رد می‌شود
- [x] decision stale رد می‌شود
- [x] task stale رد می‌شود
- [x] scheduler فقط current-run task تولید می‌کند
- [ ] run creation در برابر چند درخواست هم‌زمان idempotent شود
- [ ] runهای `RUNNING` رهاشده recovery شوند
- [ ] schema.sql و migration path یک source-of-truth واحد شوند

---

# فاز ۲ — قرارداد Facts، Reconciliation و Historical As-Of

## ۲.۱ Provenance

هر observation باید source واقعی خود را حفظ کند:

```text
clinic / laboratory / patient / caregiver / device / imported
```

Self/home/device نباید خودکار `CONFIRMED` شود.

## ۲.۲ Collection semantics

برای medication، allergy، problem list و vaccination:

```text
UNKNOWN             هنوز مرور نشده
PRESENT(items)      اقلام ثبت و مرور شده
ABSENT               مرور شد و موردی وجود ندارد
STALE                مرور قدیمی است
CONFLICTING          منابع ناسازگارند
```

لیست خالی دیتابیس به‌تنهایی معادل reconciliation نیست.

## ۲.۳ Reconciliation events

جدول/رویدادهای مستقل:

```text
medication_reconciliation
allergy_reconciliation
problem_list_reconciliation
vaccination_reconciliation
```

فیلدها:

```text
patient, reconciled_at, actor, source, completeness,
patient_confirmed, note, content_hash
```

## ۲.۴ Vocabulary

- medication با concept ID و class canonical، نه متن آزاد به‌عنوان هویت.
- lab با `test_key` canonical؛ legacy name mapping گزارش‌شده و قابل بازبینی.
- diagnosis با code canonical.
- unit normalization registry با خطای صریح برای unit ناشناخته.

## ۲.۵ Historical As-Of

Snapshot تاریخی نباید وضعیت فعلی medication/flag/diagnosis را به گذشته ببرد. برای هر منبع باید effective interval یا event history وجود داشته باشد.

## معیار پذیرش

- [x] source فشار self-reported به‌صورت provisional حفظ می‌شود
- [ ] empty collection بدون reconciliation، UNKNOWN است
- [ ] medication list دارای freshness واقعی است
- [ ] allergy/problem-list reconciliation پیاده‌سازی شده است
- [ ] labهای legacy دارای mapping report هستند
- [ ] historical medication/condition/flag replay درست است
- [ ] duplicate active diagnosis با constraint یا canonical dedupe کنترل می‌شود

---

# فاز ۳ — Applicability، Scope و Safety Semantics

## ۳.۱ Applicability

هر rule باید eligibility executable داشته باشد. `scope` توصیفی به‌تنهایی کافی نیست.

حداقل ابعاد:

- سن کامل
- جنس، در صورت مرتبط بودن
- condition codes
- care setting
- encounter type
- وضعیت‌های out-of-scope machine-readable

## ۳.۲ ترتیب داده

دادهٔ پرهزینه/وابسته فقط پس از اثبات eligibility مطالبه شود. مثال:

```text
دیابت + مصرف متفورمین -> سپس eGFR لازم است
```

نه:

```text
هر بیمار دیابتی -> همیشه eGFR برای rule متفورمین لازم است
```

## ۳.۳ Safety truth preservation

اگر یک شاخهٔ Red Flag قطعاً TRUE و شاخهٔ دیگر ERROR باشد، هشدار مثبت نباید ناپدید شود. خروجی باید هم هشدار و هم مشکل داده را حفظ کند.

## ۳.۴ Cross-rule safety dependencies

هر `suggest_med` وابسته باید blockerهای safety شناخته‌شده را executable داشته باشد. تعارض action type با semantic key مشترک باید در compile/activation رد شود، نه اینکه safety output در runtime حذف شود.

## معیار پذیرش

- [x] diagnosis eligibility از `condition.codes` استفاده می‌کند
- [x] بزرگسال‌بودن در eligibility دو rule فعلی اجرا می‌شود
- [x] مصرف متفورمین پیش از مطالبهٔ eGFR اثبات می‌شود
- [ ] care setting و encounter type executable است
- [ ] out-of-scope ساختاری است
- [ ] known-positive Red Flag با خطای شاخهٔ دیگر حفظ می‌شود
- [ ] dependency matrix ایمنی در compiler بررسی می‌شود

---

# فاز ۴ — Activation، Governance و Pilot واقعی

## ۴.۱ Build-bound seal

Seal باید به این موارد bind شود:

```text
application_commit
engine_build_hash
compiler_hash
evaluator_hash
adapter_hash
rule_schema_hash
fact_schema_hash
ruleset_content_hash
golden_matrix_hash
```

SHA-256 ساده integrity check است، نه signature. Threat model و نیاز به HMAC/signature باید صریح باشد.

## ۴.۲ Golden Outcome Matrix

فقط positive control کافی نیست:

```text
patient × rule -> expected outcome
```

شامل:

- FIRED
- NOT_FIRED
- NOT_APPLICABLE
- NEEDS_DATA
- SUPPRESSED
- ERROR = ممنوع برای activation

## ۴.۳ Cognitive burden

تمام cardها و noticeها شمرده شوند، نه فقط FIRED recommendationها.

## ۴.۴ Approval identity

- approval به user ID احراز‌شده bind شود.
- reviewer بالینی و فنی مستقل باشند.
- role و permission واقعی کنترل شود.
- approval append-only باشد، نه overwrite settings.

## ۴.۵ Pilot واقعی

`on_selected` نباید فقط TEST0001..10 باشد. cohort واقعی قابل انتخاب، consent/policy، observation window و metrics لازم است.

Metrics:

```text
presentation count
stale-run count
error/needs-data rate
accept/dismiss/defer distribution
false-positive review
clinician burden
rollback trigger
```

## معیار پذیرش

- [ ] full golden matrix
- [ ] build-bound seal
- [ ] authenticated independent approvals
- [ ] real selected cohort
- [ ] measurable selected verification
- [ ] rollback drill ثبت‌شده

---

# فاز ۵ — یکپارچه‌سازی منطق‌های بالینی موازی

## Inventory اجباری

### فعلی

- `clinical_indicators`
- control status
- analytics risk score
- per-disease risk
- dosage guidance از legacy `clinical_rules`
- engagement uncontrolled thresholds
- insulin calculator
- refill/lapsed heuristics
- Control Room prioritization

## طبقه‌بندی

```text
A. نمایش دادهٔ خام
B. descriptive analytics
C. منطق اداری
D. clinical decision support
E. safety-critical decision support
```

D و E باید version، provenance، governance و audit داشته باشند. B باید برچسب توصیفی داشته باشد و با recommendation اشتباه نشود.

## معیار پذیرش

- [ ] inventory کامل UI/API/job
- [ ] threshold sourceهای موازی حذف یا versioned شوند
- [ ] analytics توصیفی از CDS بصری و قراردادی جدا شود
- [ ] dosage guidance حساس به موتور governشده منتقل شود
- [ ] engagement بالینی فقط از current-run output استفاده کند

---

# فاز ۶ — Closed Care Loop

## چرخه

```text
fact -> evaluation -> recommendation -> presentation -> clinician decision
-> real action -> fulfillment/outcome -> new fact -> reevaluation
```

## رویدادهای لازم

```text
SUPERSEDED
INVALIDATED_BY_DATA_CHANGE
EXPIRED
RESOLVED_BY_ACTION
OVERRIDDEN
```

Medication change، prescription، referral، appointment، test order و task resolution باید بتوانند به recommendation منشأ لینک شوند.

## Follow-up identity

Task دوره‌ای نیازمند episode/period مشخص است؛ نه تکرار دائمی و نه suppression همیشگی بر اساس evidence ID قدیمی.

## معیار پذیرش

- [ ] action provenance
- [ ] fulfillment link
- [ ] recommendation lifecycle
- [ ] recurring due-period identity
- [ ] remote/in-person closure audit

---

# فاز ۷ — سخت‌سازی کل اپلیکیشن

## ۷.۱ Security

- CSRF برای تمام mutationهای session-based
- حذف/اجبار تغییر `admin/admin` در production bootstrap
- rate limit و lockout verification
- role/permission matrix برای clinical approval و manager actions
- secret/key redaction در log و UI
- session fixation/logout tests
- public patient-card threat model و token rotation

## ۷.۲ Database integrity

- حذف migrationهای safety-critical با `except: pass`
- foreign key و partial unique indexهای clinical
- transaction boundary مشخص برای aggregate mutation
- schema version table
- migration copy-of-real-shape tests
- integrity check پیش و پس از backup/restore

## ۷.۳ Scheduler و multi-process

- singleton lease در DB، نه فقط thread-local flag
- job ledger و idempotency key
- heartbeat، last success، next retry و alert
- recovery برای run/job نیمه‌کاره
- shutdown تمیز scheduler

## ۷.۴ Observability

- structured log با patient-safe identifiers
- dashboard سلامت موتور
- counters برای stale, error, needs-data, suppressed
- latency و DB contention
- audit export و retention policy

## ۷.۵ Performance

- index review برای patient page و current-run query
- جلوگیری از N+1 در dashboard/control room
- bounded history reads
- SQLite WAL/busy-timeout policy تحت تست concurrency

## ۷.۶ UI/Accessibility

- stateهای loading/error/stale صریح
- عدم نمایش «اعمال شد» برای decision-only
- نمایش as-of، source و freshness قابل فهم
- keyboard/RTL/Jalali regression
- چاپ و export امن

## ۷.۷ Backup و Disaster Recovery

- backup checksum
- restore drill خودکار روی DB موقت
- نگهداری نسخه و schema metadata
- گزارش آخرین restore verification

---

# فاز ۸ — توسعهٔ Rule Library، فقط پس از پایان Hardening

افزودن قواعد عمومی و مزمن زمانی آغاز می‌شود که فازهای ۱ تا ۴ کامل و فازهای ۵ تا ۷ حداقل دارای gate لازم باشند.

برای هر rule جدید:

1. evidence review و citation audit
2. owner/physician decisions
3. machine-readable eligibility و safety exclusions
4. canonical facts و units
5. golden positives و negatives
6. conflict/dependency analysis
7. clinician review
8. shadow evaluation
9. real pilot
10. activation و monitoring

---

# ترتیب Pull Requestها

## PR-A — Runtime Freshness Foundation

- revision triggers
- revisioned snapshot
- strict current-run repository
- current facade/decision/task
- daily current clinical follow-up
- regression tests

## PR-B — Fact Reconciliation and Historical Correctness

- medication/allergy/problem-list reconciliation
- concept IDs
- lab legacy mapping
- historical event intervals

## PR-C — Executable Scope and Safety Semantics

- context facts
- scope evaluator
- known-positive redflag preservation
- safety dependency compiler

## PR-D — Activation Evidence and Real Pilot

- golden matrix
- build-bound report/seal
- append-only authenticated approvals
- selected cohort metrics

## PR-E — Parallel Clinical Logic Consolidation

- analytics/CDS boundary
- threshold governance
- legacy runtime retirement completion

## PR-F — Application Security, Scheduler and Recovery

- CSRF
- production bootstrap
- singleton scheduler/job ledger
- stuck-run recovery
- restore drill

---

# Definition of Done برای هر PR

- [ ] migration روی DB تازه و کپی DB موجود
- [ ] unit + integration + concurrency tests
- [ ] no silent exception در مسیر safety-critical
- [ ] activity/audit event مناسب
- [ ] rollback path
- [ ] UI stale/error state
- [ ] PyInstaller bundle بررسی شده
- [ ] docs و graphify به‌روزرسانی شده
- [ ] CI هر دو اپ سبز
- [ ] هیچ ادعای بالینی جدید بدون review انسانی وارد نشده است

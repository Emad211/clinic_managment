# Completeness، provenance و حل تعارض داده‌های بالینی

## اصل ایمنی

هیچ منبعی صرفاً به‌دلیل جدیدتر بودن row، نام جدول یا ترتیب import بر منبع دیگر
برتری پنهان ندارد. هرگاه دو assertion مؤثر دربارهٔ یک مفهوم canonical با یکدیگر
ناسازگار باشند، موتور باید تا ثبت resolution صریح abstain کند:

```text
unresolved conflict
→ source rows suppressed
→ aggregate fact UNKNOWN
→ verification UNVERIFIED
→ conflict PRESENT
→ rule result NEEDS_DATA
```

GET یا projection فقط conflict را محاسبه می‌کند و event جدیدی نمی‌سازد.

## دامنهٔ فعلی

قرارداد روی سه collection اجرا می‌شود:

- conditions، بر پایهٔ `conditions.code`
- medications، بر پایهٔ `drug_catalog_id`
- allergies، بر پایهٔ `allergy_catalog.concept_key`

دادهٔ فاقد concept mapping حذف یا حدس زده نمی‌شود. آن داده با کلید صریح
`unmapped-*` باقی می‌ماند و collection را برای تصمیم‌گیری کامل نمی‌کند.

## provenance هر candidate

هر source row این فیلدها را نگه می‌دارد:

```text
source_system
source_record_id
source_assertion = PRESENT | ABSENT | UNKNOWN
verification = CONFIRMED | PROVISIONAL | UNVERIFIED | REFUTED
recorded_by
```

`source_record_id` شناسهٔ پایدار همان رکورد در منبع مبدا است. تغییر مقدار candidate
بدون تغییر این شناسه، `candidate_set_hash` را تغییر می‌دهد و resolution قبلی را stale
می‌کند.

## conflict group

تمام candidateهای مؤثر یک بیمار برای یک مفهوم canonical در یک group قرار می‌گیرند.
دلایل conflict عبارت‌اند از:

```text
SOURCE_ASSERTION_UNKNOWN
ASSERTION_DISAGREEMENT
CLINICAL_DETAIL_DISAGREEMENT
```

candidate set به‌صورت canonical مرتب و hash می‌شود. در نتیجه ترتیب rowها یا ترتیب
خواندن دیتابیس بر نتیجه اثر ندارد.

## ledger حل تعارض

`clinical_data_conflict_events` یک ledger append-only است:

```text
OPENED / REOPENED
→ RESOLVED
→ در صورت تغییر candidateها resolution قبلی stale است
```

- UPDATE و DELETE ممنوع است.
- هر group دقیقاً یک root و حداکثر یک child برای هر event دارد.
- event جدید باید head جاری همان بیمار، collection و concept را supersede کند.
- `recorded_at` نمی‌تواند در زنجیره به عقب حرکت کند.
- ثبت resolution با `BEGIN IMMEDIATE` و optimistic concurrency انجام می‌شود.

## روش‌های resolution

### SELECT_CANDIDATE

یک candidate دقیق انتخاب می‌شود. فقط همان source row برای projection قابل استفاده
است و verification آن به‌واسطهٔ resolution بالینی تأیید می‌شود.

### MERGE_CANDIDATES

حداقل دو candidate با فیلدهای مکمل ادغام می‌شوند. اگر دو candidate برای یک فیلد
بالینی مقادیر متفاوت داشته باشند، merge رد می‌شود؛ سیستم مقدار برنده را حدس نمی‌زند.

### CONFIRMED_ABSENT

پزشک نبود مفهوم را صریحاً تأیید می‌کند. این state با UNKNOWN تفاوت دارد و aggregate
می‌تواند ABSENT + CONFIRMED شود.

### MARK_UNKNOWN

پس از مرور، پاسخ معتبر هنوز معلوم نیست. aggregate برابر UNKNOWN باقی می‌ماند اما
دلیل آن یک resolution صریح و قابل‌ممیزی است.

## completeness و reconciliation

هر reconciliation event علاوه بر item snapshot، موارد زیر را ثبت می‌کند:

```text
conflict_snapshot_hash
conflict_count
unresolved_conflict_count
mapping_complete
reviewed_sources_json
```

ثبت `completeness=complete` در حضور conflict حل‌نشده ممنوع است. current بودن review
نیز به conflict snapshot وابسته است؛ تغییر candidateها review قبلی را منسوخ می‌کند.

## allergy concepts

`allergy_catalog` فقط exact alias mapping انجام می‌دهد. fuzzy matching در مسیر ایمنی
وجود ندارد. alias مبهم یا substance ناشناخته unmapped باقی می‌ماند. cohort مصنوعی
فقط زمانی آماده است که تمام allergyهای فعال دقیقاً به یک concept فعال متصل باشند.

## اثر بر Clinical Engine

engine identity این قرارداد:

```text
2.7.0-data-conflicts
```

FactBuilder فقط projection reconciled و conflict-aware را مصرف می‌کند. هیچ adapter
قدیمی اجازه ندارد source rows متعارض را به‌صورت last-row-wins یا source-priority به
Fact PRESENT تبدیل کند. run، report و activation seal build قبلی برای این semantics
معتبر نیستند.

## دروازهٔ انتشار گام چهارم

این tranche زمانی بسته است که حداقل این سناریوها عبور کنند:

- PRESENT در برابر ABSENT و دو detail متفاوت به conflict تبدیل شوند.
- aggregate و specific facts conflict حل‌نشده را مصرف نکنند.
- SELECT، MERGE، ABSENT و UNKNOWN semantics مستقل داشته باشند.
- stale candidate hash یا stale head هیچ event جزئی ثبت نکند.
- تغییر candidate، resolution قبلی را خودکار stale کند.
- GET conflict event نسازد.
- staff فقط مشاهده کند و manager resolution ثبت کند.
- copied database provenance و allergy concept mapping را idempotent مهاجرت دهد.
- cohort مصنوعی zero unmapped allergy و zero unresolved conflict داشته باشد.

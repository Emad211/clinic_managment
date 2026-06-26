# ADR-0005 — «Observation» مفهومِ کانونیک روی کانال‌های `vital_readings` + `lab_results`

- **وضعیت:** پذیرفته‌شده (۱۴۰۵/۰۳/۳۱).
- **زمینه‌ساز:** فیچرِ C — بازگشتِ نتیجهٔ آزمایش به موتور (بستنِ حلقهٔ مراقبت).
- **فرآیند:** مشورتِ تیم (principal-architect + clinical-product) با راستی‌آزماییِ کد.

## زمینه
موتور و لایهٔ تحلیل «آخرین انجام / وضعیتِ کنترل» را **فقط از `vital_readings`** می‌خواندند (`followup_engine._last_done`، `vitals_service.control_status` via `latest_by_type`، `rule_engine.build_facts`، `analytics_service._risk` lapsed). اما ثبتِ آزمایش از قبل وجود دارد (`vitals.py add_lab` → `lab_results`، با کاتالوگِ `lab_test_catalog`). نتیجه: یک HbA1c که به‌صورتِ **آزمایش** ثبت شود، نه recallِ `monitoring_due` را می‌بست و نه در وضعیتِ کنترل/ریسک دیده می‌شد — موتور نسبت به نتایجِ آزمایشگاهی **کور** بود و recall بی‌خود دوباره fire می‌کرد.

کشفِ کلیدی: `lab_test_catalog.test_key` (`hba1c`,`fbs`,`ldl`,`egfr`,`uacr`,`tsh`,…) **هم‌واژگانِ** `vital_readings.type` است — یعنی یک کلیدِ کانونیکِ مشترک از قبل وجود دارد، فقط متصل نبود.

## تصمیم
`vital_readings` و `lab_results` **دو Channel-of-Captureِ یک مفهومِ کانونیکِ واحد** («Observation» — مشاهدهٔ بالینیِ زمان‌دار) هستند، با کلیدِ کانونیکِ مشترک `test_key == vital_readings.type`. موتور روی **مفهومِ کانونیک** کار می‌کند، نه جدولِ فیزیکی. (الگوی FHIR `Observation`.)

- **دو جدولِ فیزیکیِ مجزا می‌مانند** (معناشناسیِ متفاوت: `vital_readings` شاملِ فشار/وزن که lab نیستند؛ `lab_results` با `ref_low/ref_high` و کاتالوگ). **نه ادغامِ جداول، نه dual-write** (هر دو = منبعِ حقیقتِ کثیف).
- **یک لایهٔ خواندنِ کانونیک** روی هر دو UNION می‌زند: `VitalsRepository.latest_by_type` (آخرین به‌ازای هر کلید، در هر دو کانال) — که `control_status`، کارتِ بیمار، و `rule_engine` خودکار سازگار می‌شوند؛ `followup_engine._last_done` و `analytics._risk` (lapsed) هم اتحادِ مخصوصِ خود را می‌زنند.
- **مطابقت فقط با `test_key`** (ستونِ نوِ `lab_results.test_key`)، **نه `test_name`ِ آزاد** (داده‌ٔ کثیف/فارسی match نمی‌شود). آزمایشِ خارج از کاتالوگ (`test_key` تهی) عمداً recall را نمی‌بندد (محافظه‌کارانه و درست).
- **آستانه‌ها فقط از `clinical_indicators`** (قانونِ threshold-sync). `lab_test_catalog.ref_low/ref_high` = دامنهٔ مرجعِ جمعیتی برای **نمایش**، نه هدفِ درمانی؛ هرگز در ارزیابیِ danger/warn دخالت نمی‌کند.
- **قراردادِ قفل‌شده:** واژگانِ `test_key` باید برای همیشه با `vital_readings.type` (و `clinical_indicators.key`) هم‌تراز بماند — هم‌ردهٔ threshold-sync rule. واگراییِ کلید = شکستنِ اتحاد.

## محدودهٔ پیاده‌شده (این فاز)
ستونِ `lab_results.test_key` (schema + `_ensure_column`، nullable، بدونِ backfill) · سیمِ `test_key[]` از فرم در `add_lab` (route+repo) · اتحادِ کانونیک در `latest_by_type` (→ control_status/کارت/rule_engine) · `_last_done` و `_risk` lapsed اتحادِ هر دو کانال.

## خارج از scope (ثبت‌شده برای آینده)
- ~~نمودارهای روند (`analytics.patient_analytics` series) و `medication_effect`~~ **✅ انجام شد** (پاسِ بعدی): `VitalsRepository.get_readings_canonical(pid, key)` سری را روی هر دو کانال می‌دهد و `patient_analytics` + `medication_effect` از آن می‌خوانند — تناقضِ **on-page** (کنترل می‌گفت uncontrolled ولی کاشی/نمودار خالی) رفع شد. (تیم در بازبینیِ میلستون این را on-page یافت، نه on-demand.)
- ستونِ `lab_results.source` + سیاستِ staleness (آزمایشِ ۱۱‌ماهه آیا «کنترل‌شده»؟) — **تأییدِ پزشک**.
- گسترشِ P1 آیتم→آزمایش: `renal`+`creatinine`، `lipid`+`chol_total`، افزودنِ `potassium` — **تأییدِ پزشک**.
- backfillِ best-effortِ `test_name`→`test_key` رکوردهای قدیمی (اختیاری).
- ادغامِ فیزیکی به جدولِ `observations` در مهاجرتِ Postgres/Timescale (تریگرِ Strangler).

## پیامدها
+ حلقهٔ مراقبت واقعاً بسته می‌شود (آزمایش = ویزیت‌محور برای «انجام‌شده»)؛ موتور/کنترل/ریسک/کارت همگی سازگار. − انضباطِ هم‌کلیدیِ `test_key`↔`type` باید نگه داشته شود؛ آزمایشِ بدونِ کاتالوگ recall نمی‌بندد (پذیرفته).

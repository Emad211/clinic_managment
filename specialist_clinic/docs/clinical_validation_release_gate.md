# دروازهٔ نهایی اعتبارسنجی و انتشار موتور بالینی

## اصل انتشار

هیچ package قاعده‌ای فقط با compileشدن، اجرای چند کنترل مثبت یا تغییر raw mode قابل
انتشار نیست. زنجیرهٔ رسمی نسخهٔ جاری:

```text
compile immutable package
→ structural validation
→ semantic golden cases
→ deterministic replay
→ package metrics
→ exact ruleset identity comparison
→ activation cohort report
→ clinical attestation
→ technical attestation
→ audit checkpoint
→ selected rollout
→ monitored global activation
```

هر mismatch در package، case bundle، rule identity، activation report، attestation یا
checkpoint، mode مؤثر را به `off` برمی‌گرداند.

## Golden Case

فایل canonical کیس‌ها کنار package قرار دارد:

```text
src/domain/clinical_engine/rule_artifacts/2026.1-draft.2/validation-cases.json
```

هر کیس دارای این قرارداد است:

```text
case_id
categories
fixed as_of_at
exact evaluation context
canonical facts with provenance and quality
exact expected outcome per rule
recommendation presence assertions
missing-fact assertions
trace fact-id assertions
suppression / routine-blocking assertions
run-level safety assertions
```

دسته‌های اجباری:

```text
positive
negative
borderline
missing-data
conflict
historical-as-of
contraindication
suppression
```

نبود حتی یک دسته، گزارش package را `BLOCKED` می‌کند.

## بازپخش قطعی

هر snapshot دو بار با همان package اجرا می‌شود. hash خروجی‌ها باید یکسان باشد. تفاوت در
outcome، missing facts، suppression، trace، recommendation presence یا run status شکست
release است.

## Metrics

در سطح هر rule و کل package ثبت می‌شود:

```text
true_positive
true_negative
false_positive
false_negative
needs_data
error
suppressed
not_applicable
```

release پایه نیازمند این شرایط است:

```text
zero false-positive
zero false-negative
zero ERROR
positive case for every rule
negative case for every rule
all semantic assertions pass
```

## Newest-report-wins

فقط جدیدترین report مربوط به engine/package دقیق می‌تواند evidence باشد. اگر پس از یک
`PASS`، report جدید `BLOCKED` ثبت شود، PASS قدیمی فوراً غیرقابل‌مصرف است. پس از رفع مشکل
باید report PASS جدید ساخته شود.

## Reports و attestations

این جدول‌ها append-only هستند:

```text
clinical_validation_reports
clinical_validation_attestations
```

UPDATE و DELETE در SQLite ممنوع است. `status` داخل `report_hash` قرار دارد و repository
اجازه نمی‌دهد وضعیت گزارش با checks آن ناسازگار باشد.

Clinical و Technical reviewer باید دو فرد متفاوت باشند. هر attestation به این هویت دقیق
متصل است:

```text
validation report id/hash
activation report hash
package hash
case bundle hash
role
reviewer
note
content hash
```

## اتصال بدون مسیر موازی به UI فعلی

کاربر همان wizard موجود را طی می‌کند:

1. package را آماده و قواعد را مرور می‌کند.
2. cohort مصنوعی را آماده می‌کند.
3. دکمهٔ «اجرای آزمون ۱۰ بیمار نمونه» را می‌زند.
4. سیستم Golden Caseها را نیز اجرا و report را به activation report متصل می‌کند.
5. فرم تأیید بالینی، attestation بالینی immutable می‌سازد.
6. فرم تأیید فنی، attestation فنی immutable می‌سازد.
7. activation seal فقط پس از وجود هر دو attestation ساخته می‌شود.

جزئیات کیس‌ها، outcomeها، معیارها و hashها در همان صفحهٔ موتور قابل مشاهده و جست‌وجو است.

## اتصال به audit و readiness

validation reportها و attestationها در scope checkpoint قرار دارند. seal به checkpoint
جدیدی متصل می‌شود که این جدول‌ها را نیز پوشش می‌دهد. دست‌کاری آفلاین evidence مهرشده،
`valid_seal` را fail-closed می‌کند.

Readiness نیز وجود storage validation و اعتبار seal را بررسی می‌کند، بدون نمایش PHI،
path، secret یا exception عمومی.

## مرز بالینی

Golden Caseها قرارداد فنی و semantic مورد انتظار را اثبات می‌کنند، نه صحت علمی threshold.
هر rule جدید همچنان نیازمند evidence extraction، clinical review، source locator و
package version جدید است. تغییر threshold باید case bundle و تمام gateهای انتشار را نیز
دوباره طی کند.

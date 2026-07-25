# دروازهٔ اعتبارسنجی و انتشار بسته‌های بالینی

## هدف

هیچ package قاعده‌ای فقط با compileشدن یا چند تست مثبت قابل انتشار نیست. هر نسخهٔ
immutable باید به ترتیب زیر عبور کند:

```text
compile
→ structural validation
→ semantic golden cases
→ deterministic replay
→ metrics and failure analysis
→ clinical attestation
→ technical attestation
→ shadow comparison
→ selected rollout
→ monitored global activation
```

## Golden case

هر case دارای این قرارداد است:

```text
case_id
categories
as_of_at
exact evaluation context
canonical facts + provenance/quality
exact expected outcome per rule
missing-fact assertions
suppression assertions
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

## Deterministic replay

هر snapshot دقیقاً دو بار با همان package اجرا می‌شود. hash خروجی‌ها باید یکسان باشد.
تفاوت در outcome، missing facts، suppression، provenance trace یا run status شکست
release است.

## Metrics

برای انتظارهای دودویی، معیارهای زیر در سطح rule و package ثبت می‌شوند:

```text
true_positive
true_negative
false_positive
false_negative
```

Abstentionها جدا هستند:

```text
NEEDS_DATA
ERROR
SUPPRESSED
NOT_APPLICABLE
```

release پایه به zero false-positive، zero false-negative و zero ERROR نیاز دارد. هر
قاعده باید حداقل یک positive و یک negative case صریح داشته باشد.

## Reports و attestations

`clinical_validation_reports` و `clinical_validation_attestations` append-only هستند.
گزارش شامل hash package، hash case bundle، metrics، failureها و result hash هر case
است. Clinical و Technical reviewer باید دو فرد متفاوت باشند. تغییر انتظار یا package
گزارش و attestation قبلی را برای نسخهٔ جدید بی‌اعتبار می‌کند.

## اتصال به activation

Activation report شناسه و hash validation report را در immutable report hash خود حمل
می‌کند. Activation seal نیز به همان report، package hash و دو attestation متصل است.
`valid_seal` در هر بار استفاده، reference را دوباره بررسی می‌کند.

```text
missing/blocked validation
or missing independent attestations
or package/bundle/hash mismatch
→ activation blocked
→ effective mode = off
```

Validation tables داخل clinical audit checkpoint نیز قرار می‌گیرند؛ دست‌کاری آفلاین
یک گزارش یا attestation مهرشده، seal را fail-closed می‌کند.

## مرز بالینی

Golden caseها قرارداد فنی و semantic مورد انتظار را اثبات می‌کنند، نه صحت علمی
thresholdها. هر قاعدهٔ جدید همچنان به evidence extraction، clinical review و منبع
قابل استناد نیاز دارد. تغییر threshold یک package version جدید، case bundle جدید و
تمام gateهای انتشار جدید می‌خواهد.

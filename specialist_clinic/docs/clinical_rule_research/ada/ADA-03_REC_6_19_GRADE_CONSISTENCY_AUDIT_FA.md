# ADA-03 — ممیزی سازگاری GRADE نسخهٔ v0.8

## علت ممیزی

در نسخهٔ v0.7 چهار Evidence Unit دارای certainty نهایی بودند که با دامنه‌های downgrade ثبت‌شده سازگار نبودند. این موارد بدون عبور به Rule شناسایی و اصلاح شدند.

## روش

سطوح به‌صورت زیر کنترل شدند:

- High = 4
- Moderate = 3
- Low = 2
- Very Low = 1

هر `SERIOUS` یک سطح و هر `VERY SERIOUS` دو سطح downgrade محسوب شد. سطح نهایی پایین‌تر از Very Low نمی‌رود. `PENDING` محاسبه نمی‌شود.

## اصلاحات

- `EU-6.19-04`: LOW → **VERY LOW**
- `EU-6.19-06`: MODERATE → **LOW**
- `EU-6.19-08`: MODERATE → **VERY LOW**
- `EU-6.19-09`: LOW → **VERY LOW**
- `EU-6.19-10`: همچنان **PENDING / NOT FINAL**

## اثر بالینی

این اصلاح نتیجهٔ ایمنی را سخت‌گیرانه‌تر می‌کند:

- شواهد switching پس از event بسیار غیرمستقیم است؛
- patient activation برای process شواهد Low دارد، نه Moderate؛
- HOAP برای انتقال به محیط دیگر و تعریف یک Rule، certainty بسیار پایین دارد؛
- سیگنال ED/IP HOAP برای اثبات patient-outcome benefit بسیار پایین است.

## Gate

Rule Candidate = 0  
Accepted Rule = 0

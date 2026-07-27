# A14 — صفرکردن baseline شکست‌های CI

A14 شکست‌های تاریخی شناخته‌شده را می‌بندد و میان تست منقضی و نقص محصول تفکیک می‌گذارد.

## اصلاح‌های تثبیت‌شده

- هویت موتور از release constant واحد خوانده می‌شود؛ تست literal قدیمی حذف شد.
- timestamp تست care-loop از head واقعی append-only جلو می‌رود.
- تست‌های accounting bridge مسیر per-app را تغییر می‌دهند و دیگر Config سراسری را دور نمی‌زنند.
- doctor queue در تست route ابتدا cutover رسمی، روز فعال و Encounter فعال می‌سازد و سپس سند/شاخص ثبت می‌کند.
- busy timeout فعلی specialist برابر ۱۰ ثانیه است.
- Mediana پاسخ‌های PascalCase/camelCase، `SmsItems`، `StatusInt`، خطاهای meta و پاسخ HTTP غیر JSON را fail-closed می‌خواند.
- batch مدیانا عمداً serial است تا idempotency و تطبیق پیام‌به‌پیام حفظ شود.
- شمارش UI بر token واقعی navigation انجام می‌شود.

## شواهد exact-head

Exact tested product head: `84f94ae4a883943fb08ea5e20fc482cea00e27d5`

- Specialist Clinic: **672 passed / 0 failed / 0 errors / 0 skipped**
- Accounting: **54 passed / 0 failed / 0 errors / 0 skipped**
- Evidence SHA-256: `64b1cde36a9eb1fbb3c3cde45ff817deaeb8fa76a4b2b3d26b97f4f107de7e75`
- workflow، finalizer، repair script، JUnit و bytecodeهای موقت از tree محصول حذف شدند.

## نتیجه

baseline عمومی ۲۶ failure به صفر رسید؛ هیچ failure با `skip`، `xfail` یا کاهش دامنهٔ suite پنهان نشده است.

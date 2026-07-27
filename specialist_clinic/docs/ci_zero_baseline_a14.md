# A14 — صفرکردن baseline شکست‌های CI

A14 فقط شکست‌های تاریخی شناخته‌شده را می‌بندد و میان تست منقضی و نقص محصول تفکیک می‌گذارد.

- هویت موتور از release constant واحد خوانده می‌شود؛ تست literal قدیمی حذف شد.
- timestamp تست care-loop از head واقعی append-only جلو می‌رود.
- تست‌های accounting bridge مسیر per-app را تغییر می‌دهند و دیگر Config سراسری را دور نمی‌زنند.
- doctor queue در تست route ابتدا Encounter فعال می‌سازد و سپس سند/شاخص ثبت می‌کند.
- busy timeout فعلی specialist برابر ۱۰ ثانیه است.
- Mediana پاسخ‌های PascalCase/camelCase، SmsItems، StatusInt، خطاهای meta و پاسخ HTTP غیر JSON را fail-closed می‌خواند.
- batch مدیانا عمداً serial است تا idempotency و تطبیق پیام به پیام حفظ شود.
- شمارش UI بر دکمه‌های واقعی class-bound انجام می‌شود.

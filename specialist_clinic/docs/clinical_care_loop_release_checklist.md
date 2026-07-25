# چک‌لیست انتشار Closed Clinical Care Loop

این موارد فقط با عبور gate اجرایی مربوط به repository، SQLite guards، UI و
recurrence تکمیل‌شده محسوب می‌شوند؛ بررسی دستی جایگزین تست نیست.

- [ ] هر task بالینی در زمان ساخت، یک `CREATED/OPEN` root event دارد.
- [ ] هیچ مسیر عمومی یا اداری `followup_tasks.status` را برای task بالینی تغییر نمی‌دهد.
- [ ] ثبت `COMPLETED` بدون outcome متعلق به همان task در SQLite شکست می‌خورد.
- [ ] outcome مربوط به task دیگر برای completion قابل استفاده نیست.
- [ ] `NOT_DONE` بدون disposition صریح شکست می‌خورد.
- [ ] appointment بیمار دیگر برای `SCHEDULED` رد می‌شود.
- [ ] `expected_current_event_id` قدیمی هیچ transitionی ثبت نمی‌کند.
- [ ] UPDATE و DELETE روی task event و outcome event شکست می‌خورند.
- [ ] task زمان‌بندی‌شده پس از ساخت appointment همچنان باز باقی می‌ماند.
- [ ] terminal task فقط با due period جدید می‌تواند task تازه تولید کند.
- [ ] task بالینی legacy بسته‌شده بدون outcome، fail-loud است و evidence جعلی نمی‌سازد.
- [ ] worklist برای task بالینی دکمهٔ legacy «انجام شد» نمایش نمی‌دهد.
- [ ] کاربر بدون مجوز manager فقط projection lifecycle را می‌بیند.
- [ ] CI canonical پیش از commit نهایی به نسخهٔ پایه بازگردانده می‌شود.

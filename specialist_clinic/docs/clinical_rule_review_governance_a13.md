# A13 — حاکمیت بازبینی دوگانهٔ قواعد بالینی

## مشکل بسته‌شده

مسیر قبلی اجازه می‌داد یک فرم بالینی همهٔ Ruleها را تیک بزند و همان لحظه ruleset را به `SILENT` ببرد. A13 این مسیر تک‌نفره را حذف می‌کند.

## قرارداد جدید

```text
immutable package + case bundle
→ technical decisions for every rule
→ clinical decisions for every rule
→ distinct authenticated usernames
→ exact latest APPROVE for both roles
→ separate RULE_ACTIVATE freeze
→ SILENT only
```

هر تصمیم در `clinical_rule_review_events` ثبت می‌شود و به این شناسه‌ها متصل است:

- ruleset و `ruleset_content_hash`
- rule version و `rule_content_hash`
- `package_hash`
- `case_bundle_hash`
- نقش بازبین، تصمیم، username احرازشده، نام نمایشی، یادداشت و زمان
- رویداد قبلی همان Rule/Role در صورت اصلاح تصمیم

## گاردها

- UPDATE و DELETE رویدادهای بازبینی در SQLite ممنوع است.
- review فقط روی ruleset با وضعیت `DRAFT` ثبت می‌شود.
- Rule باید عضو همان ruleset باشد و hashها باید دقیقاً منطبق باشند.
- یک username نمی‌تواند در یک ruleset هر دو نقش بالینی و فنی را ثبت کند.
- هر Rule باید در هر نقش تصمیم صریح `APPROVE` یا `REQUEST_CHANGES` داشته باشد.
- `REQUEST_CHANGES` فریز را مسدود می‌کند؛ رفع آن یک رویداد جدید append-only می‌سازد.
- فریز به مجوز مستقل `RULE_ACTIVATE` نیاز دارد و موتور همچنان خاموش می‌ماند.
- approval تک‌نفرهٔ قدیمی عمداً fail-closed شده است.

## مرز انتشار

A13 هیچ Rule را از `NOT_REVIEWED` به تأیید بالینی واقعی تبدیل نمی‌کند. این مرحله فقط زیرساخت قابل‌ممیزی برای ثبت آن تصمیم‌ها را می‌سازد.

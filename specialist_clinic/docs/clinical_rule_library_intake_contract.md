# A11 — قرارداد ورود کتابخانهٔ قواعد بالینی

## هدف

A11 هیچ threshold یا توصیهٔ بالینی تازه‌ای اضافه نمی‌کند. هدف آن است که پیش از توسعهٔ Rule Library، یک بستهٔ ناقص یا مبهم نتواند وارد مسیر import، shadow validation یا activation شود.

## منبع حقیقت واحد

```text
manifest.json
+ immutable rule JSON files
+ validation-cases.json
→ package contract
→ compiler/import
→ deterministic validation
→ append-only clinical + technical attestation
→ shadow/pilot/activation
```

import و validation هر دو از `package_contract.py` استفاده می‌کنند و hash بسته و case bundle را از همان محتوای canonical می‌سازند.

## Gateهای بسته

- version و `ruleset_code` باید دقیقاً با runtime جاری برابر باشند.
- artifact bundled همیشه `DRAFT / NOT_APPROVED` می‌ماند؛ approval واقعی داخل فایل JSON جاسازی نمی‌شود.
- filename امن و داخل همان package، sort order یکتا و phase منطبق الزامی است.
- `rule_code` و `semantic_key` در یک بسته یکتا هستند.
- evidence دارای منبع، سازمان، نسخه، locator، URL امن و وضعیت validation صریح است.
- هر golden case نتیجهٔ تمام Ruleهای manifest را مشخص می‌کند.
- `ERROR` نتیجهٔ مورد انتظار قابل قبول نیست.
- categoryهای positive، negative، borderline، missing-data، conflict، historical، contraindication و suppression پوشش داده می‌شوند.
- هر Rule حداقل یک positive و یک non-positive case دارد.
- import بستهٔ ذخیره‌شده را با package immutable برنامه دوباره تطبیق می‌دهد.

## مرز ایمنی

عبور A11 به معنی تأیید بالینی دو Rule فعلی نیست. بستهٔ `2026.1-draft.2` همچنان `NOT_REVIEWED` است و فقط پس از validation، تأیید مستقل بالینی/فنی، pilot و seal دقیق می‌تواند وارد rollout قابل مشاهده شود.

## مرحلهٔ بعد

Ruleهای جدید باید در trancheهای کوچک و بیماری‌محور اضافه شوند. برای هر Rule، evidence review، تصمیم مالک بالینی، Fact/Unit canonical، eligibility و exclusion اجرایی، golden matrix، dependency analysis، بازبینی پزشک، shadow و pilot مستقل لازم است.

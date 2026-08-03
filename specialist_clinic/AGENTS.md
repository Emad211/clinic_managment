# Specialist Clinic — Agent Instructions

این فایل نزدیک‌ترین منبع دستور برای همهٔ تغییرات زیر `specialist_clinic/` است.

## ترتیب مطالعهٔ اجباری

پیش از هر تغییر:

1. `PROJECT_STATE.md` و `PROJECT_STATE.json`؛
2. `AGENTS.md` ریشه؛
3. همین فایل؛
4. `graphify-out/GRAPH_REPORT.md` در صورت وجود؛
5. قرارداد نزدیک به کد و سند canonical جریان.

برای Follow-up، Task، Worklist، SMS، Contact، Appointment یا automation:

```text
docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md
docs/FOLLOWUP_ORCHESTRATION_UX_V1_BASELINE.md
```

حافظهٔ گفتگو، branch قدیمی و PR تاریخی بر `main` و منابع بالا مقدم نیستند.

## طبقه‌بندی محیط فعلی

```text
specialist.db = TEST_ONLY / SYNTHETIC_OR_RESETTABLE
source        = owner attestation, 2026-08-03
```

Reset/reseed و migration rehearsal روی دادهٔ فعلی مجاز است، اما guardrailهای امنیتی و بالینی حذف نمی‌شوند. پیش از دادهٔ واقعی، production-readiness و privacy review الزامی است. هیچ shortcut مبتنی بر `TEST_ONLY` وارد runtime نشود.

## وضعیت FOUX-V1

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = AUTHORIZED
FO-4 and later = BLOCKED pending FO-3 exit gate
```

### زیرساخت موجود روی main

```text
followup_episodes
followup_episode_links
followup_episode_events
followup_work_item_projection
```

Episode/Link immutable، Episode Event append-only و Projection rebuildable cache است. Backfill و projection rebuild خودکار startup ندارند.

## دامنهٔ مجاز فعلی: FO-3

```text
FO-3 — Read-only Unified Worklist & Timeline
```

FO-3 می‌تواند فقط:

- route GET feature-flagged برای list/detail؛
- read-model service بدون N+1؛
- pagination، search و filterهای whitelist؛
- کارت Work Item با copy عملیاتی؛
- action/wait/block explanation؛
- role proposal، action due، target و projection age؛
- Timeline read-only از Sourceهای حاکم؛
- permission-safe deep-link به مسیرهای فعلی؛
- empty/loading/stale/conflict states؛
- RTL/Jalali/fa number/accessibility؛
- تست‌های authorization، query count، no mutation و legacy parity.

FO-3 نباید:

- POST یا mutation endpoint جدید بسازد؛
- claim/assignment انجام دهد؛
- role proposal را assignment واقعی معرفی کند؛
- routing، SLA یا escalation mutation اجرا کند؛
- SMS ارسال یا approval را تغییر دهد؛
- appointment reaction یا outbox بسازد؛
- callback/retry/auto-close اجرا کند؛
- Evidence Assist یا clinical decision بسازد؛
- Worklist قدیمی را حذف یا رفتار آن را تغییر دهد؛
- Rule یا Hypoglycemia Shadow را تغییر دهد؛
- `clinic_new.db` را بنویسد.

## Feature Flagها

```text
FOLLOWUP_EPISODES_ENABLED
FOLLOWUP_PROJECTION_SHADOW
FOLLOWUP_UNIFIED_WORKLIST_READONLY
FOLLOWUP_UNIFIED_WORKLIST_ACTIONS
FOLLOWUP_AUTO_ROUTING
FOLLOWUP_STRUCTURED_CONTACT
FOLLOWUP_SMS_AUTO_GUARDED
FOLLOWUP_APPOINTMENT_SYNC
FOLLOWUP_EVIDENCE_ASSIST
FOLLOWUP_AUTOMATION_HEALTH
```

همه default OFF. در FO-3 فقط `FOLLOWUP_UNIFIED_WORKLIST_READONLY` مصرف می‌شود. وقتی OFF است:

- route جدید باید 404 یا unavailable کنترل‌شده بدهد؛
- navigation جدید پنهان است؛
- Worklist قدیمی هیچ query یا رفتار جدیدی اجرا نمی‌کند.

وقتی ON است، UI فقط خواندنی است.

## قرارداد Read-only UI

- Projection source truth نیست.
- request نباید projection rebuild کند.
- projection missing/stale باید واضح نمایش داده شود.
- list query صفحه‌بندی‌شده و بدون N+1 است.
- patient identity فقط به حداقل لازم محدود می‌شود.
- raw note، message body و clinical payload در list نمایش داده نمی‌شوند.
- state فنی و hash در copy اصلی نمایش داده نمی‌شوند.
- Timeline chronological و provenance-aware است.
- deep-linkها permission را دور نمی‌زنند.
- CTA در FO-3 فقط label/deep-link به مسیر حاکم است؛ action داخل UI جدید انجام نمی‌شود.

## مرزهای دائمی ایمنی

- `clinic_new.db` برای Specialist Clinic read-only است.
- Source Truthهای فعلی authoritative باقی می‌مانند.
- Episode/Projection حقیقت بالینی نیستند.
- Clinical Task completion نیازمند Evidence است.
- Appointment، Clinical Task را complete نمی‌کند.
- هیچ تصمیم دارویی، تشخیصی یا ارجاعی خودکار نیست.
- SMS guardrailها حفظ می‌شوند.
- Rule و Hypoglycemia Shadow خارج از FOUX هستند.
- eventهای append-only UPDATE/DELETE نمی‌شوند.

## تست‌های اجباری FO-3

- flag OFF route/navigation hidden؛
- flag ON authorized GET works؛
- unauthorized access denied؛
- no POST/mutation route؛
- list pagination/search/filter؛
- no N+1 / bounded query count؛
- state/role/due filters؛
- projection empty/stale/conflict states؛
- Timeline deterministic order/source labels؛
- permission-safe deep-links؛
- RTL/Jalali/fa number/accessibility؛
- no source/projection mutation from GET؛
- legacy Worklist unchanged؛
- full Specialist and Accounting CI.

## PR Contract

هر PR باید tranche، Requirement ID، scope، schema/data impact، feature flag، focused/full tests، rollback، UX effect و proof مرزهای بالینی/حسابداری را ثبت کند.

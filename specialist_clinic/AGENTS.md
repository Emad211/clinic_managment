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

Reset/reseed و migration rehearsal روی دادهٔ فعلی مجاز است، ولی guardrailهای امنیتی و بالینی حذف نمی‌شوند. پیش از ورود دادهٔ واقعی بیمار، production-readiness و privacy review الزامی است. هیچ shortcut مبتنی بر `TEST_ONLY` وارد runtime نشود.

## وضعیت FOUX-V1

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = AUTHORIZED
FO-3 and later = BLOCKED pending FO-2 exit gate
```

### FO-1 موجود روی main

```text
followup_episodes
followup_episode_links
followup_episode_events
```

Episode و Link immutable هستند؛ Event append-only و linear است. CLI backfill explicit است و startup backfill خودکار ندارد. Relation مبهم باید orphan reason بگیرد، نه relation حدسی.

## دامنهٔ مجاز فعلی: FO-2

```text
FO-2 — Projection, Next Action & Shadow Parity
```

FO-2 می‌تواند فقط این موارد را اضافه کند:

- schema additive/idempotent برای `followup_work_item_projection`؛
- repository projection؛
- source-state adapterهای read-only؛
- policy مرکزی و versioned برای state/next action؛
- `ACTION_REQUIRED / WAITING / BLOCKED / TERMINAL`؛
- waiting/block reason؛
- جداسازی `action_due_at` و `target_at`؛
- owner role proposal بدون assignment؛
- deterministic projection hash/rebuild؛
- parity report با Worklist فعلی؛
- projection lag/performance metrics؛
- explicit CLI و focused tests.

FO-2 نباید:

- Worklist یا template فعلی را تغییر دهد؛
- route یا CTA جدید عملیاتی بسازد؛
- claim/assignment انجام دهد؛
- SMS ارسال یا approval را تغییر دهد؛
- appointment reaction اجرا کند؛
- outbox، retry، escalation یا auto-close بسازد؛
- Evidence Assist بسازد؛
- Clinical Task را transition/complete کند؛
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

همه default OFF. در FO-2 فقط `FOLLOWUP_PROJECTION_SHADOW` ممکن است توسط اجرای explicit shadow/CLI مصرف شود. request، Scheduler و UI با default OFF باید دقیقاً رفتار قبلی را حفظ کنند.

## قرارداد Projection در FO-2

هر Work Item nonterminal دقیقاً یکی از این حالت‌هاست:

```text
ACTION_REQUIRED
WAITING
BLOCKED
```

و باید دقیقاً یک توضیح عملیاتی داشته باشد:

```text
next_action
waiting_reason
blocked_reason
```

Projection:

- source truth نیست؛
- از Episode/Links و Sourceهای حاکم rebuild می‌شود؛
- same source snapshot → same projection hash؛
- patient scope را دوباره کنترل می‌کند؛
- raw PHI یا payload بالینی عمومی ذخیره نمی‌کند؛
- owner فقط role proposal است؛
- تاریخ یا relation ساختگی تولید نمی‌کند؛
- conflict/missing/stale را با reason code نشان می‌دهد.

## مرزهای دائمی ایمنی

- `clinic_new.db` برای Specialist Clinic read-only است.
- Source Truthهای فعلی authoritative باقی می‌مانند.
- Episode/Projection حقیقت بالینی نیستند.
- Clinical Task completion نیازمند Evidence حاکم است.
- Appointment، Clinical Task را complete نمی‌کند.
- هیچ تصمیم دارویی، تشخیصی یا ارجاعی خودکار نیست.
- SMS consent/quiet/cap/cooldown/idempotency حفظ می‌شود.
- Rule و Hypoglycemia Shadow خارج از FOUX هستند.
- eventهای append-only هرگز UPDATE/DELETE نمی‌شوند.

## تست‌های اجباری FO-2

- fresh/existing/rerun migration؛
- deterministic projection hash؛
- delete/rebuild equivalence؛
- every nonterminal projection has action/wait/block؛
- source/patient mismatch becomes blocked/conflict؛
- stale/missing source reason؛
- role proposal deterministic؛
- action_due/target separation؛
- parity report classifies every mismatch؛
- source truth unchanged؛
- feature default OFF causes no existing behavior change؛
- no UI/Scheduler/SMS mutation؛
- full Specialist suite؛
- Accounting suite when governance/shared files change.

## PR Contract

هر PR باید tranche، Requirement ID، scope، schema/data impact، feature flag، focused/full tests، rollback، UX effect و proof مرزهای بالینی/حسابداری را ثبت کند.

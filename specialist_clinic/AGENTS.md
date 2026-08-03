# Specialist Clinic — Agent Instructions

این فایل نزدیک‌ترین منبع دستور برای همهٔ تغییرات زیر `specialist_clinic/` است.

## ترتیب مطالعهٔ اجباری

1. وضعیت واقعی `main`، PRها و Issueها؛
2. `PROJECT_STATE.md` و `PROJECT_STATE.json`؛
3. `AGENTS.md` ریشه؛
4. همین فایل؛
5. سند canonical نزدیک به جریان.

برای Follow-up، Task، Worklist، SMS، Contact، Appointment یا automation:

```text
docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md
docs/FOLLOWUP_ORCHESTRATION_UX_V1_BASELINE.md
```

## طبقه‌بندی محیط

```text
specialist.db = TEST_ONLY / SYNTHETIC_OR_RESETTABLE
```

این طبقه‌بندی هیچ guardrail امنیتی یا بالینی را حذف نمی‌کند.

## وضعیت FOUX-V1

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = TECHNICALLY_VALIDATED
FO-3 LOCAL UX ACCEPTANCE = BLOCKED BY CONFIRMED JINJA RUNTIME DEFECT
FOCUSED FIX ISSUE = #84
FOCUSED FIX PR = #85
FO-4 and later = BLOCKED
```

سند canonical: نسخهٔ `1.4.2`.

### Evidence پایهٔ FO-3

```text
Issue #80 / PR #81
merge afed3545c0a90a1ed7ff7e0a892df89fffac00c2
CI 30775348057
754 Specialist + 54 Accounting
```

### علت قطعی Incident

CI run `30808217800` با Flask/Jinja واقعی ثبت کرد:

```text
TypeError: 'builtin_function_or_method' object is not iterable
{% for item in model.items %}
```

علت قطعی:

```text
JINJA_DICT_METHOD_COLLISION_ON_ITEMS_KEY
```

در Jinja، `model.items` به متد `dict.items` اشاره کرد، نه key دیکشنری. دسترسی صحیح:

```jinja2
model['items']
timeline['items']
```

Schema/cache hardening بخشی از repair است، اما علت قطعی screenshot نیست.

## دامنهٔ مجاز فعلی

- اصلاح Jinja collision در list و Timeline؛
- real Flask/Jinja integration tests؛
- static guard علیه `model.items` و `timeline.items`؛
- repair فقط برای cache disposable `followup_work_item_projection`؛
- required-column preflight؛
- controlled Persian state برای خطاهای SQLite/schema شناخته‌شده؛
- اثبات ثابت‌ماندن Source Truth و Episode digest؛
- focused/full CI؛
- تکرار مرور UX پس از merge.

## دامنهٔ ممنوع

- POST یا mutation endpoint جدید؛
- claim/assignment؛
- routing، SLA یا escalation mutation؛
- SMS send/approval automation؛
- appointment reaction یا outbox؛
- callback/retry/auto-close؛
- Evidence Assist یا clinical decision؛
- تغییر Rule یا Hypoglycemia Shadow؛
- write به `clinic_new.db`؛
- شروع FO-4.

## قرارداد Repair

1. mapping key متعارض با متدهای dict در template با bracket notation خوانده شود.
2. real render test الزامی است؛ mock کردن `render_template` کافی نیست.
3. فقط Projection cache disposable می‌تواند در schema drift recreate شود.
4. Episode/Link/Event، Task، SMS، Appointment، Contact و Clinical tables هرگز drop/rewrite نمی‌شوند.
5. cache ناسازگار canonical و خالی می‌شود؛ rebuild فقط صریح است.
6. known SQLite/schema error باید controlled UI state بدهد، نه generic 500.
7. unknown programming exception با `except Exception` پنهان نمی‌شود.
8. Worklist قدیمی authority اقدام باقی می‌ماند.
9. flag OFF همچنان route=404 و navigation hidden است.

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

همه default OFF. در repair فقط Read-only flag مصرف می‌شود و rebuild تستی با Shadow flag صریح است. Action flags ممنوع‌اند.

## تست‌های اجباری PR #85

- real Flask/Jinja list render؛
- real Flask/Jinja Timeline render؛
- no `model.items` / no `timeline.items`؛
- incompatible cache recreated empty؛
- migration rerun idempotent؛
- Source Truth و Episode digest ثابت؛
- incompatible schema → controlled page، نه 500؛
- canonical list/detail render؛
- flag OFF 404/hidden؛
- POST 405؛
- GET بدون mutation؛
- full Specialist and Accounting CI.

## مرزهای دائمی

- `clinic_new.db` read-only است.
- Source Truthها authoritative هستند.
- Episode/Projection حقیقت بالینی نیستند.
- Clinical Task completion نیازمند Evidence است.
- Appointment، Clinical Task را complete نمی‌کند.
- تصمیم دارویی، تشخیصی یا ارجاعی خودکار نیست.
- eventهای append-only UPDATE/DELETE نمی‌شوند.

## PR Contract

هر PR باید Issue، scope، schema/cache impact، feature flag، focused/full tests، rollback و proof عدم تغییر Clinical/Accounting/Source Truth را ثبت کند. پس از merge PR #85 نیز FO-4 تا پذیرش UX جدید مالک مسدود است.

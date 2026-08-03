# Follow-up Orchestration & UX v1 — Canonical Implementation Plan

> **نام فایل مرجع:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **کد برنامه:** `FOUX-V1`
>
> **نسخه:** `1.5.0`
>
> **آخرین بازبینی:** `2026-08-03`
>
> **وضعیت:** `FO_0_VALIDATED / FO_1_VALIDATED / FO_2_VALIDATED / FO_3_VALIDATED_WITH_OWNER_ACCEPTANCE / FO_4_AUTHORIZED / FO_5_AND_LATER_BLOCKED`
>
> **مالک:** `Emad211`
>
> **دامنه:** فقط `specialist_clinic/`
>
> **طبقه‌بندی محیط فعلی:** `TEST_ONLY / SYNTHETIC_OR_RESETTABLE_DATA`
>
> **خارج از دامنه:** تغییر Rule بالینی، گسترش Hypoglycemia Shadow، تصمیم درمانی خودکار، Write به `clinic_new.db` و تغییر رفتار `webapp/`.

---

## 1. ترتیب اعتماد

1. وضعیت واقعی `main`، PRها، Issueها و CI؛
2. `PROJECT_STATE.json` و `PROJECT_STATE.md`؛
3. این سند و `specialist_clinic/AGENTS.md`؛
4. قراردادهای نزدیک به کد؛
5. متن PRهای تاریخی؛
6. حافظهٔ گفتگو یا ایجنت.

هر ادعای تکمیل، تست، push یا merge باید SHA و CI evidence داشته باشد.

---

## 2. هدف محصول

Task، SMS، Contact، Appointment، Clinical Outcome و Encounter Commitment بدون بازنویسی Source of Truthهای فعلی در یک Episode و Projection بازسازی‌پذیر دیده شوند تا کاربر فوراً بداند:

- چرا مورد ساخته شده؛
- وضعیت و موعد چیست؛
- صف و مسئول واقعی کدام است؛
- منتظر چه چیزی است؛
- آخرین رویداد و اقدام بعدی چیست.

---

## 3. وضعیت trancheها

| Tranche | وضعیت | Evidence |
|---|---|---|
| FO-0 | `VALIDATED` | Issue #71، PR #72/#73 |
| FO-1 | `VALIDATED` | Issue #74، PR #75 |
| FO-2 | `VALIDATED` | Issue #77، PR #78 |
| FO-3 | `VALIDATED_WITH_OWNER_ACCEPTANCE` | PR #81/#85/#88، Issue #83 |
| FO-4 | `AUTHORIZED` | Issue #90 و governance PR مستقل |
| FO-5 و بعد | `BLOCKED` | نیازمند validation و authorization مستقل |

---

## 4. معماری حاکم

```text
Authoritative Source Truths
        ↓
Episode / Link / append-only Event       [FO-1]
        ↓
Deterministic Projection Cache           [FO-2]
        ↓
Unified Worklist / Timeline              [FO-3]
        ↓
Ownership / Routing / SLA events         [FO-4]
```

Source Truthهای قبلی authoritative می‌مانند. Episode حقیقت بالینی نیست و Projection فقط cache است.

### Storageهای معتبر فعلی

```text
followup_episodes
followup_episode_links
followup_episode_events
followup_work_item_projection
```

### Routeهای FO-3

```text
GET /followups/unified/
GET /followups/unified/<episode_id>
```

---

## 5. Evidence معتبر

### FO-0

```text
Merge 901dbfdf9c358ecc09d2a60a0680f6a4a8370d17
731 Specialist + 54 Accounting
```

### FO-1

```text
Merge 15ef1585c069a74c26fbc0ce859e03906e5f475a
736 Specialist + 54 Accounting
4 Episodes / 12 Links / idempotent replay
```

### FO-2

```text
Merge 6c6e33203376a32165418e0d3c6f2a4a48253e7b
CI 30773195914
747 Specialist + 54 Accounting
100% legacy coverage / deterministic rebuild
```

### FO-3 initial implementation

```text
Merge afed3545c0a90a1ed7ff7e0a892df89fffac00c2
CI 30775348057
754 Specialist + 54 Accounting
```

### FO-3 runtime repair

```text
Issue #84 / PR #85
Merge 8f851c90da5a81f4b7ffce43eaa5bf6010d58fa2
Root-cause CI 30808217800
Final CI 30809363219
761 Specialist + 54 Accounting
Root cause = JINJA_DICT_METHOD_COLLISION_ON_ITEMS_KEY
```

### FO-3 operator-copy repair

```text
Issue #87 / PR #88
Merge 020803868e1c2755f7669d52da92cb8050a46018
CI 30827033618
762 Specialist + 54 Accounting
```

### FO-3 owner acceptance

Issue #83 ثبت کرده است:

```text
FO3_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = 020803868e1c2755f7669d52da92cb8050a46018
reviewed_on_test_data = true
critical_ux_defects = 0
```

Issue #83 با وضعیت `completed` بسته شد. درخواست مستقل شفاف‌سازی «رضایت پیامکی» نقص FO-3 محسوب نمی‌شود و باید در PR مستقل انجام شود.

---

## 6. Invariantهای غیرقابل‌مذاکره

1. Source Truthهای قبلی authoritative می‌مانند.
2. Episode و Projection حقیقت بالینی نیستند.
3. relation، event، due date، target، outcome یا assignment جعل نمی‌شود.
4. هر Projection غیرنهایی دقیقاً action، wait یا block دارد.
5. Clinical completion فقط با Evidence و transition معتبر انجام می‌شود.
6. Appointment به‌تنهایی Clinical Task را complete نمی‌کند.
7. Worklist قدیمی تا cutover مستقل authority عملیاتی باقی می‌ماند.
8. Rule و Hypoglycemia Shadow خارج از scope هستند.
9. `clinic_new.db` فقط read-only است.
10. feature flag خاموش رفتار قبلی را بازمی‌گرداند.
11. همهٔ ownership mutationها append-only، idempotent و audit‌شده‌اند.
12. claim هم‌زمان دقیقاً یک winner دارد.
13. هیچ silent reassignment مجاز نیست.
14. stale form/current-head mismatch باید fail closed شود.
15. owner role و owner user دو مفهوم جدا هستند.
16. نقش پیشنهادی FO-2 به‌تنهایی assignment واقعی نیست.
17. FO-5 و بعد بدون validation و governance جدید ممنوع است.

---

## 7. Feature Flags

همه default OFF:

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

FO-4 فقط با این دو flag قابل نمایش/استفاده است:

```text
FOLLOWUP_UNIFIED_WORKLIST_ACTIONS
FOLLOWUP_AUTO_ROUTING
```

خاموش‌بودن هرکدام باید mutation متناظر را غیرقابل‌دسترسی کند.

---

## 8. قدم مجاز فعلی — FO-4

Issue حاکم: `#90`

### هدف

مالکیت روشن، صف نقش واقعی، SLA قابل‌فهم و کاهش موارد بدون مسئول، بدون تغییر حقیقت بالینی یا تکمیل خودکار کار.

### دامنهٔ مجاز

- append-only ownership/routing events در Episode stream؛
- atomic claim؛
- release توسط مالک یا مدیر؛
- assign/reassign توسط مجوز مدیریتی؛
- role queue و role compatibility؛
- SLA display و filter؛
- stale form protection با expected current event؛
- actor، reason، idempotency و audit؛
- نمایش مسئول واقعی در list/detail؛
- بازسازی Projection از event stream؛
- rollback با خاموش‌کردن flagها.

### دامنهٔ ممنوع

- تغییر status یا completion Source Truth؛
- clinical decision یا clinical completion؛
- bulk mutation روی Clinical Task؛
- structured contact؛
- retry/escalation؛
- SMS automation؛
- Appointment reaction؛
- outbox/dead-letter؛
- Evidence Assist؛
- FO-5 و بعد.

### Permission contract

- مشاهده: `clinical.task.view`؛
- claim/release: permission سازگار با owner role؛
- assign/reassign: `followup.admin.manage`؛
- PHYSICIAN queue: نیازمند `clinical.task.transition`؛
- MANAGER queue: فقط manager/equivalent effective permission؛
- permission failure باید fail closed شود.

### Mutation contract

هر mutation باید این داده‌ها را ثبت کند:

```text
episode_id
action
owner_role
owner_user_id
actor_username
actor_user_id
reason_code
expected_current_assignment_event_id
idempotency_key
effective_at / recorded_at
```

### تست اجباری

- concurrent claim فقط یک winner؛
- exact replay idempotent؛
- stale expected event rejected؛
- unauthorized role claim rejected؛
- manager assign/reassign audited؛
- release by non-owner rejected؛
- terminal item mutation rejected؛
- projection rebuild ownership را حفظ کند؛
- GET و feature-off behavior قبلی حفظ شود؛
- Source Truth digest ثابت بماند؛
- full Specialist + Accounting CI سبز باشد.

### Exit gate

```text
all nonterminal items have owner role or blocked reason = PASS
concurrent claim one winner                           = PASS
zero silent reassignment                              = PASS
projection rebuild preserves ownership                = PASS
full CI green                                         = PASS
local owner UX acceptance                             = REQUIRED
```

تا validation و owner review، FO-4 به‌عنوان pilot feature باقی می‌ماند و FO-5 مسدود است.

---

## 9. UX قرارداد FO-4

در لیست و جزئیات باید واضح باشد:

```text
صف مسئول: نقش عملیاتی
مسئول فعلی: شخص واقعی یا «بدون مسئول»
اقدام اصلی: دریافت برای رسیدگی / آزادکردن / واگذاری
موعد اقدام: action_due_at
هدف نهایی: target_at
```

قواعد:

- فقط یک CTA اصلی برای هر وضعیت؛
- assignment با role proposal اشتباه نشود؛
- تغییر مسئول confirmation و reason دارد؛
- خطای رقابت به زبان ساده می‌گوید مورد قبلاً توسط فرد دیگری دریافت شده؛
- فرم stale هیچ mutationی انجام نمی‌دهد؛
- صفحه read-only با actions flag خاموش همان FO-3 باقی می‌ماند.

---

## 10. Rollback

```powershell
$env:FOLLOWUP_UNIFIED_WORKLIST_ACTIONS = "0"
$env:FOLLOWUP_AUTO_ROUTING = "0"
```

نتیجه:

- action controls و mutation routeها unavailable می‌شوند؛
- FO-3 read-only باقی می‌ماند؛
- eventهای audit حذف یا rewrite نمی‌شوند؛
- Source Truth rollback لازم ندارد؛
- Projection cache قابل rebuild است.

---

## 11. قواعد ایجنت

1. `main`، Issue #90 و plan v1.5.0 خوانده شوند؛
2. فقط FO-4 bounded contract اجرا شود؛
3. eventهای ownership append-only باشند؛
4. Source Truth، Rule، SMS و Appointment behavior تغییر نکند؛
5. هر mutation permission، stale guard و idempotency داشته باشد؛
6. هر PR schema/cache impact و rollback را ثبت کند؛
7. full CI و local UX review لازم است؛
8. بدون validation وارد FO-5 نشود.

---

## 12. تصمیم فعلی

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = VALIDATED WITH OWNER ACCEPTANCE
FO-4 = AUTHORIZED
FO-5 AND LATER = BLOCKED
```

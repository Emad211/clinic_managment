# Follow-up Orchestration & UX v1 — Canonical Implementation Plan

> **نام فایل مرجع:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **کد برنامه:** `FOUX-V1`
>
> **نسخه:** `1.7.0`
>
> **آخرین بازبینی:** `2026-08-04`
>
> **وضعیت:** `FO_0_VALIDATED / FO_1_VALIDATED / FO_2_VALIDATED / FO_3_VALIDATED_WITH_OWNER_ACCEPTANCE / FO_4_VALIDATED_WITH_OWNER_ACCEPTANCE / FO_5_TECHNICALLY_VALIDATED_OWNER_UX_PENDING / FO_6_AND_LATER_BLOCKED`
>
> **رودمپ کامل:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md`
>
> **مالک:** `Emad211`
>
> **محیط:** `TEST_ONLY / SYNTHETIC_OR_RESETTABLE_DATA`

---

## 1. ترتیب اعتماد

1. وضعیت واقعی `main`، PRها، Issueها و CI؛
2. `PROJECT_STATE.json` و `PROJECT_STATE.md`؛
3. این سند، رودمپ و `specialist_clinic/AGENTS.md`؛
4. قراردادهای نزدیک به کد؛
5. حافظهٔ گفتگو.

هر ادعای تکمیل، push، test یا merge باید SHA و CI evidence داشته باشد.

---

## 2. هدف و معماری

Task، SMS، Contact، Appointment، Clinical Outcome و Encounter Commitment بدون بازنویسی Source Truthهای موجود در Episode و Projection قابل‌ردیابی شوند تا اپراتور بداند چرا مورد ساخته شده، مسئول آن کیست، آخرین اتفاق چه بوده و اقدام بعدی چیست.

```text
Authoritative Source Truths
        ↓
Episode / Link / append-only Event       [FO-1]
        ↓
Deterministic Projection Cache           [FO-2]
        ↓
Unified Worklist / Timeline              [FO-3]
        ↓
Ownership / Routing / Effective SLA      [FO-4]
        ↓
Structured Contact / Retry / Escalation  [FO-5]
```

Storageهای معتبر فعلی:

```text
followup_episodes
followup_episode_links
followup_episode_events
followup_work_item_projection
followup_contact_events
```

`followup_contact_events` Source Truth append-only تماس باقی می‌ماند. FO-5 نباید یک حقیقت تماس موازی بسازد؛ فقط Contact Event معتبر را به Episode وصل و تصمیم عملیاتی PHI-minimized را در Episode event stream ثبت می‌کند.

---

## 3. Invariantهای غیرقابل‌مذاکره

1. Source Truthهای موجود authoritative می‌مانند.
2. Episode حقیقت بالینی نیست و Projection فقط cache قابل‌بازسازی است.
3. relation، event، due date، target، outcome یا assignment جعل نمی‌شود.
4. mutationهای orchestration append-only، idempotent و audit‌شده‌اند.
5. هیچ GET یا startup، backfill/rebuild پنهانی انجام نمی‌دهد.
6. Clinical completion فقط با Evidence و transition معتبر انجام می‌شود.
7. Appointment به‌تنهایی Clinical Task را complete نمی‌کند.
8. note آزاد محرک اتوماسیون مهم نیست.
9. `clinic_new.db` فقط read-only است.
10. تمام Feature Flagها به‌صورت پیش‌فرض OFF هستند.
11. هر tranche فقط پس از gate، Issue و PR مستقل مجاز است.
12. FO-6 و بعد بدون FO-5 validation، owner acceptance و governance مستقل ممنوع‌اند.

---

## 4. وضعیت و Evidence مراحل تکمیل‌شده

### FO-0 — VALIDATED

```text
Issue #71 / PR #72/#73
Merge 901dbfdf9c358ecc09d2a60a0680f6a4a8370d17
731 Specialist + 54 Accounting
```

### FO-1 — VALIDATED

```text
Issue #74 / PR #75
Merge 15ef1585c069a74c26fbc0ce859e03906e5f475a
736 Specialist + 54 Accounting
```

### FO-2 — VALIDATED

```text
Issue #77 / PR #78
Merge 6c6e33203376a32165418e0d3c6f2a4a48253e7b
CI 30773195914
747 Specialist + 54 Accounting
```

### FO-3 — VALIDATED WITH OWNER ACCEPTANCE

```text
Issue #83
Initial PR #81
Runtime repair #84/#85
Operator copy repair #87/#88
Runtime/UI commit 020803868e1c2755f7669d52da92cb8050a46018
CI 30828272752
762 Specialist + 54 Accounting
```

```text
FO3_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = 020803868e1c2755f7669d52da92cb8050a46018
reviewed_on_test_data = true
critical_ux_defects = 0
```

### FO-4 — VALIDATED WITH OWNER ACCEPTANCE

Ownership، claim، assignment و routing:

```text
Issue #94 / PR #95
Merge 27ccb992f2cb43c78bfe98549c3f0414b88fd1d8
Final CI 30844075841
773 Specialist + 54 Accounting
```

Seeded Unified Worklist repair:

```text
Issue #97 / PR #98
Merge 24119671b8b93fdb20db3064a59d416e02d81ef6
CI 30851594179
781 Specialist + 54 Accounting
```

Canonical effective SLA repair:

```text
Issue #99 / PR #100
Merge cd243424ecbae98892e0dfde1780bb846554942f
CI 30852909213
784 Specialist + 54 Accounting
```

قابلیت‌های معتبر FO-4:

- append-only `ROUTED / CLAIMED / ASSIGNED`؛
- atomic one-winner claim؛
- stale/permission/terminal fail-closed؛
- release، assign/reassign و route؛
- جداسازی صف مسئول از شخص مسئول؛
- حفظ ownership پس از Projection rebuild؛
- seed صریحاً Episode/Link و Projection را آماده می‌کند؛
- recovery دیتابیس با `scripts/prepare_seeded_followup_view.py`؛
- seed تکراری پیگیری دستی TEST را حفظ و history تکراری نمی‌سازد؛
- SLAهای canonical و effective overdue در زمان request، بدون read-time write.

Owner acceptance ثبت‌شده در Issue #94:

```text
FO4_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = cd243424ecbae98892e0dfde1780bb846554942f
reviewed_on_test_data = true
critical_ux_defects = 0
notes = بررسی شد و مشکل بحرانی مشاهده نشد
```

---

## 5. Feature Flags

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

FO-5 فقط با روشن‌بودن صریح `FOLLOWUP_EPISODES_ENABLED`، `FOLLOWUP_PROJECTION_SHADOW`، `FOLLOWUP_UNIFIED_WORKLIST_READONLY`، `FOLLOWUP_UNIFIED_WORKLIST_ACTIONS`، `FOLLOWUP_AUTO_ROUTING` و `FOLLOWUP_STRUCTURED_CONTACT` فعال می‌شود. خاموش‌بودن Routing یا Contact باید کنترل‌ها را مخفی و mutation route را 404 کند.

---

## 6. FO-5 — TECHNICALLY VALIDATED / OWNER UX PENDING

```text
Authorization Issue = #103 / PR #104
Governance merge = 9c296e70511d73dd79a447cc34ef2aeb79f4edd9
Implementation Issue = #105 / PR #106
Final head = 2ab1cb1ec956bb9534dea7dd383b76bbf5fb3f5c
Runtime merge = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
Final CI = 30865955479
801 Specialist + 54 Accounting
Owner UX Acceptance Issue = #107
```

تمام قراردادهای فنی FO-5 PASS شده‌اند. تنها gate باز، مرور UX مالک روی دادهٔ TEST_ONLY است. توسعهٔ بیشتر Runtime یا شروع FO-6 مجاز نیست؛ فقط local review یا defect متمرکز FO-5 مجاز است.

راهنمای canonical مرور:

```text
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_FO5_LOCAL_UX_ACCEPTANCE.md
```

### Outcomeهای ساختاریافته

```text
REACHED
NO_ANSWER
BUSY
CALLBACK_REQUESTED
PHONE_INVALID
APPOINTMENT_BOOKED
DECLINED
ESCALATED_TO_PHYSICIAN
OTHER
```

### قرارداد transition

```text
REACHED
→ ادامهٔ مسیر فعلی
→ callback حذف می‌شود

CALLBACK_REQUESTED
→ زمان آینده الزامی
→ CALLBACK_AT_TIME

NO_ANSWER / BUSY قبل از threshold
→ attempt_count + 1
→ callback آینده
→ CALLBACK_AT_TIME

NO_ANSWER / BUSY در threshold
→ MANAGER_REVIEW_UNREACHABLE
→ یک ESCALATED event
→ route به MANAGER
→ escalation تکراری ممنوع

PHONE_INVALID
→ callback/retry متوقف
→ FIX_CONTACT_DATA
→ route به RECEPTION

APPOINTMENT_BOOKED
→ گزارش عملیاتی WAIT_FOR_APPOINTMENT
→ هیچ Appointment ساخته یا تغییر داده نمی‌شود
→ Clinical Task کامل نمی‌شود

DECLINED
→ MANAGER_REVIEW_DECLINED
→ تصمیم بالینی تولید نمی‌شود

ESCALATED_TO_PHYSICIAN
→ PHYSICIAN_REVIEW
→ route عملیاتی به PHYSICIAN
→ هیچ clinical decision ساخته نمی‌شود

OTHER
→ note کوتاه الزامی
→ MANAGER_REVIEW_OTHER
```

### Persistence contract

1. تماس معتبر در `followup_contact_events` به‌صورت append-only ذخیره می‌شود.
2. همان Contact Event با `source_type=CONTACT_EVENT` به Episode لینک می‌شود.
3. Episode یک `CONTACT_RECORDED` PHI-minimized ثبت می‌کند.
4. callback، waiting، escalation و routing فقط با eventهای append-only ثبت می‌شوند.
5. note آزاد فقط در Source Truth تماس می‌ماند و در Timeline اصلی کپی نمی‌شود.
6. exact replay event یا Contact Event تکراری نمی‌سازد.
7. full Episode head برای stale-form guard استفاده می‌شود.

### Permission و ownership

- ثبت تماس نیازمند `followup.contact.record` است؛
- کاربر عادی ابتدا باید owner واقعی مورد باشد؛
- مدیر مجاز می‌تواند برای مورد بدون owner یا واگذارشده ثبت کند؛
- terminal item همیشه قبل از permission/owner checks رد می‌شود.

### UI

در Unified detail:

- آخرین نتیجهٔ تماس؛
- اقدام بعدی؛
- زمان callback؛
- attempt count؛
- فرم نتیجهٔ ساختاریافته؛
- تاریخ و ساعت callback؛
- note اختیاری و فقط برای `OTHER` الزامی؛
- توضیح صریح اینکه ثبت تماس SMS، Appointment یا تصمیم بالینی اجرا نمی‌کند.

در Unified list:

- آخرین outcome؛
- اقدام پس از تماس؛
- callback آینده، بدون N+1.

Timeline باید outcome و operational next action را نشان دهد، ولی note آزاد، متن پیام یا دادهٔ بالینی را افشا نکند.

### Tests اجباری

- callback past/missing rejected؛
- exact replay idempotent؛
- attempt threshold؛
- escalation دقیقاً یک‌بار؛
- phone-invalid route؛
- unclaimed/non-owner denied؛
- stale form denied؛
- terminal denied؛
- Flag OFF → controls hidden و POST=404؛
- note در Source Truth ذخیره ولی در Timeline/UI اصلی پنهان؛
- batch list summary؛
- Source Truthهای دیگر، SMS، Appointment، Clinical Rule و Accounting unchanged؛
- full Specialist و Accounting CI.

### Rollback

```powershell
$env:FOLLOWUP_STRUCTURED_CONTACT = "0"
```

نتیجه:

- فرم و summary تماس FO-5 مخفی می‌شوند؛
- mutation route FO-5، 404 می‌شود؛
- FO-4 و FO-3 باقی می‌مانند؛
- Contact و Episode eventهای ثبت‌شده حذف یا rewrite نمی‌شوند؛
- data rollback لازم نیست.

---

## 7. خط قرمزهای FO-5

FO-5 مجاز نیست:

- SMS automation: پیامک خودکار ارسال کند یا approval policy را تغییر دهد؛
- Appointment بسازد، لغو یا تغییر دهد؛
- Clinical Task یا Commitment را complete کند؛
- clinical outcome، diagnosis یا treatment decision استنباط کند؛
- Operational Outbox یا Dead-letter بسازد؛
- Evidence Assist را شروع کند؛
- Rule یا Hypoglycemia Shadow را تغییر دهد؛
- به `clinic_new.db` بنویسد؛
- FO-6 تا FO-10 را شروع کند.

---

## 8. Exit Gate FO-5

```text
FO-4 owner acceptance                         = PASS
FO-5 governance authorization PR #104         = PASS
FO-5 implementation PR #106                   = PASS
Structured outcome persistence                = PASS
Deterministic transition policy               = PASS
Callback future validation                    = PASS
Threshold callback cleared in Source Truth    = PASS
One-time escalation                           = PASS
Routing kill-switch prerequisite              = PASS
Jalali callback date + time                    = PASS
Stale/permission/terminal/idempotency guards  = PASS
Flag-off 404/hidden controls                  = PASS
Source Truth/SMS/Appointment/Rule unchanged   = PASS
Full CI 30865955479                            = PASS (801 + 54)
Local Owner UX Acceptance Issue #107           = PENDING
FO-6 governance authorization                 = BLOCKED
```

FO-5 اکنون `TECHNICALLY_VALIDATED / OWNER_UX_PENDING` است. پذیرش مالک باید روی merge دقیق `94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852` و فقط با دادهٔ TEST_ONLY ثبت شود.

---

## 9. Roadmap و درصد پیشرفت

رودمپ کامل FO-0 تا FO-10:

```text
specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md
```

```text
FO-0..FO-4 validated with required acceptance = 5.0
FO-5 technically validated / owner UX pending = 0.8
FO-6..FO-10 blocked = 0.0
Progress = 5.8 / 11 = 52.7%
Technical implementation = 6 / 11 = 54.5%
Remaining = 47.3%
```

این درصد فقط برنامهٔ FOUX-V1 است، نه production-readiness کل Specialist Clinic.

---

## 10. تصمیم فعلی

```text
FO-0 = VALIDATED
FO-1 = VALIDATED
FO-2 = VALIDATED
FO-3 = VALIDATED WITH OWNER ACCEPTANCE
FO-4 = VALIDATED WITH OWNER ACCEPTANCE
FO-5 = TECHNICALLY VALIDATED / OWNER UX PENDING
CURRENT ISSUE = #107
REVIEWED MERGE = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
FO-6 AND LATER = BLOCKED
```

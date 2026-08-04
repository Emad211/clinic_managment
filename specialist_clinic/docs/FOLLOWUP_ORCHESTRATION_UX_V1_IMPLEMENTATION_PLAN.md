# Follow-up Orchestration & UX v1 — Canonical Implementation Plan

> **نام فایل مرجع:** `specialist_clinic/docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md`
>
> **کد برنامه:** `FOUX-V1`
>
> **نسخه:** `1.8.0`
>
> **آخرین بازبینی:** `2026-08-04`
>
> **وضعیت:** `FO_0_VALIDATED / FO_1_VALIDATED / FO_2_VALIDATED / FO_3_VALIDATED_WITH_OWNER_ACCEPTANCE / FO_4_VALIDATED_WITH_OWNER_ACCEPTANCE / FO_5_VALIDATED_WITH_OWNER_ACCEPTANCE / FO_6_AUTHORIZED_IMPLEMENTATION_PENDING / FO_7_AND_LATER_BLOCKED`
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

## 6. FO-5 — VALIDATED WITH OWNER ACCEPTANCE

```text
Implementation Issue = #105 / PR #106
Runtime merge = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
CI 30865955479 — 801 Specialist + 54 Accounting
Owner UX Issue = #107 — completed
```

```text
FO5_UX_ACCEPTED = true
reviewer = Emad211
reviewed_commit = 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852
reviewed_on_test_data = true
critical_ux_defects = 0
notes = بررسی شد و مشکل بحرانی مشاهده نشد
```

---

## 7. قدم مجاز فعلی — FO-6 Governed SMS Automation & Freshness

Authorization Issue: `#109`

Governance authorization PR: `#110`

### هدف محصول

هیچ approval یا candidate قدیمی ارسال نشود و فقط یک مسیر بسیار محدود برای پیام‌های CARE اداری، پس از revalidation کامل و deterministic، امکان AUTO_GUARDED داشته باشد.

### Policy levels

```text
CLINICIAN_ONLY
→ هرگز خودکار ارسال نمی‌شود
→ approval تازه و صریح لازم است

MANUAL_APPROVAL
→ مسیر فعلی صف تأیید حفظ می‌شود
→ approval منقضی یا stale قابل ارسال نیست

AUTO_GUARDED
→ فقط allowlist اداری CARE
→ فقط template version immutable
→ free-text ممنوع
→ هر submission نیازمند decision تازه و fail-closed است
```

### Allowlist اولیه

```text
appointment_reminder
refill_due
```

موارد زیر خودکار نیستند:

```text
lapsed
control_room_invite
invoice outreach
campaign / MARKETING
retired clinical events
هر متن مبتنی بر diagnosis، treatment یا clinical inference
```

### قرارداد ذخیره‌سازی مجاز

فقط storageهای additive و append-only زیر مجازند:

- policy version؛
- template version و content hash؛
- candidate/approval freshness snapshot؛
- automation decision event.

Storageهای موجود برای مسئولیت فعلی خود authoritative می‌مانند و destructive migration مجاز نیست.

### Pre-send revalidation اجباری

تمام موارد باید PASS باشند:

1. Flag روشن؛
2. policy هنوز `AUTO_GUARDED`؛
3. event روی allowlist دقیق؛
4. purpose برابر `CARE`؛
5. source event هنوز برای همان `period_key` معتبر و due؛
6. CARE consent فعلی `GRANTED` و head بدون تغییر؛
7. phone canonical معتبر و بدون تغییر؛
8. template version/hash بدون تغییر؛
9. body hash مطابق rendering deterministic؛
10. candidate منقضی نشده؛
11. quiet hours؛
12. global daily cap؛
13. event cooldown؛
14. عدم dispatch/idempotency قبلی؛
15. provider configured و مطابق snapshot.

هر Unknown یا Failure باید submission را رد و decision audit ثبت کند.

### Expiry و supersession

```text
TTL default = 24 hours
Allowed range = 1..72 hours
```

تغییر consent، phone، template، source period، policy یا body hash candidate را stale/superseded می‌کند. stale candidate هرگز ارسال نمی‌شود.

### Execution boundary

- GET و startup ارسال نمی‌کنند؛
- scheduler پنهان فعال نمی‌شود؛
- executor باید صریح و bounded باشد؛
- provider در تست fake/stub است؛
- scheduler health، Outbox و dead-letter برای FO-7/FO-9 باقی می‌مانند.

---

## 8. خط قرمزهای FO-6

- MARKETING/campaign/free-text auto-send؛
- auto-send برای `CLINICIAN_ONLY` یا `MANUAL_APPROVAL`؛
- تغییر Appointment؛
- clinical inference/decision/completion؛
- SMS delivery → Episode transition؛
- Outbox/dead-letter/cross-channel state machine؛
- retry worker جدید؛
- Rule/Hypoglycemia Shadow؛
- Write به `clinic_new.db`؛
- شروع FO-7 تا FO-10.

---

## 9. Exit Gate FO-6

```text
FO-5 owner acceptance Issue #107                = PASS
FO-6 governance authorization Issue #109/PR #110 = AUTHORIZED
Immutable policy/template/candidate/decision     = PENDING
Exact CARE allowlist                             = PENDING
Pre-send freshness revalidation                  = PENDING
Expiry and append-only supersession              = PENDING
Quiet/cap/cooldown/provider fail-closed           = PENDING
Replay/concurrency one-winner                     = PENDING
No GET/startup send                               = PENDING
No campaign/MARKETING/free-text/clinical auto-send = PENDING
Full CI                                            = PENDING
Local Owner UX Acceptance                         = PENDING
FO-7 governance authorization                     = BLOCKED
```

---

## 10. Roadmap و درصد پیشرفت

```text
FO-0..FO-5 validated with required acceptance = 6.0
FO-6 authorized/not started = 0.0
FO-7..FO-10 blocked = 0.0
Progress = 6.0 / 11 = 54.5%
Remaining = 45.5%
```

این درصد فقط FOUX-V1 است و معیار آمادگی Production کل مطب نیست.

---

## 11. تصمیم فعلی

```text
FO-0..FO-5 = VALIDATED WITH REQUIRED ACCEPTANCE
FO-6 = AUTHORIZED / IMPLEMENTATION PENDING
CURRENT ISSUE = #109
FEATURE FLAG = FOLLOWUP_SMS_AUTO_GUARDED (default OFF)
FO-7 AND LATER = BLOCKED
```

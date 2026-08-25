# وصلهٔ پیشنهادی PROJECT_STATE.md — Cutover خواندن یکپارچه

> **هدف:** اعمال دستی توسط مالک پس از امضای `GOVERNANCE_NOTE_CUTOVER_FA.md`.
>
> **فایل هدف:** `PROJECT_STATE.md` (ریشهٔ workspace، کنار `specialist_clinic/`).
>
> **پیش‌نیاز:** کامیت cutover روی `main` merge شده باشد؛ `<CUTOVER_COMMIT_SHA>` جایگزین شود.
>
> هر هانک مستقل است؛ فقط بلوک‌های BEFORE را با AFTER جایگزین کنید. هیچ بخش دیگری از فایل تغییر نمی‌کند.

---

## Hunk 1 — جدول «جریان‌ها» (ردیف FOUX-V1)

**BEFORE:**

```markdown
| FOUX-V1 | `FO_0..FO_5_VALIDATED / FO_6_AUTHORIZED` | فقط پیاده‌سازی محدود SMS CARE اداری تحت Issue #109 | FO-7+، کمپین/MARKETING و اتوماسیون بالینی |
```

**AFTER:**

```markdown
| FOUX-V1 | `FO_0..FO_5_VALIDATED / FO_6_AUTHORIZED` | فقط پیاده‌سازی محدود SMS CARE اداری تحت Issue #109؛ خواندن Unified Work Center همیشه فعال (cutover مالک‌تأیید 2026-08-24، revert `<CUTOVER_COMMIT_SHA>`) | FO-7+، کمپین/MARKETING و اتوماسیون بالینی |
```

---

## Hunk 2 — بخش «Feature Flags»

**BEFORE:**

`````markdown
## Feature Flags

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
`````

**AFTER:**

`````markdown
## Feature Flags

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

استثنای cutover (دستور مالک 2026-08-24): `FOLLOWUP_UNIFIED_WORKLIST_READONLY` دیگر مسیرهای GET فهرست/جزئیات Unified Work Center را gate نمی‌کند. مقدار اعلامی این Flag همچنان OFF است اما خاموش‌کردنش رفتار legacy را برنمی‌گرداند؛ بازگشت فقط با `git revert <CUTOVER_COMMIT_SHA>` ممکن است. بقیهٔ Flagها بدون تغییر gate می‌شوند و همهٔ Flagهای اقدامی (Actions/Auto-Routing/Structured-Contact/SMS) OFF باقی می‌مانند.
`````

---

## Hunk 3 — بخش «Exact continuation point»

**BEFORE:**

`````markdown
## Exact continuation point

```text
CURRENT = FO-6 Governed SMS Automation & Freshness implementation
ISSUE = #109
BASE = main after governance PR #110
ALLOWED = bounded administrative CARE SMS implementation only
FO-7 AND LATER = BLOCKED
```
`````

**AFTER:**

`````markdown
## Exact continuation point

```text
CURRENT = FO-6 Governed SMS Automation & Freshness implementation
ISSUE = #109
BASE = main after governance PR #110 + unified-worklist read cutover (owner-approved 2026-08-24, commit <CUTOVER_COMMIT_SHA>)
ALLOWED = bounded administrative CARE SMS implementation only
READ CUTOVER = unified work center GET index/detail always-on; legacy followups/worklist.html removed with 302 shim; rollback = revert only
FO-7 AND LATER = BLOCKED
```
`````

---

## خارج از محدودهٔ این وصله

- `PROJECT_STATE.json` در این بسته تغییر داده نمی‌شود؛ اگر مالک بخواهد، به‌روزرسانی جداگانهٔ `feature_flags`/`implemented_contracts.ui_mode` لازم خواهد بود (پیشنهاد: در همان PR حاکمیتی ثبت شود).
- هیچ ردیف دیگری از جدول جریان‌ها، بخش‌های FO-0..FO-6 یا Exit Gate FO-6 تغییر نمی‌کند.

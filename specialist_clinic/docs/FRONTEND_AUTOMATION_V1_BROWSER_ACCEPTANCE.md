# Frontend Automation v1 — Browser Acceptance

**Status:** `PENDING_OWNER_BROWSER_REVIEW`  
**Review branch:** `fix/frontend-automation-v1-browser-acceptance`  
**Scope:** Repair 1 through Repair 5 together; no product-code changes belong to Repair 6.

## 1. Automated evidence already complete

- Specialist Clinic: **854 passed**
- Accounting: **success**
- Doctor Queue canonical and legacy routes: covered
- Work Center ownership, Handle and Auto-next: covered
- Patient Workspace five-tab composition and legacy hashes: covered
- Clinical Engine simple/advanced routing: covered
- Message Center five destinations and single Settings write seam: covered

Automated tests are necessary but do not replace observation in a real browser. The
stack must not merge to `main` until the checks below are recorded as PASS.

## 2. Safe local preparation on Windows

Use a disposable or copied Specialist database. Do not run acceptance mutations on the
only copy of real clinic data.

```powershell
git clone --branch fix/frontend-automation-v1-browser-acceptance `
  https://github.com/Emad211/clinic_managment.git
cd clinic_managment\specialist_clinic

py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Dedicated review database.
$env:SPECIALIST_DB_PATH = Join-Path $PWD "specialist.browser-review.db"

# Work Center capabilities implemented through FO-5.
$env:FOLLOWUP_EPISODES_ENABLED = "1"
$env:FOLLOWUP_PROJECTION_SHADOW = "1"
$env:FOLLOWUP_UNIFIED_WORKLIST_READONLY = "1"
$env:FOLLOWUP_UNIFIED_WORKLIST_ACTIONS = "1"
$env:FOLLOWUP_AUTO_ROUTING = "1"
$env:FOLLOWUP_STRUCTURED_CONTACT = "1"

# Later capabilities remain outside this frontend review.
$env:FOLLOWUP_SMS_AUTO_GUARDED = "0"
$env:FOLLOWUP_APPOINTMENT_SYNC = "0"
$env:FOLLOWUP_EVIDENCE_ASSIST = "0"
$env:FOLLOWUP_AUTOMATION_HEALTH = "0"

# Rebuild only the canonical synthetic TEST0001..TEST0010 cohort.
.\.venv\Scripts\python.exe seed_demo_data.py

# Optional: point to a copied accounting database to review a populated doctor queue.
# $env:ACCOUNTING_DB_PATH = "C:\path\to\copied\clinic_new.db"

.\.venv\Scripts\python.exe start.py
```

Open `http://127.0.0.1:8090` and sign in with `admin` / `admin`.
Closing this PowerShell window clears the process-level feature flags. Delete
`specialist.browser-review.db` after acceptance if it is no longer needed.

## 3. Required viewports

Review every primary flow at both widths:

| View | Required viewport |
|---|---:|
| Desktop | 1440 × 900 |
| Mobile | 360 × 800 |

At mobile width, use browser DevTools responsive mode. Do not accept a page solely by
resizing the desktop window without reloading it.

## 4. Acceptance scenarios

### A. Shell and navigation

- [ ] Login is a simple, usable form and redirects to the correct home.
- [ ] Desktop sidebar shows only role-allowed destinations.
- [ ] Mobile menu opens and closes by button, outside click and `Escape`.
- [ ] Mobile bottom navigation remains visible without covering the active form action.
- [ ] Global patient search is reachable by keyboard.
- [ ] There is no primary navigation entry for Control Room, legacy worklists or raw Shadow tools.

### B. Dashboard

- [ ] The page answers “what needs attention now?” without becoming another worklist.
- [ ] The primary action reaches Work Center.
- [ ] Doctor Queue, appointments and patients are reachable without duplicate destinations.
- [ ] Summary cards do not leak internal policy, event or snapshot identifiers.

### C. Work Center

- [ ] The visible tabs are `کارهای من`, `بدون مسئول`, `همهٔ کارهای باز`, `تکمیل‌شده` and manager view only for a permitted manager.
- [ ] Each row has one primary action: `رسیدگی` or `مشاهده نتیجه`.
- [ ] Opening an unassigned permitted item through `رسیدگی` claims it and opens the workspace without a separate Claim screen.
- [ ] Search and filters survive returning from item detail.
- [ ] Assignment, routing, timeline and technical details remain collapsed by default.
- [ ] A successful contact result opens the next item in the same view.
- [ ] No next item opens when the server rejects the contact result.
- [ ] At 360 px, cards do not cause horizontal page scrolling.

### D. Patient Workspace

- [ ] Exactly five tabs are visible: `خلاصه`, `اقدامات`, `داده‌های بالینی`, `دارو و نسخه`, `ویزیت‌ها و اسناد`.
- [ ] Keyboard arrows, Home and End move between tabs and update focus.
- [ ] The patient header remains available while scrolling and becomes compact without hiding critical identity.
- [ ] Allergy, next appointment, last physician and next action remain understandable.
- [ ] Existing forms still submit to their original endpoints.
- [ ] Returning after a form POST restores only the selected UI tab; no patient data appears in browser storage.
- [ ] Legacy hashes such as `#trends`, `#record`, `#meds`, `#labs` and `#vitals` open the appropriate new tab.
- [ ] Technical IDs and engine reason codes are not visible until technical details are opened.

### E. Doctor Queue and Encounter

With a copied accounting DB containing open visit invoices:

- [ ] Queue sections are visibly separate: `در حال ویزیت`, `منتظر`, `تکمیل‌شده امروز`.
- [ ] The current visit is not duplicated in the waiting list.
- [ ] Only an explicit click on `شروع ویزیت` starts a visit.
- [ ] Optional appointment/campaign linking is collapsed.
- [ ] Encounter shows the three approved sections and a sticky action area.
- [ ] `ذخیره پیش‌نویس` performs a real server save; the UI never claims background autosave.
- [ ] `پایان ویزیت` shows the single irreversible-action confirmation.
- [ ] After successful finalisation, the queue returns and focuses the next patient without starting that visit.

Without a usable accounting DB:

- [ ] Queue shows the controlled unavailable state and does not invent patient rows.

### F. Appointments

- [ ] List, date range and status filters remain usable on desktop and 360 px.
- [ ] Each scheduled row has one primary action and overflow for no-show/cancel.
- [ ] New appointment fields remain the existing server contract.
- [ ] Reversible status changes do not introduce extra confirmation dialogs.

### G. Message Center and Settings

- [ ] Message Center has exactly five destinations: approvals, campaigns, automations, delivery report and advanced settings.
- [ ] Advanced settings is visible only to an authorised manager.
- [ ] Opening advanced settings keeps the Message Center context.
- [ ] Only SMS Provider and cost/message sections are foregrounded there.
- [ ] Saving uses the existing single Settings endpoint and returns to the advanced Message Center tab.
- [ ] Hidden general Settings values are preserved after this save.
- [ ] Clearing a stored secret is the only Settings action that asks for confirmation.

### H. Clinical Engine

- [ ] The default page is a short status landing with one next action.
- [ ] No governed mutation form appears on the landing page.
- [ ] `بخش پیشرفته` opens the existing seven-step governed workflow.
- [ ] Permission-denied or validation failures return to the advanced workflow with a clear message.
- [ ] No raw hashes, report payloads or internal IDs appear on the simple landing.

### I. Users and Finance

- [ ] Users render as readable cards on 360 px with no horizontal page scroll.
- [ ] All inputs have visible labels; password remains a password input.
- [ ] Token rotation remains an explicit confirmed action.
- [ ] Finance primary review controls are keyboard reachable with visible focus.
- [ ] Finance controls meet the 44 px mobile target.
- [ ] Only reversal of a recorded correction asks for confirmation.
- [ ] Accounting values remain visibly read-only.

### J. Error, empty and unavailable states

- [ ] 403/404/500 pages use the same shell and do not expose stack traces.
- [ ] Empty Work Center, empty queue and empty appointment views explain the next safe action.
- [ ] Unavailable data never falls back to guessed clinical or accounting state.

## 5. Required evidence

Capture at least these screenshots:

1. Desktop dashboard
2. Desktop Work Center
3. Mobile Work Center at 360 px
4. Desktop Patient Workspace summary
5. Mobile Patient Workspace actions tab
6. Doctor Queue with all three states, or its controlled unavailable state
7. Encounter sticky actions on mobile
8. Message Center with five tabs
9. Clinical Engine simple landing
10. Users or Finance mobile view

Record console errors and failed network requests. A page with an uncaught JavaScript
error, HTTP 500, clipped primary action or horizontal body scroll is FAIL.

## 6. Result record

| Area | Desktop | Mobile 360 | Keyboard | Result / note |
|---|---|---|---|---|
| Shell and dashboard | PENDING | PENDING | PENDING | |
| Work Center | PENDING | PENDING | PENDING | |
| Patient Workspace | PENDING | PENDING | PENDING | |
| Queue and Encounter | PENDING | PENDING | PENDING | |
| Appointments | PENDING | PENDING | PENDING | |
| Message Center and Settings | PENDING | PENDING | PENDING | |
| Clinical Engine | PENDING | PENDING | PENDING | |
| Users and Finance | PENDING | PENDING | PENDING | |
| Errors and unavailable states | PENDING | PENDING | PENDING | |

## 7. Merge gate

The frontend may be described as complete only when:

1. every required row above is PASS;
2. no severity-1 or severity-2 browser defect remains;
3. the screenshot set is attached to the final review;
4. the stacked repair branches are merged in order;
5. CI is green again on the resulting `main` head.

Until then, `FRONTEND_AUTOMATION_V1_COMPLETION_REPORT.md` remains withdrawn and the
frontend must not be reported as complete.

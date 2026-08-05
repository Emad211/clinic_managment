# Frontend Automation V1 — Reality Gap Audit

**Audit date:** 2026-08-05  
**Audited baseline:** `main@4d0fe69c23cfbe5fd7ca0607a4f10a967e3a7356`  
**Source of truth:** `FRONTEND_AUTOMATION_V1_IMPLEMENTATION_PLAN.md`  
**Status:** the previous completion claim is withdrawn. The implementation is partial and requires corrective delivery.

## 1. Executive finding

The current frontend is not a completed automation-first workspace. It contains useful partial redesigns, but the global shell, information architecture and cross-page workflow orchestration were not implemented as specified.

The most visible proof is the application shell:

- the sidebar still renders the legacy destinations and labels;
- `Control Room` remains a primary destination;
- `Work Center` is not rendered natively by the shell;
- labels are changed after page load by JavaScript only on templates that opt into `automation_base.html`;
- error pages and legacy templates therefore show the old navigation;
- no role-aware mobile bottom navigation exists;
- the Doctor Queue primary path was not browser-smoke-tested and is reported as returning 404 in a clean local run.

Estimated plan completion at this baseline: **about 31%**, not 100%.

## 2. Plan-to-code assessment

| Area | Target | Proven current state | Estimated completion |
|---|---|---|---:|
| Shared foundation | Native shared shell, role-aware sidebar, mobile bottom navigation, search, drawer, toast, loading/empty/error primitives | Automation CSS/JS exists, but only selected templates opt in; no native role-aware shell, bottom navigation, global search or shared task drawer | 35% |
| Information architecture | One primary home per capability; legacy destinations demoted | Legacy Control Room and old labels remain in `base.html`; Work Center is injected by JS on some pages | 15% |
| Work Center | My/Unassigned/All/Completed tabs, one Handle action, task drawer, auto-claim, auto-complete, auto-next | Unified list/detail redesigned; automatic filters and quick contact outcomes exist; tabs, drawer, true auto-claim and next-item orchestration are missing | 45% |
| Patient Workspace | Sticky header and five target tabs with contextual actions | Existing record received partial styling, consent and clinical-suggestion simplification; the target five-tab architecture and unified action surface are incomplete | 30% |
| Doctor Queue / Encounter | Reliable queue route, next-patient flow, preload brief, autosave where safe, one final confirmation | Templates were simplified; route reliability was not browser-smoke-tested; reported 404; no next-patient redirect and no safe server autosave | 35% |
| Appointments | Today/list views, compact filters, one-click routine states, contextual booking | List and creation forms were improved; calendar/today workflow and full task-context continuity remain incomplete | 55% |
| Message Center | Needs approval, campaigns, automations, delivery, advanced; individual messaging in patient context | Four-tab header exists, but advanced automation integration and patient-context messaging consolidation are incomplete | 35% |
| Management | Simple/advanced Clinical Engine, split independently saved settings, users, finance | Finance and settings presentation improved; settings still submit one monolithic form; Clinical Engine remains the large legacy wizard | 25% |
| Polish and QA | 360px QA, route smoke, keyboard, visual regression, real browser verification | Unit/contract CI passed, but visual and primary-route browser acceptance was not performed before the completion claim | 20% |

## 3. Incorrect completion claims

The previous completion report overstated these items:

1. **Role-aware navigation:** not implemented natively.
2. **Global shell:** only a subset of pages uses the automation layer.
3. **Work Center consolidation:** legacy destinations remain visible and operationally primary.
4. **Doctor Queue availability:** template tests passed, but the real browser path was not verified.
5. **Patient Workspace completion:** only partial component-level changes landed.
6. **Settings split:** visual sections exist, but independent save surfaces do not.
7. **Clinical Engine simplification:** the original multi-step governance wizard remains.
8. **Mobile navigation:** off-canvas sidebar exists; the specified bottom navigation does not.
9. **Visual acceptance:** no evidence of desktop and 360px browser acceptance was attached before merge.

## 4. Corrective delivery gates

### Repair 1 — Global shell and route reliability

- Replace JavaScript label rewriting with native Jinja navigation.
- Render exact destinations from the approved IA.
- Gate destinations by effective permissions.
- Remove Control Room and other duplicate pages from primary navigation.
- Add mobile bottom navigation.
- Make Doctor Queue accept canonical and no-trailing-slash paths.
- Add route-map and authenticated smoke tests for every primary destination.

### Repair 2 — Work Center

- Add My work, Unassigned, All and Completed filters/tabs using existing query capabilities.
- Remove the separate Claim ceremony from normal flow where the existing guarded endpoint permits it.
- Keep one primary `رسیدگی` action.
- Implement next-item continuation after successful guarded actions.
- Move assignment, routing, contact and timeline into a consistent action workspace/drawer pattern.

### Repair 3 — Patient Workspace

- Implement the approved five-tab architecture.
- Keep patient identity and next action visible while scrolling.
- Move contact, appointment and measurement actions into patient context.
- Hide technical and governance metadata by default.

### Repair 4 — Queue and Encounter

- Prove Queue GET and visit-start routes in an authenticated runtime test.
- Add an explicit empty/unavailable state instead of route failure.
- Implement next-patient continuation after successful finalisation.
- Preserve the deliberate no-fake-autosave boundary until a safe draft endpoint exists.

### Repair 5 — Remaining surfaces

- Complete Message Center advanced section.
- Split Settings into independent save contracts only when backend endpoints safely support it.
- Create a simple Clinical Engine landing view while retaining governance actions under Advanced.
- Finish users and finance mobile/keyboard flows.

### Repair 6 — Acceptance

A corrective PR may merge only after:

- complete Specialist and Accounting CI is green;
- every primary navigation destination has an authenticated route smoke test;
- the shell is identical on normal, error and unavailable pages;
- screenshots or a written browser checklist cover desktop and 360px mobile;
- the completion report is updated to list proven outcomes and remaining gaps only.

## 5. Immediate continuation point

The exact continuation point is **Repair 1: global shell and Doctor Queue reliability**. No further visual polishing should precede that repair.
# Graph Report - .  (2026-07-21)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1384 nodes · 3250 edges · 115 communities (79 shown, 36 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 266 edges (avg confidence: 0.77)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ac5d7bcb`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- js
- jquery.min.js
- _
- SmsRepository
- MedianaProvider
- accounting_bridge.py
- jalali_to_gregorian_str
- patients.py
- ClinicalRulesRepository
- ns
- sms.py
- zt
- iran_now
- an
- PatientRepository
- FollowupRepository
- update
- buildTicks
- updateElements
- n
- bn
- control_room_service.py
- base.html (RTL Jalali Layout)
- ClinicalFlagsRepository
- revenue_service.py
- Scheduler
- Patient Record (one-page snapshot)
- core.py
- destroy
- fa
- rule_engine.py
- Do
- clinical_rules (ADA If/Then catalog)
- engagement_service.py
- hi
- no
- persian-datepicker.min.js
- AppointmentRepository
- tn
- configure
- .get
- SGLT2 inhibitor (SGLT2i)
- clinical_rules_seed.py
- EngagementRepository
- bt
- s
- Red Flags (immediate referral: severe hypo, DKA/HHS, BP≥180/110, Fournier gangrene)
- Hypoglycemia classification (Level 1/2/3, Table 6.4)
- Patient Analytics Dashboard
- ._notify
- vitals_service.THRESHOLDS (warn/high threshold map)
- GLP-1 receptor agonist (GLP-1 RA)
- kavenegar_provider.py
- Engine B — Event to Channel Engagement Engine
- EngagementService.dispatch_patient
- Manager — ADA Decision Rules editor (decision_rules.html)
- ._handleEvent
- Glycemic target (A1c <7.0%, pre-meal 80-130, peak <180)
- Complication screening schedule (eye/foot/neuropathy/renal/lipid)
- CSS variable tokens (app.css: surfaces/lines/text/semantic/spacing/radius)
- Clinic Dashboard
- constructor
- validators.py
- KavenegarProvider.send
- es
- ADA Standards of Care in Diabetes 2026
- Rule T2-MED-ASCVD-01 (ASCVD → GLP-1 RA and/or SGLT2i, independent of A1c)
- SMS via Mediana integration
- AvalAI unified AI API gateway
- Revenue & Campaign Performance Block
- persian-date.min.js
- BMI / weight indicator
- A1c follow-up cadence (3 months off-target / 6 months stable)
- Diabetes classification (T1/T2/special/GDM)
- DSMES (diabetes self-management education and support)
- ADA evidence levels (A/B/C/E)
- HDL cholesterol indicator
- MNT (medical nutrition therapy)
- Physical activity (≥150 min/week aerobic + resistance)
- Diabetes screening criteria (Table 2.5, age 35, BMI thresholds)
- Statin (lipid-lowering therapy)
- Triglyceride indicator
- src/common cross-cutting utils
- followup_tasks table / worklist
- Offline by design (vendored front-end libs)
- Accounting Sync — Deferred Payment Reminder at Visit
- Engagement Engine Phase Status (0-4 complete)
- Kavenegar account/info endpoint (credit check)
- Kavenegar sms/send endpoint spec
- Row
- SendResult
- SmsProvider
- patient_links Local Mirror Model
- Specialist Clinic Flask App
- Threshold-sync Rule (clinical_indicators vs fallback constants)
- start.py (frozen-mode launcher)
- control_room Blueprint
- dashboard Blueprint
- followups Blueprint
- COHORT_DEFS (prioritized cohort segments)
- REASON_LABELS
- Appointments — list + filter + status actions (list.html)
- Login Page
- sms/campaign_detail.html (campaign KPIs + incrementality)
- sms/_hub_tabs.html (messaging hub tab bar)
- manager/index.html

## God Nodes (most connected - your core abstractions)
1. `_()` - 266 edges
2. `update()` - 109 edges
3. `js()` - 70 edges
4. `an()` - 60 edges
5. `SmsRepository` - 59 edges
6. `ns()` - 55 edges
7. `draw()` - 46 edges
8. `get_db()` - 44 edges
9. `constructor()` - 43 edges
10. `n()` - 33 edges

## Surprising Connections (you probably didn't know these)
- `Pending SMS Pattern (timeout ≠ failure, no retry)` --rationale_for--> `KavenegarProvider.send()`  [INFERRED]
  specialist_clinic/CLAUDE.md → src/services/sms/kavenegar_provider.py
- `Timeout→Pending pattern (not failed, no retry)` --rationale_for--> `KavenegarProvider.send()`  [EXTRACTED]
  docs/kavenegar_reference.md → src/services/sms/kavenegar_provider.py
- `Event→Channel Routing Table (seed defaults)` --rationale_for--> `CHANNELS (sms|worklist|both|off)`  [INFERRED]
  docs/engagement_engine_plan.md → src/adapters/sqlite/engagement_repo.py
- `suggestion_log table (accountability trail)` --references--> `clinical_rules (ADA If/Then catalog)`  [INFERRED]
  CLAUDE.md → specialist_clinic/CLAUDE.md
- `clinical_rules_seed.py (~50 ADA rules seed)` --cites--> `ADA Standards of Care in Diabetes 2026`  [EXTRACTED]
  docs/treatment_engine_plan.md → ada_t2_rules.md

## Import Cycles
- 1-file cycle: `src/common/utils.py -> src/common/utils.py`

## Hyperedges (group relationships)
- **Closed Care Loop Workflow** — docs_record_redesign_plan_closed_care_loop, docs_phase3_doctor_queue_plan_doctor_queue, src_templates_followups_worklist_followup_worklist, src_templates_manager_engagement_engagement_rules [INFERRED 0.95]
- **SMS Delivery Stack** — specialist_clinic_readme_mediana_sms, docs_mediana_reference_mediana_protocol, src_templates_manager_settings_provider_settings, src_templates_sms_campaigns_campaign_builder [INFERRED 0.95]
- **Engagement Dispatch Guardrail System (opt-out, quiet hours, daily cap, cooldown, idempotency)** — engagement_service_engagementservice_dispatch_patient, engagement_repo_engagementrepository_already_dispatched, engagement_repo_engagementrepository_in_cooldown, engagement_repo_engagementrepository_sms_count_today, engagement_repo_engagementrepository_record_dispatch [EXTRACTED 1.00]
- **Control Room Cohort Action (panel → cohort → recall/sms)** — services_control_room_service_panel, services_control_room_service_cohort_ids, api_control_room_recall, api_control_room_sms, sqlite_followups_repo_create [EXTRACTED 0.90]

## Communities (115 total, 36 thin omitted)

### Community 0 - "js"
Cohesion: 0.05
Nodes (37): afterDraw(), afterUpdate(), b(), Ci(), d(), draw(), ea(), eo() (+29 more)

### Community 1 - "jquery.min.js"
Cohesion: 0.07
Nodes (29): Ae(), Ie(), Y(), A(), at(), b(), be(), ce() (+21 more)

### Community 2 - "_"
Cohesion: 0.06
Nodes (30): _(), afterEvent(), ai(), As(), be(), beforeLayout(), ct(), Di() (+22 more)

### Community 3 - "SmsRepository"
Cohesion: 0.09
Nodes (12): get_db(), Return the per-request connection to the specialist DB (created on first use)., rows = [(patient_link_id, accounting_patient_id, grp), ...]., True if any SMS panel (Kavenegar or Mediana) has an API key set., SmsRepository, Apply a credit (+) or debit (-) and record a transaction. Returns new balance., WalletRepository, _patient() (+4 more)

### Community 4 - "MedianaProvider"
Cohesion: 0.11
Nodes (24): SendResult, _field(), MedianaProvider, Mediana SMS provider adapter (https://api.mediana.ir).  Auth: header `X-API-KEY:, Return the panel wallet balance, or None on failure., Read Mediana fields in both documented PascalCase and live camelCase., BatchItemResult, BatchSendResult (+16 more)

### Community 5 - "accounting_bridge.py"
Cohesion: 0.09
Nodes (37): _chunks(), _connect_ro(), daily_revenue_for_accounting_ids(), daily_revenue_for_enrolled(), get_patient_by_id(), get_patient_by_national_id(), get_visit_history(), is_available() (+29 more)

### Community 6 - "jalali_to_gregorian_str"
Cohesion: 0.09
Nodes (23): list_appointments(), new_appointment(), set_status(), login_required(), index(), Physician-first clinic-at-a-glance: who needs attention today, plus business KPI, Iran local time (UTC+3:30) convention, Jalali dates everywhere convention (+15 more)

### Community 7 - "patients.py"
Cohesion: 0.08
Nodes (23): add_condition(), add_medication(), change_dose(), enroll_accounting(), enroll_manual(), generate_followups(), list_patients(), medication_effect() (+15 more)

### Community 8 - "ClinicalRulesRepository"
Cohesion: 0.10
Nodes (17): detail(), ClinicalRulesRepository, evaluate(), _num(), Clinical rule evaluation: direction-aware red-flag logic driven by the editable, Return 'danger' | 'warn' | 'ok' for a value against one indicator rule.      Hon, evaluate_reading(), _fallback_eval() (+9 more)

### Community 9 - "ns"
Cohesion: 0.12
Nodes (4): labelColor(), labelPointStyle(), ns(), vs()

### Community 10 - "sms.py"
Cohesion: 0.11
Nodes (24): Repository for SMS templates, campaigns, messages, and key/value settings., add_template(), api_check(), api_recipients(), approvals(), campaign_detail(), campaigns(), messages_report() (+16 more)

### Community 11 - "zt"
Cohesion: 0.11
Nodes (14): Bi(), color(), Ee(), Ft(), It(), jt(), kt(), mt() (+6 more)

### Community 12 - "iran_now"
Cohesion: 0.10
Nodes (12): login(), logout(), AuthRepository, activity_logs table, Auth & roles (manager/staff, bcrypt, lockout), iran_now(), Return current Tehran time as a naive datetime.      The DB stores timestamps as, Lightweight activity logger for the specialist app. (+4 more)

### Community 13 - "an"
Cohesion: 0.14
Nodes (5): an(), cn(), dn(), Mn(), onClick()

### Community 14 - "PatientRepository"
Cohesion: 0.09
Nodes (6): Today's Gregorian date as 'YYYY-MM-DD' (Iran time)., today_str(), PatientRepository, Scan patients and open follow-up tasks (idempotent — no duplicates while open)., PatientRepository, Repository for patient_links and their chronic-care records.

### Community 15 - "FollowupRepository"
Cohesion: 0.11
Nodes (15): add_manual(), generate(), resolve(), worklist(), FollowupRepository, Generates and manages follow-up worklist tasks., FollowupRepository, Repository for follow-up tasks (worklist). (+7 more)

### Community 16 - "update"
Cohesion: 0.16
Nodes (8): aa(), afterDatasetsUpdate(), jn, la(), oa(), ta(), u(), update()

### Community 17 - "buildTicks"
Cohesion: 0.14
Nodes (17): bo, buildTicks(), En, et(), _generate(), getLabelForValue(), H(), init() (+9 more)

### Community 18 - "updateElements"
Cohesion: 0.17
Nodes (16): ca(), _calculateBarIndexPixels(), _calculateBarValuePixels(), getBasePixel(), getLabelAndValue(), getPixelForValue(), _getRuler(), _getStackCount() (+8 more)

### Community 19 - "n"
Cohesion: 0.20
Nodes (18): a(), determineDataLimits(), Fn(), Fo(), Gn(), go(), ko, l() (+10 more)

### Community 20 - "bn"
Cohesion: 0.14
Nodes (8): at(), bn, e(), K(), on(), pn(), xn(), Ye()

### Community 21 - "control_room_service.py"
Cohesion: 0.15
Nodes (15): index(), Patient Control Room — prioritized cohort targeting with one-click recall.  Visi, Open a 'recall' worklist call-task for everyone in the chosen cohort., Send a one-off invitation SMS to everyone in the cohort (opt-out respected)., recall(), _show_value(), sms(), Patient Control Room: a prioritized, cohort-segmented view of who needs attentio (+7 more)

### Community 22 - "base.html (RTL Jalali Layout)"
Cohesion: 0.21
Nodes (20): De-ADA (UI strings only), Merged Per-Disease Manager Page Plan, appointments/list.html (Appointment List), CLINIC_THEME Chart Theme + Datepicker Bootstrap, base.html (RTL Jalali Layout), Sidebar Navigation (operations + system), Lucide-style SVG Icon Sprite, Patients Needing Attention Section (+12 more)

### Community 23 - "ClinicalFlagsRepository"
Cohesion: 0.14
Nodes (8): analytics(), Merged into the unified patient cockpit; kept as a stable deep-link to the trend, main(), trend(), ClinicalFlagsRepository, _parse_options(), Repository for clinical decision inputs: flag_catalog, patient_flags, drug_class, HFrEF|EF کاهش‌یافته,unknown|نامشخص' -> [{value,label}, ...]

### Community 24 - "revenue_service.py"
Cohesion: 0.13
Nodes (12): format_jalali_date(), Format datetime (or 'YYYY-MM-DD' string) as Jalali date only., _jalali_month_start_gregorian(), Revenue analytics for the specialist clinic, sourced from the accounting DB (rea, Gregorian 'YYYY-MM-DD' of the first day of the current Jalali month., Causal lift for a campaign that used a holdout/control group.          Compares, Top-level revenue numbers + 30-day trend for enrolled patients., (accounting_patient_id, enrollment_date 'YYYY-MM-DD') for active linked patients (+4 more)

### Community 25 - "Scheduler"
Cohesion: 0.16
Nodes (7): init_scheduler(), Background scheduler: appointment reminders, scheduled campaigns, follow-up gene, Weekly snapshot of THIS app's DB (specialist.db; the accounting DB is never, Run the unified engagement engine: due reminders + follow-ups -> SMS/worklist., Read-only invoice-sync consumer (ADR-0003 D3+): record recently-closed         a, Scheduler, DeliveryService

### Community 26 - "Patient Record (one-page snapshot)"
Cohesion: 0.12
Nodes (18): accounting_bridge (read-only accounting DB), vitals_service (THRESHOLDS / leveling), Per-Disease Indicator Tiles, Patient Record (one-page snapshot), Allergies Manager, Conditions Manager, Labs Table & Entry, Medications Manager (start/dose/stop) (+10 more)

### Community 27 - "core.py"
Cohesion: 0.14
Nodes (15): _ensure_column(), _ensure_default_admin(), init_db_command(), _load_schema_text(), Additive migrations for existing DBs (new tables come from schema IF NOT EXISTS), Load bundled schema.sql in both source and frozen (PyInstaller) modes., Create a default manager account (admin/admin) if no users exist., CLI helper: (re)apply schema. (+7 more)

### Community 28 - "destroy"
Cohesion: 0.16
Nodes (7): destroy(), fs(), ls, rs, rt(), updateRangeFromParsed(), ws

### Community 29 - "fa"
Cohesion: 0.18
Nodes (11): beforeDatasetDraw(), beforeDatasetsDraw(), da(), fa(), ga(), ha, ii(), na() (+3 more)

### Community 30 - "rule_engine.py"
Cohesion: 0.17
Nodes (10): ADA clinical decision-support engine, drug_classes table, flag_catalog + patient_flags tables, Suggestion-only, physician-decides, logged principle, _age_from_birthdate(), Rule engine: builds a patient fact-bundle and evaluates the editable clinical_ru, Return the list of fired rules for a patient (suggestion-only)., Fired rules grouped into UI sections, in display order. (+2 more)

### Community 31 - "Do"
Cohesion: 0.18
Nodes (15): ao(), average(), co(), Do(), getCenterPoint(), getDecimalForValue(), ho(), Hs (+7 more)

### Community 32 - "clinical_rules (ADA If/Then catalog)"
Cohesion: 0.14
Nodes (16): clinical_rules_seed.py (seed_clinical_rules), core.py get_db() / bootstrap, schema.sql (source of truth), ADA clinical reference docs (clinical_reference.md, ada_t2_rules.md), Idempotent schema + additive runtime migrations (no migration framework), suggestion_log table (accountability trail), Threshold-sync rule (indicators + fallbacks + docs), trigger_json all/any/not + leaf DSL (+8 more)

### Community 33 - "engagement_service.py"
Cohesion: 0.19
Nodes (8): Engagement Engine Architecture (Engine B), Event→Channel Routing Table (seed defaults), SMS Guardrails (quiet hours, daily cap, opt-out), Engagement engine (event -> channel) — the dispatcher that unifies automated rem, Dry-run snapshot: exactly what the engine would do right now, per patient,, True if the current Tehran time is OUTSIDE the allowed sending window., Return (events, cfg) where events is a list of due events for the patient, CHANNELS (sms|worklist|both|off)

### Community 34 - "hi"
Cohesion: 0.22
Nodes (11): beforeDraw(), dataset(), hi(), _i(), index(), inRange(), ji(), Re() (+3 more)

### Community 35 - "no"
Cohesion: 0.18
Nodes (6): buildLookupTable(), _getTimestampsForTable(), initOffsets(), lt(), no, zi()

### Community 36 - "persian-datepicker.min.js"
Cohesion: 0.18
Nodes (9): a(), c(), d(), e(), i(), n(), r(), s() (+1 more)

### Community 37 - "AppointmentRepository"
Cohesion: 0.13
Nodes (5): AppointmentRepository, AppointmentRepository, Repository for appointments., date_from/date_to are gregorian 'YYYY-MM-DD'. Returns appts with patient name., Scheduled appts within the next N hours that haven't had a reminder sent.

### Community 38 - "tn"
Cohesion: 0.24
Nodes (3): addElements(), tn, w()

### Community 39 - "configure"
Cohesion: 0.22
Nodes (6): beforeUpdate(), configure(), initialize(), ke(), reset(), wn()

### Community 40 - ".get"
Cohesion: 0.20
Nodes (5): ce(), de, getPixelForTick(), he(), qs()

### Community 41 - "SGLT2 inhibitor (SGLT2i)"
Cohesion: 0.21
Nodes (13): ACEi/ARB (RAS inhibition), eGFR (estimated glomerular filtration rate, CKD-EPI 2021), Finerenone (nsMRA), Heart failure (HF, HFrEF/HFpEF), Metformin (oral, historic first-line), Rule T2-MED-CKD-01 (CKD → SGLT2i or GLP-1 RA; finerenone), Rule T2-MED-HF-01 (HF → SGLT2i; TZD contraindicated), SGLT2 inhibitor (SGLT2i) (+5 more)

### Community 42 - "clinical_rules_seed.py"
Cohesion: 0.17
Nodes (8): _condition_for(), Comprehensive seed of ADA T2D decision rules → clinical_rules table.  Covers EVE, Idempotently insert the rule catalog (manager edits are preserved)., Owning disease module for a rule. Explicit `condition_code` wins; otherwise, Idempotently insert the rule catalog (manager edits are preserved) and tag     e, seed_clinical_rules(), CROSS_DISEASE (rules shared across all disease modules), RULES (ADA decision rule catalog)

### Community 43 - "EngagementRepository"
Cohesion: 0.15
Nodes (3): Repository for the engagement engine: the editable event->channel routing table, True if this event was dispatched to this channel within `cooldown_days`., EngagementRepository

### Community 44 - "bt"
Cohesion: 0.24
Nodes (7): addBox(), bt, Gt(), je(), start(), ti(), vt()

### Community 45 - "s"
Cohesion: 0.21
Nodes (6): fe(), ia(), label(), nn(), s(), sn

### Community 46 - "Red Flags (immediate referral: severe hypo, DKA/HHS, BP≥180/110, Fournier gangrene)"
Cohesion: 0.18
Nodes (11): DKA (diabetic ketoacidosis; euglycemic DKA with SGLT2i), HHS (hyperosmolar hyperglycemic state), Red Flags (immediate referral: severe hypo, DKA/HHS, BP≥180/110, Fournier gangrene), Combined weighted risk score (analytics_service upgrade), clinical_indicators table (targets/thresholds), clinical_rules table (If/Then rule catalog), clinical_rules_seed.py (~50 ADA rules seed), /manager/rules clinical-rules admin center (+3 more)

### Community 47 - "Hypoglycemia classification (Level 1/2/3, Table 6.4)"
Cohesion: 0.18
Nodes (11): Glucagon (prescribe for all insulin users, 6.16), Hypoglycemia classification (Level 1/2/3, Table 6.4), Individualized A1c target (tight <6.5%, relaxed up to 8%), Insulin (basal/bolus, human and analog), Insulin initiation algorithm (A1c>10%, glucose≥300, catabolism), Insulin start/titration doses (basal 10U or 0.1-0.2U/kg, bolus 4U), Rule T2-MED-HYPO-01 (high hypo risk → low-hypo agents, deintensify), Rule of 15 (15g carbohydrate, recheck 15 min) (+3 more)

### Community 48 - "Patient Analytics Dashboard"
Cohesion: 0.22
Nodes (11): rule_engine (ADA trigger DSL evaluator), Patient Analytics Dashboard, ADA Clinical Support Panel (suggestion-only), Clinical Chart Studio (line/area/bar/scatter), Disease Control Status Panel, Insulin Titration Calculator (ADA §6.4), Medication Effect Tool (pre/post indicator), Medication Timeline Lanes (+3 more)

### Community 49 - "._notify"
Cohesion: 0.33
Nodes (4): Cs, os(), removeBox(), stop()

### Community 50 - "vitals_service.THRESHOLDS (warn/high threshold map)"
Cohesion: 0.25
Nodes (9): Blood pressure (systolic/diastolic), Blood pressure target (<130/80; <120 SBP high-risk; <140/90 frail), LDL cholesterol indicator, Lipid target (LDL <70 high CV risk, ≥50% reduction), Standards of Care 2025 Abridged for Primary Care (Clin Diabetes, DOI 10.2337/cd25-aint), Clinical reference (thresholds & targets source), Summary of Revisions: Standards of Care 2026 (Diabetes Care 49 Suppl 1:S6), analytics_service.TARGETS (clinical target map) (+1 more)

### Community 51 - "GLP-1 receptor agonist (GLP-1 RA)"
Cohesion: 0.22
Nodes (9): DPP-4 inhibitor (DPP-4i), Dual GIP/GLP-1 RA (tirzepatide), FIB-4 (liver fibrosis index, AST/ALT/platelets), GLP-1-based therapy preferred over insulin (9.21), GLP-1 receptor agonist (GLP-1 RA), MASLD/MASH (metabolic-associated steatotic liver disease), Obesity / overweight, Rule T2-MED-MASLD-01 (MASLD → GLP-1 RA / dual) (+1 more)

### Community 52 - "kavenegar_provider.py"
Cohesion: 0.28
Nodes (4): Kavenegar REST API Reference, Kavenegar SMS provider adapter (https://api.kavenegar.com).  Auth differs from M, Account remaining credit in Rials, or None on failure.          Calls the read-o, Call a Kavenegar method; return (http_status, parsed_json_envelope).

### Community 53 - "Engine B — Event to Channel Engagement Engine"
Cohesion: 0.29
Nodes (8): Modular Clinical Engine (Engine A), engagement_dispatch Idempotency Table, engagement_events Table (event->channel config), Engine B — Event to Channel Engagement Engine, Message & Follow-up Hub (3-tab /sms redesign), Automated SMS Guardrails (quiet hours, 1/day cap, opt-out), sms/campaigns.html (Campaign Builder & List), Wallet-Credit Campaign + Compliance Rewrite

### Community 54 - "EngagementService.dispatch_patient"
Cohesion: 0.36
Nodes (6): EngagementRepository.already_dispatched(), EngagementRepository.in_cooldown(), EngagementService.collect_due_events(), EngagementService.dispatch_patient(), EngagementService.preview(), REASON_BY_EVENT (event→worklist reason map)

### Community 55 - "Manager — ADA Decision Rules editor (decision_rules.html)"
Cohesion: 0.36
Nodes (8): rule_engine (ADA clinical decision-support engine), Manager — ADA Decision Rules editor (decision_rules.html), Clinical Decision-Rule Editor (text/severity/evidence/active per rule), Manager Dashboard (index.html), Manager — Clinical Protocols / periodic checkup worklist (protocols.html), Manager — Clinical Indicators & Targets editor (rules.html), Clinical-Indicator Editor (warn/danger/target/goal/risk-weight per indicator), Manager — User Management (users.html)

### Community 57 - "Glycemic target (A1c <7.0%, pre-meal 80-130, peak <180)"
Cohesion: 0.33
Nodes (7): CGM (continuous glucose monitoring) / TIR-TBR-TAR, Diabetes diagnosis criteria (A1c≥6.5 / FPG≥126 / 2hPG≥200 / random≥200+symptoms), FPG (fasting plasma glucose), Glycemic target (A1c <7.0%, pre-meal 80-130, peak <180), HbA1c (glycated hemoglobin) indicator, PPG (postprandial glucose / 1-2h peak), Prediabetes (A1c 5.7-6.4 / IFG / IGT)

### Community 58 - "Complication screening schedule (eye/foot/neuropathy/renal/lipid)"
Cohesion: 0.29
Nodes (7): Complication screening schedule (eye/foot/neuropathy/renal/lipid), Dilated eye exam (retinopathy screening), Foot exam + 10g monofilament / neuropathy screening, UACR (urine albumin-to-creatinine ratio), Vaccination (influenza/pneumococcal/hepatitis B/COVID/zoster), followup_engine (Engine 3 — monitoring/follow-up), followup_tasks table (idempotent due-date tasks)

### Community 59 - "CSS variable tokens (app.css: surfaces/lines/text/semantic/spacing/radius)"
Cohesion: 0.43
Nodes (7): window.CLINIC_THEME (chart color theme), Component classes (.card/.btn/.kpi/.badge/.table-wrap/.tiles), CSS variable tokens (app.css: surfaces/lines/text/semantic/spacing/radius), Design System (Dark Data-Dense Dashboard), Design HARD RULES (preserve logic, RTL/Jalali, no raw hex), Jalali/Persian Jinja filters (|fa_num |jalali |jalali_date, .jdate), SVG icon sprite (#i-NAME use refs in base.html)

### Community 60 - "Clinic Dashboard"
Cohesion: 0.29
Nodes (7): Clinic Dashboard, Campaign Performance Table, Operational KPI Cards, Revenue Panel (accounting bridge), 30-Day Revenue Trend Chart, Upcoming Appointments & Recent Patients, Risk Score Hero (risk meter + breakdown)

### Community 61 - "constructor"
Cohesion: 0.33
Nodes (4): constructor(), dt(), pi(), un()

### Community 62 - "validators.py"
Cohesion: 0.33
Nodes (5): تابع validation برای کدملی ایرانی., اعتبارسنجی شماره موبایل ایرانی.          شماره باید 11 رقم و با 09 شروع شود., اعتبارسنجی کدملی ایرانی با الگوریتم استاندارد.          Examples:         >>>, validate_iranian_national_id(), validate_iranian_phone()

### Community 63 - "KavenegarProvider.send"
Cohesion: 0.33
Nodes (5): Timeout→Pending pattern (not failed, no retry), Kavenegar return.status codes (200/403/430/…), Pending SMS Pattern (timeout ≠ failure, no retry), KavenegarProvider.send(), RETURN_CODES (Kavenegar status map)

### Community 64 - "es"
Cohesion: 0.33
Nodes (4): es(), generateLabels(), Qi(), ts()

### Community 65 - "ADA Standards of Care in Diabetes 2026"
Cohesion: 0.50
Nodes (5): ADA Standards of Care in Diabetes 2026, Expert Advisor — suggestion-only decision support engine, Safety principle: system suggests, physician confirms (پیشنهاد — تأیید با پزشک), suggestion_log table (physician accept/dismiss audit), Treatment engine implementation plan (3 engines)

### Community 66 - "Rule T2-MED-ASCVD-01 (ASCVD → GLP-1 RA and/or SGLT2i, independent of A1c)"
Cohesion: 0.40
Nodes (5): ASCVD (atherosclerotic cardiovascular disease), CKD (chronic kidney disease, G1-G5/A1-A3), Rule T2-MED-ASCVD-01 (ASCVD → GLP-1 RA and/or SGLT2i, independent of A1c), flag_catalog table (editable flag-key catalog), patient_flags table (categorical/boolean clinical flags)

### Community 67 - "SMS via Mediana integration"
Cohesion: 0.40
Nodes (5): wallet_repo.py (wallet_transactions), Background scheduler (reminders, campaigns, backups), settings table (SMS keys/config), SMS via Mediana integration, Patient wallet credit (lawful discount framing)

### Community 68 - "AvalAI unified AI API gateway"
Cohesion: 0.50
Nodes (5): Anthropic-compatible Messages interface, AvalAI unified AI API gateway, Persian/Iran-focused service (Toman billing), OpenAI-compatible interface (base URL + Bearer key), Structured Outputs / JSON mode

### Community 69 - "Revenue & Campaign Performance Block"
Cohesion: 0.83
Nodes (4): Read-only Accounting Bridge, Revenue & Campaign Performance Block, Causal Incrementality (Holdout Lift) Measurement, sms/campaign_detail.html (Campaign Detail & Log)

### Community 70 - "persian-date.min.js"
Cohesion: 0.83
Nodes (3): e(), i(), t()

## Knowledge Gaps
- **104 isolated node(s):** `Connection`, `AuthRepository`, `src/common cross-cutting utils`, `flag_catalog + patient_flags tables`, `drug_classes table` (+99 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **36 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `_()` connect `_` to `js`, `jquery.min.js`, `ns`, `zt`, `an`, `update`, `buildTicks`, `updateElements`, `n`, `bn`, `destroy`, `fa`, `Do`, `hi`, `no`, `tn`, `configure`, `.get`, `bt`, `s`, `._notify`, `._handleEvent`, `constructor`, `es`?**
  _High betweenness centrality (0.127) - this node is a cross-community bridge._
- **Why does `WalletRepository` connect `SmsRepository` to `jalali_to_gregorian_str`, `patients.py`, `ClinicalRulesRepository`, `sms.py`, `core.py`?**
  _High betweenness centrality (0.060) - this node is a cross-community bridge._
- **Why does `SmsRepository` connect `SmsRepository` to `engagement_service.py`, `MedianaProvider`, `sms.py`, `control_room_service.py`, `Scheduler`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `update()` (e.g. with `gi()` and `ji()`) actually correct?**
  _`update()` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `SmsRepository` (e.g. with `engagement_service.py` and `Scheduler`) actually correct?**
  _`SmsRepository` has 10 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Connection`, `Read-only bridge to the accounting app's database (clinic_new.db).  CRITICAL SAF`, `Open a read-only connection to the accounting DB, or None if unavailable.` to the rest of the system?**
  _239 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `js` be split into smaller, more focused modules?**
  _Cohesion score 0.053267326732673266 - nodes in this community are weakly interconnected._
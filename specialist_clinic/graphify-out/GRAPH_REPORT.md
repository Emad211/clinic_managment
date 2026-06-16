# Graph Report - .  (2026-06-17)

## Corpus Check
- 87 files · ~64,659 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1363 nodes · 3360 edges · 91 communities (71 shown, 20 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 277 edges (avg confidence: 0.77)
- Token cost: 142,726 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_SQLite repositories & DB core|SQLite repositories & DB core]]
- [[_COMMUNITY_Chart.js core internals|Chart.js core internals]]
- [[_COMMUNITY_SMS campaign & wallet|SMS campaign & wallet]]
- [[_COMMUNITY_jQuery internals|jQuery internals]]
- [[_COMMUNITY_Patient-facing UI views|Patient-facing UI views]]
- [[_COMMUNITY_Accounting bridge (read-only)|Accounting bridge (read-only)]]
- [[_COMMUNITY_Decision-support & engagement architecture|Decision-support & engagement architecture]]
- [[_COMMUNITY_API routes (blueprints)|API routes (blueprints)]]
- [[_COMMUNITY_Revenue & Jalali dates|Revenue & Jalali dates]]
- [[_COMMUNITY_Chart.js controller update|Chart.js controller update]]
- [[_COMMUNITY_Chart.js scale generation|Chart.js scale generation]]
- [[_COMMUNITY_Manager routes & per-disease pages|Manager routes & per-disease pages]]
- [[_COMMUNITY_Chart.js barpixel mapping|Chart.js bar/pixel mapping]]
- [[_COMMUNITY_Chart.js misc helpers|Chart.js misc helpers]]
- [[_COMMUNITY_Chart.js dataset controller|Chart.js dataset controller]]
- [[_COMMUNITY_Chart.js interactionrange|Chart.js interaction/range]]
- [[_COMMUNITY_Chart.js event handling|Chart.js event handling]]
- [[_COMMUNITY_Database schema (tables)|Database schema (tables)]]
- [[_COMMUNITY_App bootstrap & scheduler|App bootstrap & scheduler]]
- [[_COMMUNITY_Chart.js drawingtooltip|Chart.js drawing/tooltip]]
- [[_COMMUNITY_Chart.js label resolution|Chart.js label resolution]]
- [[_COMMUNITY_DB bootstrap & rule seeding|DB bootstrap & rule seeding]]
- [[_COMMUNITY_Appointments|Appointments]]
- [[_COMMUNITY_Managerops UI views|Manager/ops UI views]]
- [[_COMMUNITY_Vitals service & indicators|Vitals service & indicators]]
- [[_COMMUNITY_Follow-up worklist engine|Follow-up worklist engine]]
- [[_COMMUNITY_Chart.js dataset visibility|Chart.js dataset visibility]]
- [[_COMMUNITY_Chart.js option resolver|Chart.js option resolver]]
- [[_COMMUNITY_Chart.js interpolation|Chart.js interpolation]]
- [[_COMMUNITY_Cardiorenal drug selection|Cardiorenal drug selection]]
- [[_COMMUNITY_Auth & activity logging|Auth & activity logging]]
- [[_COMMUNITY_Chart.js grid lines|Chart.js grid lines]]
- [[_COMMUNITY_Chart.js radialgrid scale|Chart.js radial/grid scale]]
- [[_COMMUNITY_Clinical flags repository|Clinical flags repository]]
- [[_COMMUNITY_Rule engine (trigger DSL)|Rule engine (trigger DSL)]]
- [[_COMMUNITY_Chart.js registry|Chart.js registry]]
- [[_COMMUNITY_Chart.js layoutfit|Chart.js layout/fit]]
- [[_COMMUNITY_Persian datepicker|Persian datepicker]]
- [[_COMMUNITY_Patient analytics & risk|Patient analytics & risk]]
- [[_COMMUNITY_Chart.js DOM events|Chart.js DOM events]]
- [[_COMMUNITY_Patient enrollment service|Patient enrollment service]]
- [[_COMMUNITY_Clinical indicators repository|Clinical indicators repository]]
- [[_COMMUNITY_Chart.js scale bounds|Chart.js scale bounds]]
- [[_COMMUNITY_Chart.js animation|Chart.js animation]]
- [[_COMMUNITY_Chart.js render pipeline|Chart.js render pipeline]]
- [[_COMMUNITY_Decision-support architecture|Decision-support architecture]]
- [[_COMMUNITY_Red flags & hypoglycemia|Red flags & hypoglycemia]]
- [[_COMMUNITY_Chart.js animation control|Chart.js animation control]]
- [[_COMMUNITY_BP & lipid targets|BP & lipid targets]]
- [[_COMMUNITY_Indicator evaluation service|Indicator evaluation service]]
- [[_COMMUNITY_Chart.js controller lifecycle|Chart.js controller lifecycle]]
- [[_COMMUNITY_Chart.js dataset parsing|Chart.js dataset parsing]]
- [[_COMMUNITY_Chart.js pixel mapping|Chart.js pixel mapping]]
- [[_COMMUNITY_Chart.js plugin descriptors|Chart.js plugin descriptors]]
- [[_COMMUNITY_Glycemic targets & diagnosis|Glycemic targets & diagnosis]]
- [[_COMMUNITY_Complication screening schedule|Complication screening schedule]]
- [[_COMMUNITY_Insulin therapy & titration|Insulin therapy & titration]]
- [[_COMMUNITY_Design system (dark dashboard)|Design system (dark dashboard)]]
- [[_COMMUNITY_Iranian IDphone validators|Iranian ID/phone validators]]
- [[_COMMUNITY_AvalAI AI API gateway|AvalAI AI API gateway]]
- [[_COMMUNITY_Chart.js teardown|Chart.js teardown]]
- [[_COMMUNITY_Chart.js small helpers|Chart.js small helpers]]
- [[_COMMUNITY_persian-date library|persian-date library]]
- [[_COMMUNITY_Obesity drug rule|Obesity drug rule]]
- [[_COMMUNITY_MASLD  liver drug rule|MASLD / liver drug rule]]
- [[_COMMUNITY_Heart-failure drug rule|Heart-failure drug rule]]
- [[_COMMUNITY_Claude Code settings|Claude Code settings]]
- [[_COMMUNITY_BMI & weight target|BMI & weight target]]
- [[_COMMUNITY_A1c follow-up cadence|A1c follow-up cadence]]
- [[_COMMUNITY_Diabetes classification|Diabetes classification]]
- [[_COMMUNITY_Diabetes self-management education|Diabetes self-management education]]
- [[_COMMUNITY_Evidence levels|Evidence levels]]
- [[_COMMUNITY_HDL cholesterol indicator|HDL cholesterol indicator]]
- [[_COMMUNITY_Medical nutrition therapy|Medical nutrition therapy]]
- [[_COMMUNITY_Physical activity guidance|Physical activity guidance]]
- [[_COMMUNITY_Diabetes screening criteria|Diabetes screening criteria]]
- [[_COMMUNITY_Statin therapy|Statin therapy]]
- [[_COMMUNITY_Triglyceride indicator|Triglyceride indicator]]
- [[_COMMUNITY_Login page|Login page]]
- [[_COMMUNITY_Common utils package|Common utils package]]
- [[_COMMUNITY_patient_links model|patient_links model]]
- [[_COMMUNITY_App overview|App overview]]
- [[_COMMUNITY_Offline vendored libraries|Offline vendored libraries]]

## God Nodes (most connected - your core abstractions)
1. `_()` - 266 edges
2. `get_db()` - 127 edges
3. `update()` - 109 edges
4. `js()` - 70 edges
5. `an()` - 60 edges
6. `ns()` - 55 edges
7. `draw()` - 46 edges
8. `constructor()` - 43 edges
9. `SmsRepository` - 35 edges
10. `iran_now()` - 34 edges

## Surprising Connections (you probably didn't know these)
- `start.py (frozen-mode launcher)` --calls--> `create_app()`  [EXTRACTED]
  CLAUDE.md → src/app.py
- `clinical_rules_seed.py (seed_clinical_rules)` --shares_data_with--> `clinical_rules (ADA If/Then catalog)`  [EXTRACTED]
  CLAUDE.md → specialist_clinic/CLAUDE.md
- `suggestion_log table (accountability trail)` --references--> `clinical_rules (ADA If/Then catalog)`  [INFERRED]
  CLAUDE.md → specialist_clinic/CLAUDE.md
- `HbA1c (glycated hemoglobin) indicator` --references--> `vitals_service.THRESHOLDS (warn/high threshold map)`  [INFERRED]
  ada_t2_rules.md → docs/clinical_reference.md
- `eGFR (estimated glomerular filtration rate, CKD-EPI 2021)` --references--> `vitals_service.THRESHOLDS (warn/high threshold map)`  [INFERRED]
  ada_t2_rules.md → docs/clinical_reference.md

## Import Cycles
- 1-file cycle: `src/common/utils.py -> src/common/utils.py`

## Hyperedges (group relationships)
- **Two-Engine + One-Bridge Architecture** — engagement_engine_plan_two_engine_architecture, engagement_engine_plan_modular_disease_engine, engagement_engine_plan_event_to_channel_engine [EXTRACTED 1.00]
- **Per-Disease Manager Page Consolidates Two Legacy Pages** — manager_diseases_disease_module_hub, manager_disease_detail_per_disease_page, manager_rules_indicators_page, manager_decision_rules_page [EXTRACTED 1.00]
- **Campaign Revenue Attribution & Incrementality Flow** — sms_campaigns_hub, sms_campaign_detail_incrementality, templates_dashboard_revenue_block, claude_md_accounting_bridge [INFERRED 0.85]

## Communities (91 total, 20 thin omitted)

### Community 0 - "SQLite repositories & DB core"
Cohesion: 0.05
Nodes (15): Row, AuthRepository, Low-level DB operations for users., get_db(), Return the per-request connection to the specialist DB (created on first use)., FollowupRepository, Repository for follow-up tasks (worklist)., True if there's an OPEN task for this rule, or a DONE one within `months`. (+7 more)

### Community 1 - "Chart.js core internals"
Cohesion: 0.05
Nodes (39): _(), aa(), beforeDatasetDraw(), beforeDatasetsDraw(), beforeLayout(), Ci(), Di(), easeInOutElastic() (+31 more)

### Community 2 - "SMS campaign & wallet"
Cohesion: 0.06
Nodes (41): wallet_repo.py (wallet_transactions), add_template(), api_check(), api_recipients(), campaign_detail(), campaigns(), Live compliance check + preview for the campaign composer., send_campaign() (+33 more)

### Community 3 - "jQuery internals"
Cohesion: 0.07
Nodes (27): Ie(), Y(), A(), at(), b(), be(), ce(), e() (+19 more)

### Community 4 - "Patient-facing UI views"
Cohesion: 0.06
Nodes (47): Follow-up Worklist, Worklist Reason Filter Tabs, Follow-up Task Table (done/dismiss), Patient Analytics Dashboard, ADA Clinical Support Panel (suggestion-only), Clinical Chart Studio (line/area/bar/scatter), Disease Control Status Panel, Per-Disease Indicator Tiles (+39 more)

### Community 5 - "Accounting bridge (read-only)"
Cohesion: 0.08
Nodes (40): _chunks(), _connect_ro(), daily_revenue_for_accounting_ids(), daily_revenue_for_enrolled(), get_patient_by_id(), get_patient_by_national_id(), get_visit_history(), is_available() (+32 more)

### Community 6 - "Decision-support & engagement architecture"
Cohesion: 0.09
Nodes (42): appointments/list.html (Appointment List), Read-only Accounting Bridge, clinical_indicators (editable thresholds), clinical_rules (ADA If/Then catalog), Modular Clinical Engine (Engine A), suggestion_log table (accountability trail), trigger_json all/any/not + leaf DSL, clinical_rules.condition_code Column (+34 more)

### Community 7 - "API routes (blueprints)"
Cohesion: 0.09
Nodes (28): new_appointment(), set_status(), login(), login_required(), logout(), manager_required(), add_manual(), resolve() (+20 more)

### Community 8 - "Revenue & Jalali dates"
Cohesion: 0.07
Nodes (26): list_appointments(), index(), Physician-first clinic-at-a-glance: who needs attention today, plus business KPI, Iran local time (UTC+3:30) convention, Jalali dates everywhere convention, Gregorian, Persian, format_jalali_date() (+18 more)

### Community 9 - "Chart.js controller update"
Cohesion: 0.12
Nodes (10): afterUpdate(), As(), beforeUpdate(), configure(), d(), init(), js(), po() (+2 more)

### Community 10 - "Chart.js scale generation"
Cohesion: 0.12
Nodes (18): buildLookupTable(), buildTicks(), En, _generate(), getDecimalForValue(), _getTimestampsForTable(), H(), In() (+10 more)

### Community 11 - "Manager routes & per-disease pages"
Cohesion: 0.08
Nodes (27): decision_rules(), decision_rules_update(), disease_detail(), diseases(), index(), _indicator_applies(), protocol_followup(), protocols() (+19 more)

### Community 12 - "Chart.js bar/pixel mapping"
Cohesion: 0.11
Nodes (16): Ae(), _calculateBarIndexPixels(), _calculateBarValuePixels(), getBasePixel(), getPixelForValue(), _getRuler(), _getStackCount(), _getStackIndex() (+8 more)

### Community 13 - "Chart.js misc helpers"
Cohesion: 0.11
Nodes (14): Bi(), color(), Ee(), Ft(), It(), jt(), kt(), mt() (+6 more)

### Community 15 - "Chart.js interaction/range"
Cohesion: 0.13
Nodes (21): ai(), ao(), average(), beforeDraw(), dataset(), generateLabels(), getCenterPoint(), hi() (+13 more)

### Community 16 - "Chart.js event handling"
Cohesion: 0.13
Nodes (6): afterEvent(), an(), cn(), dn(), reset(), u()

### Community 17 - "Database schema (tables)"
Cohesion: 0.13
Nodes (25): activity_logs, allergies, appointments, campaign_audience, care_protocols, clinical_indicators, clinical_rules, conditions (+17 more)

### Community 18 - "App bootstrap & scheduler"
Cohesion: 0.13
Nodes (12): main(), trend(), init_scheduler(), Background scheduler: appointment reminders, scheduled campaigns, follow-up gene, Scheduler, Send a one-off SMS (e.g. an appointment reminder) and log it.      Defaults to ', send_single(), start.py (frozen-mode launcher) (+4 more)

### Community 19 - "Chart.js drawing/tooltip"
Cohesion: 0.21
Nodes (14): draw(), ea(), gs(), ki(), Le(), oa(), Oi(), Si() (+6 more)

### Community 20 - "Chart.js label resolution"
Cohesion: 0.11
Nodes (15): bo, et(), Fo(), getLabelAndValue(), getLabelForValue(), is(), label(), n() (+7 more)

### Community 21 - "DB bootstrap & rule seeding"
Cohesion: 0.12
Nodes (16): _condition_for(), Comprehensive seed of ADA T2D decision rules → clinical_rules table.  Covers EVE, Idempotently insert the rule catalog (manager edits are preserved)., Owning disease module for a rule. Explicit `condition_code` wins; otherwise, Idempotently insert the rule catalog (manager edits are preserved) and tag     e, seed_clinical_rules(), _ensure_column(), _ensure_default_admin() (+8 more)

### Community 22 - "Appointments"
Cohesion: 0.10
Nodes (7): AppointmentRepository, Appointment logic, including recurring (periodic) appointments., Mark an appointment done; if recurring, auto-create the next one., AppointmentRepository, Repository for appointments., date_from/date_to are gregorian 'YYYY-MM-DD'. Returns appts with patient name., Scheduled appts within the next N hours that haven't had a reminder sent.

### Community 23 - "Manager/ops UI views"
Cohesion: 0.15
Nodes (21): Appointments — list + filter + status actions (list.html), Appointments — schedule new appointment (new.html), base.html (RTL/Jalali layout template), clinical_indicators (indicator thresholds/targets table), clinical_rules (ADA decision-rule catalog table), followup_engine (turns due rules/protocols into followup_tasks), Manager — ADA Decision Rules editor (decision_rules.html), Clinical Decision-Rule Editor (text/severity/evidence/active per rule) (+13 more)

### Community 24 - "Vitals service & indicators"
Cohesion: 0.13
Nodes (13): schema.sql (source of truth), detail(), ADA clinical reference docs (clinical_reference.md, ada_t2_rules.md), clinical_indicators table (live thresholds), Threshold-sync rule (indicators + fallbacks + docs), FollowupRepository, evaluate_reading(), _fallback_eval() (+5 more)

### Community 25 - "Follow-up worklist engine"
Cohesion: 0.16
Nodes (14): generate(), followup_tasks table / worklist, Today's Gregorian date as 'YYYY-MM-DD' (Iran time)., today_str(), generate_all(), generate_for_patient(), _last_done(), _months_since() (+6 more)

### Community 26 - "Chart.js dataset visibility"
Cohesion: 0.16
Nodes (5): afterDatasetsUpdate(), K(), labelColor(), labelPointStyle(), onClick()

### Community 27 - "Chart.js option resolver"
Cohesion: 0.14
Nodes (6): at(), bn, e(), on(), pn(), Ye()

### Community 28 - "Chart.js interpolation"
Cohesion: 0.20
Nodes (10): da(), fa(), ga(), ha, ii(), la(), pa(), ra() (+2 more)

### Community 29 - "Cardiorenal drug selection"
Cohesion: 0.17
Nodes (16): ACEi/ARB (RAS inhibition), ASCVD (atherosclerotic cardiovascular disease), CKD (chronic kidney disease, G1-G5/A1-A3), DPP-4 inhibitor (DPP-4i), eGFR (estimated glomerular filtration rate, CKD-EPI 2021), Finerenone (nsMRA), GLP-1 receptor agonist (GLP-1 RA), Metformin (oral, historic first-line) (+8 more)

### Community 30 - "Auth & activity logging"
Cohesion: 0.16
Nodes (8): AuthRepository, activity_logs table, Auth & roles (manager/staff, bcrypt, lockout), iran_now(), Return current Tehran time as a naive datetime.      The DB stores timestamps as, bcrypt dependency (>=4.0), Lightweight activity logger for the specialist app., Auth logic with bcrypt + lockout (5 failed attempts -> 15 min lock).

### Community 31 - "Chart.js grid lines"
Cohesion: 0.20
Nodes (6): b(), ce(), de, he(), ia(), qs()

### Community 32 - "Chart.js radial/grid scale"
Cohesion: 0.24
Nodes (6): ca(), co(), Do(), eo(), Gn(), so()

### Community 33 - "Clinical flags repository"
Cohesion: 0.17
Nodes (6): analytics(), Merged into the unified patient cockpit; kept as a stable deep-link to the trend, ClinicalFlagsRepository, _parse_options(), Repository for clinical decision inputs: flag_catalog, patient_flags, drug_class, HFrEF|EF کاهش‌یافته,unknown|نامشخص' -> [{value,label}, ...]

### Community 34 - "Rule engine (trigger DSL)"
Cohesion: 0.20
Nodes (8): drug_classes table, flag_catalog + patient_flags tables, _age_from_birthdate(), Rule engine: builds a patient fact-bundle and evaluates the editable clinical_ru, Return the list of fired rules for a patient (suggestion-only)., Fired rules grouped into UI sections, in display order., Robust age: handles gregorian or Jalali year in birthdate string., _truthy()

### Community 35 - "Chart.js registry"
Cohesion: 0.24
Nodes (3): addElements(), tn, w()

### Community 36 - "Chart.js layout/fit"
Cohesion: 0.22
Nodes (3): getPixelForTick(), xa, Xs()

### Community 37 - "Persian datepicker"
Cohesion: 0.19
Nodes (8): a(), d(), e(), i(), n(), r(), s(), u()

### Community 38 - "Patient analytics & risk"
Cohesion: 0.20
Nodes (8): medication_effect(), On-demand pre/post effect of a medication on a chosen indicator.      Doctor-dri, ADA clinical decision-support engine, Suggestion-only, physician-decides, logged principle, Management dashboard (control rate, campaign efficacy), _mean(), _parse_date(), Per-patient clinical analytics — rules-driven, per-disease, risk + med effect.

### Community 39 - "Chart.js DOM events"
Cohesion: 0.24
Nodes (6): ct(), ge(), ms(), rs, ws, ys()

### Community 40 - "Patient enrollment service"
Cohesion: 0.15
Nodes (7): enroll_accounting(), search_accounting(), PatientRepository, Patient enrollment + chronic profile logic., Search the accounting DB (read-only) and flag which are already enrolled., Pull a patient from the accounting DB and create a local chronic-care link., Create a local patient not (yet) in the accounting DB.

### Community 41 - "Clinical indicators repository"
Cohesion: 0.24
Nodes (6): ClinicalRulesRepository, Repository for the editable clinical decision rules (clinical_indicators).  This, All indicators ordered for display. Cached per-request on flask.g., {key: indicator} map., Indicators that apply to a patient with the given condition codes.          An i, Update editable fields of one indicator.

### Community 42 - "Chart.js scale bounds"
Cohesion: 0.29
Nodes (9): a(), determineDataLimits(), ei(), f(), ko, ls, r(), ri() (+1 more)

### Community 43 - "Chart.js animation"
Cohesion: 0.24
Nodes (7): addBox(), bt, constructor(), dt(), Gt(), start(), vt()

### Community 44 - "Chart.js render pipeline"
Cohesion: 0.24
Nodes (4): afterDraw(), initialize(), ke(), wn()

### Community 45 - "Decision-support architecture"
Cohesion: 0.20
Nodes (12): ADA Standards of Care in Diabetes 2026, Expert Advisor — suggestion-only decision support engine, Safety principle: system suggests, physician confirms (پیشنهاد — تأیید با پزشک), clinical_indicators table (targets/thresholds), clinical_rules table (If/Then rule catalog), clinical_rules_seed.py (~50 ADA rules seed), /manager/rules clinical-rules admin center, RuleEvaluator (trigger tree evaluator) (+4 more)

### Community 46 - "Red flags & hypoglycemia"
Cohesion: 0.20
Nodes (10): DKA (diabetic ketoacidosis; euglycemic DKA with SGLT2i), Glucagon (prescribe for all insulin users, 6.16), HHS (hyperosmolar hyperglycemic state), Hypoglycemia classification (Level 1/2/3, Table 6.4), Individualized A1c target (tight <6.5%, relaxed up to 8%), Red Flags (immediate referral: severe hypo, DKA/HHS, BP≥180/110, Fournier gangrene), Rule of 15 (15g carbohydrate, recheck 15 min), Rule T2-MED-OLDER-01 (frail elderly → low-hypo agents, relaxed targets) (+2 more)

### Community 47 - "Chart.js animation control"
Cohesion: 0.31
Nodes (4): Cs, os(), removeBox(), stop()

### Community 48 - "BP & lipid targets"
Cohesion: 0.25
Nodes (9): Blood pressure (systolic/diastolic), Blood pressure target (<130/80; <120 SBP high-risk; <140/90 frail), LDL cholesterol indicator, Lipid target (LDL <70 high CV risk, ≥50% reduction), Standards of Care 2025 Abridged for Primary Care (Clin Diabetes, DOI 10.2337/cd25-aint), Clinical reference (thresholds & targets source), Summary of Revisions: Standards of Care 2026 (Diabetes Care 49 Suppl 1:S6), analytics_service.TARGETS (clinical target map) (+1 more)

### Community 49 - "Indicator evaluation service"
Cohesion: 0.28
Nodes (4): evaluate(), _num(), Clinical rule evaluation: direction-aware red-flag logic driven by the editable, Return 'danger' | 'warn' | 'ok' for a value against one indicator rule.      Hon

### Community 51 - "Chart.js dataset parsing"
Cohesion: 0.47
Nodes (9): Fn(), go(), l(), parse(), parseArrayData(), parseObjectData(), parsePrimitiveData(), resolveDataElementOptions() (+1 more)

### Community 52 - "Chart.js pixel mapping"
Cohesion: 0.25
Nodes (7): getValueForPixel(), ho(), inXRange(), inYRange(), oo(), tt(), xo

### Community 54 - "Glycemic targets & diagnosis"
Cohesion: 0.33
Nodes (7): CGM (continuous glucose monitoring) / TIR-TBR-TAR, Diabetes diagnosis criteria (A1c≥6.5 / FPG≥126 / 2hPG≥200 / random≥200+symptoms), FPG (fasting plasma glucose), Glycemic target (A1c <7.0%, pre-meal 80-130, peak <180), HbA1c (glycated hemoglobin) indicator, PPG (postprandial glucose / 1-2h peak), Prediabetes (A1c 5.7-6.4 / IFG / IGT)

### Community 55 - "Complication screening schedule"
Cohesion: 0.29
Nodes (7): Complication screening schedule (eye/foot/neuropathy/renal/lipid), Dilated eye exam (retinopathy screening), Foot exam + 10g monofilament / neuropathy screening, UACR (urine albumin-to-creatinine ratio), Vaccination (influenza/pneumococcal/hepatitis B/COVID/zoster), followup_engine (Engine 3 — monitoring/follow-up), followup_tasks table (idempotent due-date tasks)

### Community 56 - "Insulin therapy & titration"
Cohesion: 0.29
Nodes (7): GLP-1-based therapy preferred over insulin (9.21), Insulin (basal/bolus, human and analog), Insulin initiation algorithm (A1c>10%, glucose≥300, catabolism), Insulin start/titration doses (basal 10U or 0.1-0.2U/kg, bolus 4U), Rule T2-MED-HYPO-01 (high hypo risk → low-hypo agents, deintensify), Sulfonylurea (SU, 2nd generation), Insulin dose calculator (explicit ADA numbers)

### Community 57 - "Design system (dark dashboard)"
Cohesion: 0.43
Nodes (7): window.CLINIC_THEME (chart color theme), Component classes (.card/.btn/.kpi/.badge/.table-wrap/.tiles), CSS variable tokens (app.css: surfaces/lines/text/semantic/spacing/radius), Design System (Dark Data-Dense Dashboard), Design HARD RULES (preserve logic, RTL/Jalali, no raw hex), Jalali/Persian Jinja filters (|fa_num |jalali |jalali_date, .jdate), SVG icon sprite (#i-NAME use refs in base.html)

### Community 58 - "Iranian ID/phone validators"
Cohesion: 0.33
Nodes (5): تابع validation برای کدملی ایرانی., اعتبارسنجی شماره موبایل ایرانی.          شماره باید 11 رقم و با 09 شروع شود., اعتبارسنجی کدملی ایرانی با الگوریتم استاندارد.          Examples:         >>>, validate_iranian_national_id(), validate_iranian_phone()

### Community 59 - "AvalAI AI API gateway"
Cohesion: 0.50
Nodes (5): Anthropic-compatible Messages interface, AvalAI unified AI API gateway, Persian/Iran-focused service (Toman billing), OpenAI-compatible interface (base URL + Bearer key), Structured Outputs / JSON mode

### Community 60 - "Chart.js teardown"
Cohesion: 0.40
Nodes (3): destroy(), Jo(), rt()

### Community 61 - "Chart.js small helpers"
Cohesion: 0.67
Nodes (4): be(), pe(), we(), me()

### Community 62 - "persian-date library"
Cohesion: 0.83
Nodes (3): e(), i(), t()

### Community 63 - "Obesity drug rule"
Cohesion: 0.67
Nodes (3): Dual GIP/GLP-1 RA (tirzepatide), Obesity / overweight, Rule T2-MED-OBESITY-01 (obesity → weight-lowering GLP-1/dual)

### Community 64 - "MASLD / liver drug rule"
Cohesion: 0.67
Nodes (3): FIB-4 (liver fibrosis index, AST/ALT/platelets), MASLD/MASH (metabolic-associated steatotic liver disease), Rule T2-MED-MASLD-01 (MASLD → GLP-1 RA / dual)

### Community 65 - "Heart-failure drug rule"
Cohesion: 0.67
Nodes (3): Heart failure (HF, HFrEF/HFpEF), Rule T2-MED-HF-01 (HF → SGLT2i; TZD contraindicated), Thiazolidinedione / pioglitazone (TZD)

## Ambiguous Edges - Review These
- `mediana_provider.py` → `jdatetime dependency (>=4.0)`  [AMBIGUOUS]
  requirements.txt · relation: conceptually_related_to

## Knowledge Gaps
- **98 isolated node(s):** `allow`, `Row`, `users`, `settings`, `activity_logs` (+93 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **20 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `mediana_provider.py` and `jdatetime dependency (>=4.0)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `get_db()` connect `SQLite repositories & DB core` to `Clinical flags repository`, `Rule engine (trigger DSL)`, `SMS campaign & wallet`, `Patient analytics & risk`, `API routes (blueprints)`, `Revenue & Jalali dates`, `Clinical indicators repository`, `Manager routes & per-disease pages`, `App bootstrap & scheduler`, `DB bootstrap & rule seeding`, `Appointments`, `Vitals service & indicators`, `Follow-up worklist engine`, `Auth & activity logging`?**
  _High betweenness centrality (0.112) - this node is a cross-community bridge._
- **Why does `_()` connect `Chart.js core internals` to `jQuery internals`, `Chart.js controller update`, `Chart.js scale generation`, `Chart.js bar/pixel mapping`, `Chart.js misc helpers`, `Chart.js dataset controller`, `Chart.js interaction/range`, `Chart.js event handling`, `Chart.js drawing/tooltip`, `Chart.js label resolution`, `Chart.js dataset visibility`, `Chart.js option resolver`, `Chart.js interpolation`, `Chart.js grid lines`, `Chart.js radial/grid scale`, `Chart.js registry`, `Chart.js layout/fit`, `Chart.js DOM events`, `Chart.js scale bounds`, `Chart.js animation`, `Chart.js render pipeline`, `Chart.js animation control`, `Chart.js controller lifecycle`, `Chart.js dataset parsing`, `Chart.js pixel mapping`, `Chart.js plugin descriptors`, `Chart.js teardown`, `Chart.js small helpers`?**
  _High betweenness centrality (0.100) - this node is a cross-community bridge._
- **Why does `clinical_rules (ADA If/Then catalog)` connect `Decision-support & engagement architecture` to `Follow-up worklist engine`, `Rule engine (trigger DSL)`, `Accounting bridge (read-only)`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `update()` (e.g. with `gi()` and `ji()`) actually correct?**
  _`update()` has 8 INFERRED edges - model-reasoned connections that need verification._
- **What connects `allow`, `Read-only bridge to the accounting app's database (clinic_new.db).  CRITICAL SAF`, `Open a read-only connection to the accounting DB, or None if unavailable.` to the rest of the system?**
  _224 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `SQLite repositories & DB core` be split into smaller, more focused modules?**
  _Cohesion score 0.04828828828828829 - nodes in this community are weakly interconnected._
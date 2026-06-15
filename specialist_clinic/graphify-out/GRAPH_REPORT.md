# Graph Report - .  (2026-06-16)

## Corpus Check
- 84 files · ~55,583 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1478 nodes · 3366 edges · 86 communities (64 shown, 22 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 261 edges (avg confidence: 0.76)
- Token cost: 353,719 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Chart.js option resolver|Chart.js option resolver]]
- [[_COMMUNITY_API routes (blueprints)|API routes (blueprints)]]
- [[_COMMUNITY_Chart.js title rendering|Chart.js title rendering]]
- [[_COMMUNITY_SQLite repositories|SQLite repositories]]
- [[_COMMUNITY_ADA rule engine|ADA rule engine]]
- [[_COMMUNITY_DB core & accounting bridge|DB core & accounting bridge]]
- [[_COMMUNITY_jQuery internals|jQuery internals]]
- [[_COMMUNITY_Patient-facing UI views|Patient-facing UI views]]
- [[_COMMUNITY_Chart.js helpers|Chart.js helpers]]
- [[_COMMUNITY_Chart.js scale generation|Chart.js scale generation]]
- [[_COMMUNITY_Chart.js core & easing|Chart.js core & easing]]
- [[_COMMUNITY_Chart.js registry|Chart.js registry]]
- [[_COMMUNITY_Chart.js radialgrid scale|Chart.js radial/grid scale]]
- [[_COMMUNITY_Jalali date utilities|Jalali date utilities]]
- [[_COMMUNITY_Chart.js bar controller|Chart.js bar controller]]
- [[_COMMUNITY_Auth & activity logging|Auth & activity logging]]
- [[_COMMUNITY_Persian datepicker  arc|Persian datepicker / arc]]
- [[_COMMUNITY_App bootstrap & scheduler|App bootstrap & scheduler]]
- [[_COMMUNITY_Patient analytics & wallet|Patient analytics & wallet]]
- [[_COMMUNITY_Chart.js element interaction|Chart.js element interaction]]
- [[_COMMUNITY_Follow-up worklist engine|Follow-up worklist engine]]
- [[_COMMUNITY_Chart.js scale bounds|Chart.js scale bounds]]
- [[_COMMUNITY_Chart.js dataset parsing|Chart.js dataset parsing]]
- [[_COMMUNITY_Chart.js layoutfit|Chart.js layout/fit]]
- [[_COMMUNITY_SMS campaign service|SMS campaign service]]
- [[_COMMUNITY_Database schema (tables)|Database schema (tables)]]
- [[_COMMUNITY_Appointments|Appointments]]
- [[_COMMUNITY_Chart.js stacking|Chart.js stacking]]
- [[_COMMUNITY_Managerops UI views|Manager/ops UI views]]
- [[_COMMUNITY_Chart.js animation|Chart.js animation]]
- [[_COMMUNITY_SMS provider (Mediana)|SMS provider (Mediana)]]
- [[_COMMUNITY_Chart.js dataset visibility|Chart.js dataset visibility]]
- [[_COMMUNITY_Chart.js tick hooks|Chart.js tick hooks]]
- [[_COMMUNITY_Chart.js label sizing|Chart.js label sizing]]
- [[_COMMUNITY_Glucose-lowering drug selection|Glucose-lowering drug selection]]
- [[_COMMUNITY_Revenue dashboard|Revenue dashboard]]
- [[_COMMUNITY_Chart.js helpers (misc)|Chart.js helpers (misc)]]
- [[_COMMUNITY_Clinical flags repository|Clinical flags repository]]
- [[_COMMUNITY_Clinical indicators repository|Clinical indicators repository]]
- [[_COMMUNITY_Chart.js dataset controllers|Chart.js dataset controllers]]
- [[_COMMUNITY_Chart.js legend|Chart.js legend]]
- [[_COMMUNITY_Chart.js chart lifecycle|Chart.js chart lifecycle]]
- [[_COMMUNITY_Decision-support architecture|Decision-support architecture]]
- [[_COMMUNITY_Chart.js grid drawing|Chart.js grid drawing]]
- [[_COMMUNITY_Chart.js DOM events|Chart.js DOM events]]
- [[_COMMUNITY_Chart.js pixel mapping|Chart.js pixel mapping]]
- [[_COMMUNITY_Chart.js element drawing|Chart.js element drawing]]
- [[_COMMUNITY_Red flags & hypoglycemia|Red flags & hypoglycemia]]
- [[_COMMUNITY_Chart.js event binding|Chart.js event binding]]
- [[_COMMUNITY_Chart.js render pipeline|Chart.js render pipeline]]
- [[_COMMUNITY_BP & lipid targets|BP & lipid targets]]
- [[_COMMUNITY_Glycemic targets & diagnosis|Glycemic targets & diagnosis]]
- [[_COMMUNITY_Complication screening schedule|Complication screening schedule]]
- [[_COMMUNITY_Insulin therapy & titration|Insulin therapy & titration]]
- [[_COMMUNITY_Engagement SMS, wallet, reminders|Engagement: SMS, wallet, reminders]]
- [[_COMMUNITY_Design system (dark dashboard)|Design system (dark dashboard)]]
- [[_COMMUNITY_Iranian IDphone validators|Iranian ID/phone validators]]
- [[_COMMUNITY_Chart.js hover handling|Chart.js hover handling]]
- [[_COMMUNITY_AvalAI AI API gateway|AvalAI AI API gateway]]
- [[_COMMUNITY_persian-date library|persian-date library]]
- [[_COMMUNITY_Obesity drug rule|Obesity drug rule]]
- [[_COMMUNITY_MASLD  liver drug rule|MASLD / liver drug rule]]
- [[_COMMUNITY_Heart-failure drug rule|Heart-failure drug rule]]
- [[_COMMUNITY_Claude Code settings|Claude Code settings]]
- [[_COMMUNITY_BMI & weight target|BMI & weight target]]
- [[_COMMUNITY_A1c follow-up cadence|A1c follow-up cadence]]
- [[_COMMUNITY_Diabetes classification|Diabetes classification]]
- [[_COMMUNITY_Diabetes self-management education|Diabetes self-management education]]
- [[_COMMUNITY_ADA evidence levels|ADA evidence levels]]
- [[_COMMUNITY_HDL cholesterol indicator|HDL cholesterol indicator]]
- [[_COMMUNITY_Medical nutrition therapy|Medical nutrition therapy]]
- [[_COMMUNITY_Physical activity guidance|Physical activity guidance]]
- [[_COMMUNITY_Diabetes screening criteria|Diabetes screening criteria]]
- [[_COMMUNITY_Statin therapy|Statin therapy]]
- [[_COMMUNITY_Triglyceride indicator|Triglyceride indicator]]
- [[_COMMUNITY_Login page|Login page]]
- [[_COMMUNITY_Common utils package|Common utils package]]
- [[_COMMUNITY_Offline vendored libraries|Offline vendored libraries]]

## God Nodes (most connected - your core abstractions)
1. `_()` - 268 edges
2. `get_db()` - 119 edges
3. `js()` - 70 edges
4. `an()` - 61 edges
5. `ns()` - 55 edges
6. `iran_now()` - 34 edges
7. `n()` - 34 edges
8. `SmsRepository` - 33 edges
9. `log_activity()` - 33 edges
10. `no` - 32 edges

## Surprising Connections (you probably didn't know these)
- `RuleEngine` --shares_data_with--> `drug_classes table`  [INFERRED]
  src/services/rule_engine.py → CLAUDE.md
- `RuleEngine` --shares_data_with--> `flag_catalog + patient_flags tables`  [INFERRED]
  src/services/rule_engine.py → CLAUDE.md
- `start.py (frozen-mode launcher)` --calls--> `create_app()`  [EXTRACTED]
  CLAUDE.md → src/app.py
- `RuleEngine` --references--> `trigger_json all/any/not + leaf DSL`  [EXTRACTED]
  src/services/rule_engine.py → CLAUDE.md
- `ADA clinical decision-support engine` --references--> `RuleEngine`  [EXTRACTED]
  CLAUDE.md → src/services/rule_engine.py

## Import Cycles
- 1-file cycle: `src/common/utils.py -> src/common/utils.py`

## Hyperedges (group relationships)
- **api -> services -> adapters layered architecture** — claude_api_layer, claude_services_layer, claude_adapters_sqlite_layer, claude_layered_architecture [EXTRACTED 1.00]
- **ADA clinical decision-support flow** — services_rule_engine_ruleengine, claude_clinical_rules_table, claude_clinical_indicators_table, claude_trigger_json_dsl, services_followup_engine, claude_suggestion_log_table [EXTRACTED 0.95]
- **Mediana SMS subsystem (provider + compliance + wallet + settings)** — claude_sms_mediana, sms_mediana_provider, sms_provider, sms_compliance, claude_settings_table, adapters_sqlite_wallet_repo [EXTRACTED 0.95]
- **Glycemic target set (A1c, FPG/pre-meal, PPG peak, CGM TIR)** — ada_t2_rules_hba1c, ada_t2_rules_fpg, ada_t2_rules_ppg, ada_t2_rules_cgm, ada_t2_rules_glycemic_target [EXTRACTED 1.00]
- **Cardiorenal-protective drug classes (ASCVD/HF/CKD: SGLT2i, GLP-1 RA, dual GIP/GLP-1, finerenone)** — ada_t2_rules_sglt2i, ada_t2_rules_glp1_ra, ada_t2_rules_dual_gip_glp1, ada_t2_rules_finerenone, ada_t2_rules_rule_ckd_01 [INFERRED 0.85]
- **Three clinical engines (risk, treatment-advisor, follow-up) over the rule/trigger core** — docs_treatment_engine_plan_risk_engine, docs_treatment_engine_plan_treatment_advisor, docs_treatment_engine_plan_followup_engine, docs_treatment_engine_plan_rule_evaluator, docs_treatment_engine_plan_clinical_rules [EXTRACTED 1.00]
- **Patient management workflow (base-extending templates)** — patients_list, patients_enroll, patients_detail, patients_analytics, followups_worklist [INFERRED 0.80]
- **ADA clinical decision support UI surface** — patients_detail_clinical_flags, patients_analytics_ada_support, patients_analytics_redflag_alert, patients_analytics_suggestion_action [INFERRED 0.75]
- **Templates rendering read-only accounting bridge data** — templates_dashboard_revenue, patients_detail_visit_history, patients_enroll_accounting_search [INFERRED 0.80]
- **Manager editor screens that tune the ADA clinical engine** — manager_decision_rules, manager_rules, manager_protocols, clinical_rules, clinical_indicators, rule_engine [INFERRED 0.80]
- **SMS campaign flow: build → compliance/settings → send → wallet credit → log** — sms_campaigns, sms_campaign_detail, sms_compliance, mediana_sms_settings, wallet_repo, manager_settings [INFERRED 0.80]

## Communities (86 total, 22 thin omitted)

### Community 0 - "Chart.js option resolver"
Cohesion: 0.07
Nodes (10): bn, fs(), labelColor(), labelPointStyle(), ns(), on(), pn(), rt() (+2 more)

### Community 1 - "API routes (blueprints)"
Cohesion: 0.06
Nodes (37): login(), login_required(), logout(), manager_required(), add_manual(), generate(), resolve(), decision_rules() (+29 more)

### Community 2 - "Chart.js title rendering"
Cohesion: 0.09
Nodes (22): afterDraw(), ai(), da(), ea(), fa(), ga(), gs(), ha (+14 more)

### Community 3 - "SQLite repositories"
Cohesion: 0.07
Nodes (10): settings(), Row, AuthRepository, Low-level DB operations for users., get_db(), Return the per-request connection to the specialist DB (created on first use)., PatientRepository, Repository for patient_links and their chronic-care records. (+2 more)

### Community 4 - "ADA rule engine"
Cohesion: 0.05
Nodes (36): clinical_rules_seed.py (seed_clinical_rules), core.py get_db() / bootstrap, schema.sql (source of truth), ADA clinical reference docs (clinical_reference.md, ada_t2_rules.md), src/adapters/sqlite repositories layer, src/api Flask Blueprints layer, ADA clinical decision-support engine, clinical_indicators table (live thresholds) (+28 more)

### Community 5 - "DB core & accounting bridge"
Cohesion: 0.06
Nodes (40): _chunks(), _connect_ro(), daily_revenue_for_accounting_ids(), get_patient_by_id(), get_patient_by_national_id(), get_visit_history(), is_available(), Read-only bridge to the accounting app's database (clinic_new.db).  CRITICAL SAF (+32 more)

### Community 6 - "jQuery internals"
Cohesion: 0.07
Nodes (27): Ie(), Y(), A(), at(), b(), be(), ce(), e() (+19 more)

### Community 7 - "Patient-facing UI views"
Cohesion: 0.06
Nodes (47): Follow-up Worklist, Worklist Reason Filter Tabs, Follow-up Task Table (done/dismiss), Patient Analytics Dashboard, ADA Clinical Support Panel (suggestion-only), Clinical Chart Studio (line/area/bar/scatter), Disease Control Status Panel, Per-Disease Indicator Tiles (+39 more)

### Community 8 - "Chart.js helpers"
Cohesion: 0.07
Nodes (18): Bi(), bt, color(), Ee(), Ft(), Gt(), It(), jt() (+10 more)

### Community 9 - "Chart.js scale generation"
Cohesion: 0.08
Nodes (15): buildLookupTable(), En, Fo(), _generate(), getDecimalForValue(), _getTimestampsForTable(), init(), initOffsets() (+7 more)

### Community 10 - "Chart.js core & easing"
Cohesion: 0.06
Nodes (21): _(), addBox(), afterEvent(), at(), beforeDatasetDraw(), beforeDatasetsDraw(), beforeUpdate(), configure() (+13 more)

### Community 11 - "Chart.js registry"
Cohesion: 0.08
Nodes (8): addElements(), ce(), de, dt(), he(), ia(), tn, w()

### Community 12 - "Chart.js radial/grid scale"
Cohesion: 0.08
Nodes (11): bo, co(), Do(), eo(), et(), label(), ne(), numeric() (+3 more)

### Community 13 - "Jalali date utilities"
Cohesion: 0.08
Nodes (18): protocol_followup(), protocols(), Create follow-up tasks for all patients due for a given protocol., Iran local time (UTC+3:30) convention, Jalali dates everywhere convention, Gregorian, Persian, add_months() (+10 more)

### Community 14 - "Chart.js bar controller"
Cohesion: 0.10
Nodes (21): ca(), _calculateBarIndexPixels(), _calculateBarValuePixels(), getBasePixel(), getLabelAndValue(), getLabelForValue(), getPixelForTick(), getPixelForValue() (+13 more)

### Community 15 - "Auth & activity logging"
Cohesion: 0.08
Nodes (14): Record the physician's decision on an engine suggestion (accept/dismiss)., suggestion_action(), AuthRepository, activity_logs table, Auth & roles (manager/staff, bcrypt, lockout), iran_now(), Return current Tehran time as a naive datetime.      The DB stores timestamps as, bcrypt dependency (>=4.0) (+6 more)

### Community 16 - "Persian datepicker / arc"
Cohesion: 0.11
Nodes (10): jn, a(), c(), d(), e(), i(), n(), r() (+2 more)

### Community 17 - "App bootstrap & scheduler"
Cohesion: 0.10
Nodes (16): index(), Management analytics dashboard., FollowupRepository, main(), trend(), FollowupService, init_scheduler(), Background scheduler: appointment reminders, scheduled campaigns, follow-up gene (+8 more)

### Community 18 - "Patient analytics & wallet"
Cohesion: 0.10
Nodes (16): medication_effect(), On-demand pre/post effect of a medication on a chosen indicator.      Doctor-dri, wallet_adjust(), format_jalali_date(), Format datetime (or 'YYYY-MM-DD' string) as Jalali date only., Management dashboard (control rate, campaign efficacy), AnalyticsService, _mean() (+8 more)

### Community 19 - "Chart.js element interaction"
Cohesion: 0.11
Nodes (26): ao(), average(), be(), dataset(), getCenterPoint(), gi(), ho(), Hs (+18 more)

### Community 20 - "Follow-up worklist engine"
Cohesion: 0.09
Nodes (17): generate_followups(), Generate due ADA monitoring/screening/vaccine follow-ups for this patient., followup_tasks table / worklist, Today's Gregorian date as 'YYYY-MM-DD' (Iran time)., today_str(), generate_all(), generate_for_patient(), _last_done() (+9 more)

### Community 21 - "Chart.js scale bounds"
Cohesion: 0.12
Nodes (13): a(), aa(), b(), determineDataLimits(), g(), m(), o(), p() (+5 more)

### Community 22 - "Chart.js dataset parsing"
Cohesion: 0.12
Nodes (13): buildTicks(), Fn(), Gn(), go(), l(), n(), parse(), parseArrayData() (+5 more)

### Community 24 - "SMS campaign service"
Cohesion: 0.14
Nodes (22): add_template(), api_check(), api_recipients(), campaign_detail(), campaigns(), new_campaign(), Live compliance check + preview for the campaign composer., send_campaign() (+14 more)

### Community 25 - "Database schema (tables)"
Cohesion: 0.13
Nodes (24): activity_logs, allergies, appointments, care_protocols, clinical_indicators, clinical_rules, conditions, drug_classes (+16 more)

### Community 26 - "Appointments"
Cohesion: 0.10
Nodes (10): list_appointments(), new_appointment(), set_status(), AppointmentRepository, AppointmentService, Mark an appointment done; if recurring, auto-create the next one., AppointmentRepository, Repository for appointments. (+2 more)

### Community 27 - "Chart.js stacking"
Cohesion: 0.09
Nodes (11): es(), is(), ls, Qi(), rs, ss(), ts(), update() (+3 more)

### Community 28 - "Manager/ops UI views"
Cohesion: 0.15
Nodes (21): Appointments — list + filter + status actions (list.html), Appointments — schedule new appointment (new.html), base.html (RTL/Jalali layout template), clinical_indicators (indicator thresholds/targets table), clinical_rules (ADA decision-rule catalog table), followup_engine (turns due rules/protocols into followup_tasks), Manager — ADA Decision Rules editor (decision_rules.html), Clinical Decision-Rule Editor (text/severity/evidence/active per rule) (+13 more)

### Community 29 - "Chart.js animation"
Cohesion: 0.16
Nodes (5): Cs, fe(), nn(), pi(), sn

### Community 30 - "SMS provider (Mediana)"
Cohesion: 0.18
Nodes (11): SendResult, MedianaProvider, Mediana SMS provider adapter (https://api.mediana.ir).  Auth: header `X-API-KEY:, Return the panel wallet balance, or None on failure., get_provider(), NullProvider, SMS provider abstraction.  Concrete providers (e.g. Mediana) implement `send`. T, Test/simulation provider: logs to console, never actually sends. (+3 more)

### Community 31 - "Chart.js dataset visibility"
Cohesion: 0.15
Nodes (3): an(), generateLabels(), onClick()

### Community 33 - "Chart.js label sizing"
Cohesion: 0.17
Nodes (3): H(), ks(), Xs()

### Community 34 - "Glucose-lowering drug selection"
Cohesion: 0.17
Nodes (16): ACEi/ARB (RAS inhibition), ASCVD (atherosclerotic cardiovascular disease), CKD (chronic kidney disease, G1-G5/A1-A3), DPP-4 inhibitor (DPP-4i), eGFR (estimated glomerular filtration rate, CKD-EPI 2021), Finerenone (nsMRA), GLP-1 receptor agonist (GLP-1 RA), Metformin (oral, historic first-line) (+8 more)

### Community 35 - "Revenue dashboard"
Cohesion: 0.17
Nodes (11): index(), format_jalali_datetime(), parse_datetime(), Parse a 'YYYY-MM-DD HH:MM:SS' / 'YYYY-MM-DD' string (or datetime) to datetime., Format datetime (or string) as Jalali date+time string., _jalali_month_start_gregorian(), Revenue analytics for the specialist clinic, sourced from the accounting DB (rea, Gregorian 'YYYY-MM-DD' of the first day of the current Jalali month. (+3 more)

### Community 36 - "Chart.js helpers (misc)"
Cohesion: 0.14
Nodes (11): ei(), getRange(), hi(), ii(), je(), K(), li(), Ni() (+3 more)

### Community 37 - "Clinical flags repository"
Cohesion: 0.19
Nodes (5): analytics(), ClinicalFlagsRepository, _parse_options(), Repository for clinical decision inputs: flag_catalog, patient_flags, drug_class, HFrEF|EF کاهش‌یافته,unknown|نامشخص' -> [{value,label}, ...]

### Community 38 - "Clinical indicators repository"
Cohesion: 0.22
Nodes (6): ClinicalRulesRepository, Repository for the editable clinical decision rules (clinical_indicators).  This, All indicators ordered for display. Cached per-request on flask.g., {key: indicator} map., Indicators that apply to a patient with the given condition codes.          An i, Update editable fields of one indicator.

### Community 40 - "Chart.js legend"
Cohesion: 0.23
Nodes (3): afterUpdate(), tt(), xa

### Community 42 - "Decision-support architecture"
Cohesion: 0.20
Nodes (12): ADA Standards of Care in Diabetes 2026, Expert Advisor — suggestion-only decision support engine, Safety principle: system suggests, physician confirms (پیشنهاد — تأیید با پزشک), clinical_indicators table (targets/thresholds), clinical_rules table (If/Then rule catalog), clinical_rules_seed.py (~50 ADA rules seed), /manager/rules clinical-rules admin center, RuleEvaluator (trigger tree evaluator) (+4 more)

### Community 43 - "Chart.js grid drawing"
Cohesion: 0.24
Nodes (4): Ae(), Ci(), Fi(), ge()

### Community 44 - "Chart.js DOM events"
Cohesion: 0.21
Nodes (6): ct(), ge(), ms(), we(), ws, ys()

### Community 45 - "Chart.js pixel mapping"
Cohesion: 0.17
Nodes (5): beforeLayout(), getValueForPixel(), j(), ko, qo()

### Community 46 - "Chart.js element drawing"
Cohesion: 0.20
Nodes (8): As(), beforeDraw(), draw(), getMaxOverflow(), kn(), qn(), size(), uo()

### Community 47 - "Red flags & hypoglycemia"
Cohesion: 0.20
Nodes (10): DKA (diabetic ketoacidosis; euglycemic DKA with SGLT2i), Glucagon (prescribe for all insulin users, 6.16), HHS (hyperosmolar hyperglycemic state), Hypoglycemia classification (Level 1/2/3, Table 6.4), Individualized A1c target (tight <6.5%, relaxed up to 8%), Red Flags (immediate referral: severe hypo, DKA/HHS, BP≥180/110, Fournier gangrene), Rule of 15 (15g carbohydrate, recheck 15 min), Rule T2-MED-OLDER-01 (frail elderly → low-hypo agents, relaxed targets) (+2 more)

### Community 50 - "BP & lipid targets"
Cohesion: 0.25
Nodes (9): Blood pressure (systolic/diastolic), Blood pressure target (<130/80; <120 SBP high-risk; <140/90 frail), LDL cholesterol indicator, Lipid target (LDL <70 high CV risk, ≥50% reduction), Standards of Care 2025 Abridged for Primary Care (Clin Diabetes, DOI 10.2337/cd25-aint), Clinical reference (thresholds & targets source), Summary of Revisions: Standards of Care 2026 (Diabetes Care 49 Suppl 1:S6), analytics_service.TARGETS (clinical target map) (+1 more)

### Community 51 - "Glycemic targets & diagnosis"
Cohesion: 0.33
Nodes (7): CGM (continuous glucose monitoring) / TIR-TBR-TAR, Diabetes diagnosis criteria (A1c≥6.5 / FPG≥126 / 2hPG≥200 / random≥200+symptoms), FPG (fasting plasma glucose), Glycemic target (A1c <7.0%, pre-meal 80-130, peak <180), HbA1c (glycated hemoglobin) indicator, PPG (postprandial glucose / 1-2h peak), Prediabetes (A1c 5.7-6.4 / IFG / IGT)

### Community 52 - "Complication screening schedule"
Cohesion: 0.29
Nodes (7): Complication screening schedule (eye/foot/neuropathy/renal/lipid), Dilated eye exam (retinopathy screening), Foot exam + 10g monofilament / neuropathy screening, UACR (urine albumin-to-creatinine ratio), Vaccination (influenza/pneumococcal/hepatitis B/COVID/zoster), followup_engine (Engine 3 — monitoring/follow-up), followup_tasks table (idempotent due-date tasks)

### Community 53 - "Insulin therapy & titration"
Cohesion: 0.29
Nodes (7): GLP-1-based therapy preferred over insulin (9.21), Insulin (basal/bolus, human and analog), Insulin initiation algorithm (A1c>10%, glucose≥300, catabolism), Insulin start/titration doses (basal 10U or 0.1-0.2U/kg, bolus 4U), Rule T2-MED-HYPO-01 (high hypo risk → low-hypo agents, deintensify), Sulfonylurea (SU, 2nd generation), Insulin dose calculator (explicit ADA numbers)

### Community 54 - "Engagement: SMS, wallet, reminders"
Cohesion: 0.38
Nodes (7): wallet_repo.py (wallet_transactions), Background scheduler (reminders, campaigns, backups), settings table (SMS keys/config), SMS via Mediana integration, Patient wallet credit (lawful discount framing), Appointments + periodic auto-visits + SMS reminders, Targeted SMS campaign feature

### Community 55 - "Design system (dark dashboard)"
Cohesion: 0.43
Nodes (7): window.CLINIC_THEME (chart color theme), Component classes (.card/.btn/.kpi/.badge/.table-wrap/.tiles), CSS variable tokens (app.css: surfaces/lines/text/semantic/spacing/radius), Design System (Dark Data-Dense Dashboard), Design HARD RULES (preserve logic, RTL/Jalali, no raw hex), Jalali/Persian Jinja filters (|fa_num |jalali |jalali_date, .jdate), SVG icon sprite (#i-NAME use refs in base.html)

### Community 56 - "Iranian ID/phone validators"
Cohesion: 0.33
Nodes (5): تابع validation برای کدملی ایرانی., اعتبارسنجی شماره موبایل ایرانی.          شماره باید 11 رقم و با 09 شروع شود., اعتبارسنجی کدملی ایرانی با الگوریتم استاندارد.          Examples:         >>>, validate_iranian_national_id(), validate_iranian_phone()

### Community 58 - "AvalAI AI API gateway"
Cohesion: 0.50
Nodes (5): Anthropic-compatible Messages interface, AvalAI unified AI API gateway, Persian/Iran-focused service (Toman billing), OpenAI-compatible interface (base URL + Bearer key), Structured Outputs / JSON mode

### Community 59 - "persian-date library"
Cohesion: 0.83
Nodes (3): e(), i(), t()

### Community 60 - "Obesity drug rule"
Cohesion: 0.67
Nodes (3): Dual GIP/GLP-1 RA (tirzepatide), Obesity / overweight, Rule T2-MED-OBESITY-01 (obesity → weight-lowering GLP-1/dual)

### Community 61 - "MASLD / liver drug rule"
Cohesion: 0.67
Nodes (3): FIB-4 (liver fibrosis index, AST/ALT/platelets), MASLD/MASH (metabolic-associated steatotic liver disease), Rule T2-MED-MASLD-01 (MASLD → GLP-1 RA / dual)

### Community 62 - "Heart-failure drug rule"
Cohesion: 0.67
Nodes (3): Heart failure (HF, HFrEF/HFpEF), Rule T2-MED-HF-01 (HF → SGLT2i; TZD contraindicated), Thiazolidinedione / pioglitazone (TZD)

## Ambiguous Edges - Review These
- `mediana_provider.py` → `jdatetime dependency (>=4.0)`  [AMBIGUOUS]
  requirements.txt · relation: conceptually_related_to

## Knowledge Gaps
- **89 isolated node(s):** `allow`, `Row`, `users`, `settings`, `activity_logs` (+84 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **22 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `mediana_provider.py` and `jdatetime dependency (>=4.0)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `_()` connect `Chart.js core & easing` to `Chart.js option resolver`, `Chart.js title rendering`, `jQuery internals`, `Chart.js helpers`, `Chart.js scale generation`, `Chart.js registry`, `Chart.js radial/grid scale`, `Chart.js bar controller`, `Persian datepicker / arc`, `Chart.js element interaction`, `Chart.js scale bounds`, `Chart.js dataset parsing`, `Chart.js layout/fit`, `Chart.js stacking`, `Chart.js animation`, `Chart.js dataset visibility`, `Chart.js tick hooks`, `Chart.js label sizing`, `Chart.js helpers (misc)`, `Chart.js dataset controllers`, `Chart.js legend`, `Chart.js chart lifecycle`, `Chart.js grid drawing`, `Chart.js DOM events`, `Chart.js pixel mapping`, `Chart.js element drawing`, `Chart.js event binding`, `Chart.js render pipeline`, `Chart.js hover handling`?**
  _High betweenness centrality (0.167) - this node is a cross-community bridge._
- **Why does `get_db()` connect `SQLite repositories` to `API routes (blueprints)`, `Revenue dashboard`, `ADA rule engine`, `Clinical flags repository`, `Clinical indicators repository`, `DB core & accounting bridge`, `Jalali date utilities`, `Auth & activity logging`, `App bootstrap & scheduler`, `Patient analytics & wallet`, `Follow-up worklist engine`, `SMS campaign service`, `Appointments`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Why does `js()` connect `Chart.js layout/fit` to `Chart.js tick hooks`, `Chart.js label sizing`, `Chart.js title rendering`, `Chart.js core & easing`, `Chart.js grid drawing`, `Chart.js radial/grid scale`, `Chart.js pixel mapping`, `Chart.js bar controller`, `Chart.js scale bounds`, `Chart.js dataset parsing`, `Chart.js stacking`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **What connects `allow`, `Read-only bridge to the accounting app's database (clinic_new.db).  CRITICAL SAF`, `Open a read-only connection to the accounting DB, or None if unavailable.` to the rest of the system?**
  _195 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Chart.js option resolver` be split into smaller, more focused modules?**
  _Cohesion score 0.06594071385359952 - nodes in this community are weakly interconnected._
- **Should `API routes (blueprints)` be split into smaller, more focused modules?**
  _Cohesion score 0.05909090909090909 - nodes in this community are weakly interconnected._
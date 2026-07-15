# دور سوم پژوهش عمیق — قرارداد ماژول بیماری و حاکمیت موتور پیشنهاد

**تاریخ:** ۲۰۲۶-۰۷-۱۵  
**وضعیت:** Research architecture / governance proposal؛ نه rule بالینی نهایی  
**دامنه:** Clinical Program Package، evidence registry، نسخه‌بندی و انتشار rule، recommendation instance، alert fatigue، validation و سنجش اثر

---

## ۱. مسئلهٔ اصلی

موتور بالینی فقط با «درست‌بودن چند IF/THEN» علمی نمی‌شود. یک موتور قابل دفاع باید پاسخ دهد:

1. این پیشنهاد از کدام نسخهٔ شواهد آمده است؟
2. برای چه جمعیتی معتبر و برای چه کسانی نامعتبر است؟
3. کدام دادهٔ بیمار آن را فعال کرده و کیفیت آن داده چیست؟
4. در چه زمان و workflow باید دیده شود؟
5. پزشک چرا آن را پذیرفت، رد کرد یا به تعویق انداخت؟
6. rule پس از تغییر guideline چگونه version، validate، deploy و rollback می‌شود؟
7. چگونه می‌فهمیم rule مفید، بی‌اثر یا پرسر‌وصداست؟
8. مسئول علمی، ایمنی، محصول و عملیات آن چه کسی است؟

تز این دور:

> **ماژول بیماری در حلقه باید یک بستهٔ نسخه‌دارِ شواهد + داده + برنامهٔ مراقبت + workflow + UX + سنجش باشد؛ نه مجموعه‌ای از جدول‌ها و ruleهای مستقل.**

---

## ۲. وضعیت واقعی موتور فعلی

### نقاط قوت تثبیت‌شده

- `rule_engine.py` صریحاً suggestion-only است و هر rule fired این اصل را حمل می‌کند.
- factها از observation، diagnosis، flag، medication class و demographics ساخته می‌شوند.
- observationهای self-report تنها با `verified=True` وارد موتور می‌شوند؛ این verified gate یکی از مهم‌ترین invariantهای محصول است.
- age-gated rule در نبود demographics fail-closed می‌شود.
- `clinical_indicators` منبع زندهٔ threshold/target است.
- population override فقط وقتی `approved` باشد اعمال می‌شود و draft inert است.
- پیشنهادهای accept/dismiss هم state فعلی و هم event append-only دارند.
- dashboard آماری فعلی صادقانه می‌گوید acceptance rate معیار کیفیت rule و معادل اثر علّی نیست.

### gapهای ساختاری

#### ClinicalRule

مدل فعلی این اطلاعات را دارد:

```text
rule_code, title, category, condition_code
trigger_json, recommendation, monitoring, contraindications
evidence_level, action_type, severity, priority, source_ref
is_active, notes
```

اما هنوز این موارد صریح و ساختاریافته نیستند:

- immutable rule version؛
- status چرخهٔ انتشار؛
- guideline/evidence package FK؛
- effective_from / expires_at / review_due_at؛
- clinical owner و reviewerها؛
- eligibility و exclusion ساختاریافته؛
- patient-facing wording version؛
- deployment scope و rollback target؛
- test package hash؛
- supersedes/superseded_by؛
- change rationale؛
- local adaptation classification.

`source_ref` و `evidence_level` متن آزادند؛ برای traceability کافی نیستند.

#### ClinicalIndicator

thresholdها در `clinical_indicators` tenant-scoped و قابل‌خواندن‌اند، اما چهار fallback عددی در Python نیز وجود دارد. این fallback برای availability مفید است ولی خطر **دو منبع حقیقتِ ناهمگام** ایجاد می‌کند. هر تغییر threshold باید seed، fallback، docs، tests و program version را هم‌زمان تغییر دهد یا fallbackها به یک artifact تولیدشده از package تبدیل شوند.

#### Suggestion history

- `suggestion_log` یک state mutable برای `(patient, rule_code)` است.
- `suggestion_events` append-only است، ولی snapshot فعلی عمدتاً text و evidence level را نگه می‌دارد.
- rule version، fact bundle hash، indicator version، program version و evidence package version در event مدل فعلی صریح نیستند.

بنابراین پس از تغییر rule، بازسازی دقیق این‌که «پزشک در آن لحظه دقیقاً چه نسخه‌ای را بر اساس چه facts دیده» دشوار می‌شود.

#### Population override

مکانیزم draft/approved و fail-safe ارزشمند است. بااین‌حال سطح manager API خوانده‌شده فقط listing و analytics read-only است و در comment خود approve را به مرحلهٔ بعد موکول کرده است. انتشار override باید در governance عمومی ruleها ادغام شود، نه یک مسیر استثنایی جدا.

---

## ۳. تعریف Clinical Program Package

هر بیماری یا مسیر بالینی یک package immutable و نسخه‌دار دارد:

```text
ClinicalProgram
└── ProgramVersion
    ├── EvidencePackage
    ├── EligibilityDefinition
    ├── ExclusionAndReferralPolicy
    ├── IndicatorDefinitions
    ├── MeasurementProtocols
    ├── RiskStratification
    ├── CarePlanTemplates
    ├── GoalsAndActivities
    ├── RecommendationRules
    ├── MedicationSafetyRules
    ├── EscalationProtocols
    ├── PatientContent
    ├── ClinicianPresentation
    ├── WorklistRouting
    ├── OutcomeAndProcessMetrics
    ├── SyntheticFixtures
    └── ValidationReport
```

### اصل package

- افزودن بیماری فقط «چند rule جدید» نیست.
- package بدون patient UX، worklist owner و metric قابل انتشار نیست.
- package بدون evidence و test در حالت draft می‌ماند.
- tenant یک نسخهٔ منتشرشده را adopt می‌کند؛ ruleهای همان نسخه با یکدیگر سازگارند.

---

## ۴. مدل دادهٔ پیشنهادی

### ۴.۱ ClinicalProgram

```text
program_key
name_fa / name_en
domain
intended_population
program_owner
status
created_at
```

نمونهٔ keyهای پیشنهادی، فقط برای نام‌گذاری:

```text
t2d_adult
hypertension_adult
ascvd_risk_management
heart_failure_followup
```

«cardiac» یا «heart disease» به‌تنهایی برای program key بیش از حد مبهم است.

### ۴.۲ ProgramVersion

```text
program_id
semantic_version
status
release_notes
effective_from
review_due_at
supersedes_version_id
package_manifest_sha256
created_by
approved_at
retired_at
```

### ۴.۳ EvidenceSource

```text
title
organization_or_journal
source_type
guideline_version
publication_date
doi
canonical_url
retrieved_at
superseded_at
license_or_access_note
```

### ۴.۴ EvidenceStatement

یک guideline چند statement دارد. هر statement:

```text
source_id
statement_key
verbatim_excerpt_pointer
normalized_claim
population
intervention_or_action
comparators
outcomes
recommendation_strength
certainty_of_evidence
exceptions
reviewer_notes
```

متن کامل copyrighted در DB کپی نمی‌شود؛ pointer، citation و خلاصهٔ مجاز ذخیره می‌شود.

### ۴.۵ RuleDefinition و RuleVersion

```text
RuleDefinition:
  stable_rule_key
  program_id
  intent

RuleVersion:
  rule_definition_id
  semantic_version
  trigger_json
  eligibility_json
  exclusion_json
  missing_data_policy
  recommendation_template
  candidate_actions_json
  urgency
  presentation_mode
  cooldown
  expiration_policy
  evidence_statement_ids
  authored_by
  reviewed_by
  status
  effective_from
  review_due_at
  manifest_hash
```

`rule_code` ثابت برای identity کافی است، ولی logic باید immutable version داشته باشد.

### ۴.۶ RecommendationInstance

هر بار که rule برای بیمار materialize می‌شود:

```text
recommendation_id
rule_version_id
program_version_id
tenant_id
patient_link_id
fact_snapshot_hash
fact_provenance_json
missing_data_json
triggered_at
expires_at
urgency
presentation_mode
status
superseded_by
```

### ۴.۷ RecommendationDecision

```text
recommendation_id
decision
reason_code
reason_note
acted_by
acted_at
resulting_care_plan_id
resulting_task_id
resulting_order_or_prescription_id
```

تصمیم‌ها:

```text
accepted
accepted_modified
dismissed_not_applicable
dismissed_already_addressed
dismissed_bad_data
dismissed_patient_preference
deferred_need_information
deferred_followup
expired
```

reason taxonomy از free text مهم‌تر است؛ note اختیاری تکمیل‌کننده است.

### ۴.۸ RuleTestCase

```text
rule_version_id
case_key
facts_json
expected_fire
expected_urgency
expected_action_keys
expected_missing_data
clinical_rationale
reviewer
```

### ۴.۹ Deployment و Monitoring

```text
RuleDeployment
  rule_version_id
  tenant/program scope
  mode: shadow | pilot | active
  started_at
  percentage_or_cohort
  rollback_version

RuleMetricDaily
  exposures
  patient_days
  accepted/dismissed/deferred
  time_to_review
  time_to_action
  repeat burden
  missing_data
  downstream completion
  safety flags
```

---

## ۵. تفکیک knowledge، policy و patient plan

این سه نباید در یک جدول یا admin form مخلوط شوند.

### Global Clinical Knowledge

- guideline-derived؛
- توسط clinical governance منتشر می‌شود؛
- immutable version؛
- tenant آن را مستقیم ویرایش نمی‌کند.

### Tenant Operational Policy

- چه roleی review می‌کند؛
- SLA؛
- ساعات کاری؛
- channel؛
- queue assignment؛
- presentation preference؛
- محدود به دامنهٔ عملیاتی، نه تغییر علمی rule.

### Patient-specific Plan

- target فردی؛
- goal؛
- cadence؛
- contraindication/context؛
- تصمیم پزشک؛
- در care plan مصوب ذخیره می‌شود.

### Local Clinical Adaptation

گاهی واقعاً لازم است. اما باید:

```text
local_protocol_overlay
→ rationale
→ evidence
→ scope
→ clinical owner
→ expiry/review date
→ tests
→ approval
```

داشته باشد. «مدیر tenant عدد را تغییر دهد» مدل ایمن نیست.

---

## ۶. چرخهٔ انتشار rule

```text
draft
→ evidence_review
→ specialist_review
→ medication_safety_review   (در صورت ارتباط)
→ informatics_review
→ test_validated
→ shadow
→ pilot
→ active
→ paused
→ superseded | retired
```

### گیت‌ها

#### Evidence review

- citation معتبر؛
- نسخه و تاریخ؛
- population و exclusions؛
- strength/certainty؛
- اختلاف guidelineها ثبت شده است.

#### Clinical review

- حداقل متخصص مرتبط یا GP panel؛
- red flagها و referral boundaries؛
- patient safety wording؛
- feasibility در مطب واقعی.

#### Pharmacy review

برای ruleهای دارویی:

- drug-drug؛
- drug-disease؛
- renal/hepatic adjustment؛
- pregnancy/frailty؛
- monitoring prerequisites؛
- deprescribing concern.

#### Informatics review

- DSL semantics؛
- missing-data policy؛
- duplicate/conflicting rules؛
- ordering؛
- provenance؛
- RLS/tenant safety؛
- performance.

#### Validation review

- tests سبز؛
- retrospective replay؛
- shadow metrics؛
- alert burden؛
- clinician chart review؛
- rollback آماده.

---

## ۷. Versioning و change control

### Semantic versioning پیشنهادی

```text
MAJOR: تغییر meaning، population، threshold یا action که رفتار بالینی را materially عوض می‌کند
MINOR: افزودن rule/indicator/education سازگار
PATCH: wording، typo، presentation یا bug بدون تغییر intended clinical behavior
```

### هر release باید manifest داشته باشد

```text
program version
rule versions
indicator versions
evidence statement versions
care-plan template versions
patient content versions
test fixture hashes
validation report hash
reviewer approvals
git commit / artifact digest
```

### rollback

- rollback به package version قبلی، نه ویرایش دستی چند row؛
- recommendation instanceهای قبلی تاریخچه‌شان را حفظ می‌کنند؛
- recommendation قدیمی می‌تواند superseded شود ولی overwrite نمی‌شود؛
- care plan پذیرفته‌شده با rollback موتور خودکار لغو نمی‌شود؛ پزشک تصمیم گرفته است.

---

## ۸. Fact provenance و data quality

هر fact واردشده به recommendation باید این context را داشته باشد:

```text
fact_key
value
unit
source_table/source_system
source_record_id
observed_at
received_at
verified
verified_by
measurement_protocol
quality_flags
version/transformation
```

### Missing data policy

هر leaf/rule یکی از policyهای زیر را صریح دارد:

```text
fail_closed
emit_data_gap
not_applicable
use_approved_default
```

default clinical پنهان ممنوع است. fallback threshold باید در explanation و telemetry قابل مشاهده باشد.

### stale data

هر indicator max age دارد. مقدار قدیمی نباید مانند مقدار تازه وارد rule شود مگر rule صریحاً historical intent داشته باشد.

### conflicting data

وقتی vital و lab یا manual و device conflict دارند، resolution policy program-specific است. «آخرین مقدار» همیشه از نظر بالینی بهترین fact نیست.

---

## ۹. Recommendation contract در UI پزشک

هر پیشنهاد باید در یک نگاه این شش سؤال را پاسخ دهد:

1. **چه چیزی پیشنهاد می‌شود؟**
2. **چرا اکنون؟**
3. **بر اساس کدام داده؟**
4. **چه داده‌ای کم است یا نامطمئن است؟**
5. **منبع علمی چیست؟**
6. **اقدام بعدی چیست؟**

### ساختار کارت

```text
severity + intent
recommendation summary
why-now facts
contraindications / safety
missing data
candidate actions
source/evidence drawer
accept / modify / defer / dismiss
```

### اصل explanation

Explainability یعنی نمایش input، rule، exclusion و evidence؛ نه نمایش chain-of-thought مدل.

---

## ۱۰. Alert policy و بودجهٔ توجه

### tierها

| Tier | شکل نمایش | شرط |
|---|---|---|
| A — Critical interruptive | modal/hard attention | خطر نادر، فوری، high specificity، action واضح |
| B — Safety inline | بالای context مرتبط | مهم ولی قابل review در workflow |
| C — Actionable recommendation | کارت پیشنهاد | تصمیم درمانی/پایش در ویزیت |
| D — Worklist task | صف تیم | قابل واگذاری، deadline و SLA |
| E — Digest/cohort | گزارش manager | population management |
| F — Silent | telemetry/shadow | تحقیق، validation و quality |

### قوانین interruption

- interruptive فقط اگر response فوری و owner واقعی وجود دارد؛
- یک rule نباید در یک encounter چندبار interrupt کند؛
- snooze/cooldown از جنس clinical intent است، نه صرفاً UI؛
- alertهای هم‌علت باید bundle شوند؛
- hard stop فقط با evidence قوی، خطر شدید و مسیر override امن؛
- reason override ثبت می‌شود؛
- patient safety هرگز با هدف کاهش count حذف نمی‌شود، ولی specificity باید اصلاح شود.

### Alert budget

برای هر role و context بودجه تعریف شود:

```text
interruptions per encounter
new recommendation cards per patient
repeated exposures per rule/patient/week
queue items per care coordinator/day
```

بودجه یک safety monitoring threshold است؛ rule پرسر‌وصدا pause/review می‌شود، نه اینکه تیم مجبور به عادت‌کردن شود.

---

## ۱۱. Validation ladder

### Level 0 — Schema/DSL validation

- JSON schema؛
- operator whitelist؛
- type/unit compatibility؛
- unreachable branch؛
- conflicting action؛
- dependency وجود دارد.

### Level 1 — Unit and fixture

- positive/negative boundary cases؛
- missing facts؛
- exact threshold؛
- age/population؛
- contraindication؛
- verified gate؛
- tenant isolation.

### Level 2 — Synthetic longitudinal patients

- چند ویزیت/اندازه‌گیری؛
- تغییر دارو؛
- data stale/conflict؛
- multimorbidity؛
- event ordering؛
- no duplicate task.

### Level 3 — Retrospective replay

روی دادهٔ de-identified/sanitised:

- fire prevalence؛
- chart-review precision؛
- missed eligible cases؛
- subgroup distribution؛
- workload projection؛
- conflict با تصمیم واقعی.

این مرحله efficacy را ثابت نمی‌کند.

### Level 4 — Shadow mode

- rule محاسبه می‌شود ولی به پزشک نشان داده نمی‌شود؛
- stability، latency، volume و data gaps سنجیده می‌شود؛
- candidate cases توسط panel مرور می‌شوند.

### Level 5 — Limited pilot

- یک tenant/cohort؛
- feature flag؛
- daily safety review؛
- rollback؛
- no automated patient action.

### Level 6 — Prospective evaluation

- process outcome؛
- patient safety؛
- workload؛
- adoption؛
- care-loop completion؛
- اگر claim بالینی مدنظر است، design مناسب comparator/holdout و زمان کافی.

### Level 7 — Post-deployment surveillance

- drift؛
- guideline expiry؛
- subgroup inequity؛
- incident/near miss؛
- override pattern؛
- clinician feedback؛
- periodic revalidation.

---

## ۱۲. Metric framework

### ۱۲.۱ Technical

```text
latency
engine failure
fact resolution failure
version mismatch
duplicate materialization
queue delivery failure
```

### ۱۲.۲ Data quality

```text
missing required facts
stale facts
unverified fact exclusion
unit mismatch
out-of-range input
source conflict
```

### ۱۲.۳ Exposure

```text
eligible patients
rules evaluated
recommendations fired
unique patient-days
repeat exposures
```

### ۱۲.۴ Human response

```text
viewed
accepted
accepted_modified
dismissed by reason
deferred by reason
time to review
time to decision
```

### ۱۲.۵ Workflow

```text
task created
assigned
completed
escalated
time to action
loop closed
```

### ۱۲.۶ Quality review

```text
chart-review true actionable
false positive
missed eligible
unsafe wording
wrong urgency
missing contraindication
```

### ۱۲.۷ Patient outcome

بعداً و با design معتبر:

```text
control status over time
screening completion
adherence proxy
hospital/ED outcomes where available
patient-reported burden/quality of life
```

### نکتهٔ حیاتی

Acceptance rate بالا می‌تواند ناشی از آسان‌بودن، bias، تکرار یا lack of scrutiny باشد. Dismissal rate بالا هم لزوماً rule بد نیست. کیفیت با denominator، case review، downstream action و safety سنجیده می‌شود.

---

## ۱۳. Clinical Program Contract — قالب اجباری

هر program پیش از ساخت باید این سند را پر کند:

### A. Definition

```text
program key
condition and scope
population
care setting
clinical owner
version
```

### B. Inclusion / Exclusion / Referral

- eligibility؛
- exclusions؛
- pregnancy؛
- age؛
- comorbidity؛
- referral/red flag؛
- scope boundary.

### C. Data contract

- required observations؛
- optional observations؛
- units؛
- source/protocol؛
- freshness؛
- verification؛
- quality rules.

### D. Measurement protocol

- cadence؛
- context؛
- patient instruction؛
- device validation؛
- aggregation؛
- missing/abnormal handling.

### E. Care plan

- goals؛
- activities؛
- roles؛
- cadence؛
- closure evidence؛
- escalation.

### F. CDS

- rules؛
- evidence؛
- exclusions؛
- action types؛
- explanation؛
- alert tier؛
- cooldown؛
- test cases.

### G. Patient experience

- Today actions؛
- education؛
- caregiver role؛
- language/health literacy؛
- emergency boundary.

### H. Team workflow

- inbox/queue؛
- owner؛
- SLA؛
- escalation؛
- coverage hours؛
- staffing/capacity.

### I. Metrics

- process؛
- safety؛
- workload؛
- equity؛
- outcome؛
- minimum sample and caveat.

### J. Rollout

- shadow؛
- pilot؛
- rollback؛
- training؛
- sign-off؛
- review date.

---

## ۱۴. Scope پیشنهادی programهای اولیه

این بخش rule یا guideline نیست؛ مرزبندی محصول است.

### ۱۴.۱ Type 2 Diabetes — Adult

#### داخل نسخهٔ اول

- adult T2D enrollment؛
- HbA1c/FBS و context سنجش؛
- BP/lipid/kidney screening dependencies؛
- medication list/class؛
- hypoglycemia/frailty/pregnancy flags برای exclusion/safety؛
- periodic lab/screening tasks؛
- clinician-approved goals؛
- education و refill follow-up؛
- suggestion-only therapy/monitoring support.

#### خارج نسخهٔ اول مگر package جدا

- Type 1 dosing automation؛
- closed-loop insulin control؛
- gestational diabetes؛
- pediatric diabetes؛
- autonomous insulin titration؛
- CGM interpretation as treatment command.

### ۱۴.۲ Hypertension — Adult

#### داخل

- diagnosis/enrollment؛
- home BP measurement protocol؛
- repeated reading/context؛
- adherence و medication classes؛
- CKD/diabetes/CVD context؛
- follow-up cadence؛
- clinician review/titration suggestion؛
- lifestyle education؛
- uncontrolled cohort worklist.

#### خارج یا جدا

- pregnancy/postpartum HTN؛
- pediatric HTN؛
- hypertensive emergency autonomous triage؛
- secondary HTN diagnostic workup engine؛
- patient self-titration بدون protocol مصوب.

### ۱۴.۳ Cardiovascular

یک program واحد «قلب» ممنوع است. سه مسیر مستقل:

#### ASCVD Risk Management

- established ASCVD vs primary prevention؛
- lipid/BP/diabetes/smoking context؛
- prevention and monitoring plan.

#### Heart Failure Follow-up

- known HF؛
- weight/symptom/BP/HR protocol؛
- post-discharge/follow-up tasks؛
- medication monitoring prerequisites؛
- escalation workflow و staff capacity.

#### Post-event Secondary Prevention

- post-MI/stroke/procedure؛
- medication reconciliation؛
- rehab/follow-up؛
- risk-factor control؛
- education.

هر کدام evidence، role و red-flag متفاوت دارد.

---

## ۱۵. Multimorbidity و conflict resolution

وقتی بیمار چند program فعال دارد:

- یک fact می‌تواند به چند program feed شود؛
- taskهای هم‌زمان باید deduplicate/bundle شوند؛
- targetهای متعارض باید conflict object تولید کنند؛
- دارو/contraindication cross-program بررسی می‌شود؛
- priority نباید فقط مجموع scoreها باشد؛
- patient plan واحد است، ولی provenance هر activity به program محفوظ می‌ماند.

### Conflict object

```text
conflict_type
program_versions
rules/actions involved
patient context
severity
resolution owner
status
resolution decision
```

موتور نباید یک conflict بالینی را با priority عددی پنهان حل کند.

---

## ۱۶. LLM/AI boundary

### مجاز در نزدیک‌مدت

- evidence search assistant با citation؛
- draft خلاصهٔ پرونده از facts ساختاریافته؛
- draft patient explanation از care plan مصوب؛
- clustering reasonهای dismiss برای review؛
- پیشنهاد test case، با review انسانی؛
- terminology mapping، نه source of truth.

### ممنوع یا research-only

- ساخت rule و انتشار خودکار؛
- تغییر threshold؛
- autonomous treatment selection؛
- direct patient diagnosis؛
- خلاصهٔ بدون citation/provenance؛
- training روی PHI بدون governance؛
- استفاده از مدل خارجی بدون data agreement و threat model.

### ثبت اجباری

```text
model/provider/version
prompt/template version
input sources
output hash
human reviewer
decision/use
```

explanation مدل جای evidence traceability را نمی‌گیرد.

---

## ۱۷. ساختار تیم Clinical Governance

### Clinical Knowledge Board

- GP/family medicine؛
- specialist مرتبط؛
- clinical pharmacist؛
- clinical research advisor؛
- clinical data scientist؛
- product/UX برای workflow؛
- security/privacy و legal در قابلیت پرریسک.

### مسئولیت‌ها

| نقش | مسئولیت |
|---|---|
| Program owner | scope و نتیجهٔ کلی |
| Evidence lead | search/appraisal/update |
| Specialist reviewer | صحت تخصصی |
| GP reviewer | کاربردپذیری primary care |
| Pharmacist | safety دارویی |
| Informatics owner | DSL/data/provenance |
| Product/UX | timing و actionability |
| QA | test/validation evidence |
| Safety officer | incident/pause/rollback |

هیچ rule بالینی با approval یک مدیر عمومی منتشر نمی‌شود.

---

## ۱۸. Incident و emergency change

### Incident types

```text
unsafe recommendation
missed high-risk case
wrong patient/tenant
bad data provenance
excessive alert burden
incorrect patient wording
guideline superseded
model/rule drift
```

### پاسخ

1. pause rule/program version؛
2. preserve evidence و event log؛
3. identify affected recommendation instances؛
4. clinician-led patient impact review؛
5. rollback؛
6. root cause؛
7. correction + regression tests؛
8. reapproval؛
9. transparent release note.

Emergency patch نیز approval و audit می‌خواهد؛ سرعت به معنی overwrite تاریخچه نیست.

---

## ۱۹. Acceptance criteria برای governance backbone

### Rule version immutability

```text
Given یک RuleVersion active است
When logic یا wording material تغییر می‌کند
Then row قبلی update نمی‌شود
And نسخهٔ جدید با manifest جدید ساخته می‌شود
And recommendationهای قبلی به نسخهٔ قبلی اشاره می‌کنند
```

### Evidence expiry

```text
Given review_due_at گذشته است
When deployment gate اجرا می‌شود
Then rule جدید برای tenant تازه فعال نمی‌شود
And owner هشدار review می‌گیرد
And active rule بر اساس policy pause یا grace-period می‌شود
```

### Shadow safety

```text
Given deployment mode=shadow
When rule fire می‌شود
Then پزشک/بیمار آن را نمی‌بیند
And exposure، facts، expected workload و review sample ثبت می‌شوند
And هیچ task/order ساخته نمی‌شود
```

### Alert budget

```text
Given rule از threshold repeat burden عبور کرده است
When daily monitor اجرا می‌شود
Then safety review ایجاد می‌شود
And auto-promotion به active متوقف می‌شود
And rule بدون تصمیم board خاموش یا سبک‌تر نمی‌شود
```

### Tenant adaptation

```text
Given tenant می‌خواهد SLA یا assignee را تغییر دهد
Then operational policy قابل تغییر است
But trigger/threshold/evidence تغییر نمی‌کند
Unless local overlay با clinical approval و version مستقل ساخته شود
```

### Reproducibility

```text
Given recommendation تاریخی بررسی می‌شود
Then سیستم می‌تواند rule version، program version، fact provenance، evidence version و decision را بازسازی کند
Without relying on current mutable rows
```

---

## ۲۰. پژوهش و شواهد این دور

- knowledge-based CDSS in chronic disease: [Gholamzadeh et al., 2023](https://doi.org/10.1155/2023/8550905)
- clinician behavior and heterogeneous CDSS effects: [Ronan et al., 2022](https://doi.org/10.1002/jhm.12825)
- explainability failure modes and validation ladder: [Wang et al., 2026](https://doi.org/10.1111/exsy.70259)
- AI transparency/auditability in evidence workflows: [Ribeiro Junior et al., 2026](https://doi.org/10.1002/cesm.70080)
- lifecycle governance concepts: [Leon, 2026](https://doi.org/10.1002/sres.70014)
- diabetes algorithmic stewardship/human oversight: [Bemporad et al., 2026](https://doi.org/10.1002/dmrr.70139)
- current rule engine and verified gate: `halqe/clinical/rule_engine.py`
- current rule/indicator/suggestion models: `halqe/clinical/models.py`
- population override approval semantics: `halqe/clinical/population_service.py`
- honest suggestion analytics: `halqe/clinical/api/manager.py`
- WHO AI ethics and governance؛
- FDA Clinical Decision Support Software Guidance، ژانویهٔ ۲۰۲۶، به‌عنوان reference محافظه‌کارانهٔ طراحی و نه ادعای jurisdictional compliance.

شواهد governance مستقیم برای تمام جزئیات lifecycle rule-based CDS محدود است؛ بخشی از پیشنهاد حاضر synthesis مهندسی، clinical safety و AI lifecycle governance است و باید با متخصصان و وکیل رسمی نهایی شود.

---

## ۲۱. تصمیم‌های موقت دور سوم

1. `ClinicalRule` فعلی حفظ می‌شود ولی مسیر تکامل به RuleDefinition/RuleVersion لازم است.
2. ruleها باید تحت ProgramVersion منتشر شوند، نه مستقل.
3. evidence و threshold متن آزاد باقی نمی‌مانند.
4. recommendation تاریخی باید reproducible باشد.
5. acceptance/dismissal فقط telemetry رفتار است، نه برچسب ground truth.
6. interruptive alert به یک tier نادر و سخت‌گیر محدود می‌شود.
7. shadow mode گیت اجباری ruleهای material جدید است.
8. tenant فقط operational policy را آزادانه پیکربندی می‌کند؛ clinical knowledge governance جداست.
9. T2D و HTN program contractهای اول هستند؛ HF و ASCVD دو program جدا خواهند بود.
10. LLM در این مرحله author یا decision-maker بالینی نیست.

---

## ۲۲. گام پژوهشی بعدی

دور چهارم باید «Operating Model چندمستأجره و عمومی‌سازی حسابداری» را تا سطح ماتریس capability و bounded context پایین ببرد:

- مطب تک‌پزشک؛
- کلینیک تخصصی؛
- درمانگاه چندشیفت؛
- single/multi-location؛
- نقش‌ها، شعب، صندوق، payer، catalog، payroll، inventory و approval؛
- مرز revenue-cycle در برابر general ledger؛
- onboarding و packaging تجاری.

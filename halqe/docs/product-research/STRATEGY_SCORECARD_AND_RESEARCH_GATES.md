# Strategy Scorecard و Research Gates حلقه

**نسخه:** ۱.۰  
**تاریخ:** ۲۰۲۶-۰۷-۱۵  
**مالک پیشنهادی:** Product + Clinical + Implementation  
**کاربرد:** تبدیل فرضیه‌های پژوهش به تصمیم مستند `BUILD / PILOT / DEFER / KILL`  
**هشدار:** thresholdهای این سند نقطهٔ شروع‌اند و باید با دادهٔ پایلوت calibration شوند.

---

## ۱. چرا این سند وجود دارد

تیم محصول در حوزهٔ سلامت به‌سادگی می‌تواند سه چیز متفاوت را با هم اشتباه بگیرد:

```text
feature shipped
≠ workflow adopted
≠ service delivered safely
≠ patient outcome improved
≠ business model sustainable
```

این scorecard برای جلوگیری از این خطا ساخته شده است. هیچ قابلیت یا segment فقط به‌دلیل جذاب‌بودن demo، درخواست یک مشتری یا امکان فنی وارد roadmap نمی‌شود.

---

## ۲. واحد تصمیم

هر تصمیم باید یک **Decision Unit** روشن داشته باشد:

```yaml
id: STRAT-YYYY-NNN
question: "آیا ... را برای ... بسازیم/پایلوت کنیم؟"
segment: "..."
workflow: "..."
clinical_scope: "..."
buyer: "..."
users:
  - "..."
patient_population: "..."
owner: "..."
proposed_outcome: "..."
known_dependencies:
  - "..."
known_risks:
  - "..."
decision_due: "YYYY-MM-DD"
```

مثال معتبر:

> آیا صندوق درخواست refill و measurement برای بیماران بالغ HTN/T2D در کلینیک‌های غدد ۱ تا ۳ شعبه‌ای، پس از آماده‌شدن staff queue و SLA، وارد پایلوت شود؟

مثال نامعتبر:

> آیا پرتال بیمار بسازیم؟

---

## ۳. Evidence Ladder

هر ادعا با سطح evidence ثبت می‌شود:

| سطح | نوع شاهد | استفاده مجاز |
|---|---|---|
| E0 | نظر داخلی یا ایده | فقط سؤال پژوهش |
| E1 | درخواست مشتری/مصاحبه منفرد | فرضیه، نه commitment |
| E2 | الگوی تکرارشونده در چند مصاحبه یا observation | prototype/discovery |
| E3 | دادهٔ workflow و baseline واقعی | pilot design |
| E4 | usability/feasibility pilot | تصمیم به iteration یا محدودکردن scope |
| E5 | multi-site operational pilot | تصمیم به packaging و repeatability |
| E6 | effectiveness/economic evaluation معتبر | claim محدود و scale تصمیم‌گیری‌شده |

### قاعده

- E0/E1 برای build سنگین کافی نیست.
- E2 بدون owner و baseline برای pilot کافی نیست.
- E4 برای claim بالینی یا ROI کافی نیست.
- vendor page در capability mapping مفید است، ولی evidence outcome نیست.

---

## ۴. Segment Scorecard

### ۴.۱ وزن‌ها

| معیار | وزن | تعریف امتیاز ۱ | تعریف امتیاز ۵ |
|---|---:|---|---|
| Problem intensity | ۱۵٪ | درد کم/موردی | درد پرتکرار، پرهزینه یا پرخطر |
| Product fit | ۱۵٪ | نیازمند محصول جدید | دارایی‌های فعلی value فوری دارند |
| Workflow control | ۱۵٪ | buyer کنترل اندکی دارد | buyer می‌تواند role/process/SLA را تغییر دهد |
| Buyer clarity | ۱۰٪ | تصمیم‌گیر و budget مبهم | buyer و budget owner روشن |
| Implementation simplicity | ۱۵٪ | integration/procurement سنگین | pilot کم‌وابستگی و سریع |
| Safety manageability | ۱۰٪ | نیازمند پاسخ ۲۴/۷ یا liability بالا | scope و escalation محدود و روشن |
| Expansion potential | ۱۰٪ | استفادهٔ تک‌قابلیتی | مسیر روشن به module/location/program دیگر |
| Measurability | ۱۰٪ | baseline/outcome مبهم | event و outcome قابل ثبت |

### ۴.۲ فرمول

```text
Weighted score = Σ(score 1..5 × weight)
```

### ۴.۳ interpretation

| امتیاز | تصمیم پیش‌فرض |
|---:|---|
| ۴٫۲ تا ۵ | Discovery اولویت بالا؛ آمادهٔ Gate A |
| ۳٫۶ تا ۴٫۱۹ | Discovery محدود و مقایسه با ICP اصلی |
| ۳٫۰ تا ۳٫۵۹ | فقط فرصت خاص با شواهد قوی |
| ۲٫۵ تا ۲٫۹۹ | Defer |
| کمتر از ۲٫۵ | Kill برای دورهٔ فعلی |

### ۴.۴ template

| Segment | Problem | Fit | Control | Buyer | Simplicity | Safety | Expansion | Measure | Weighted | Evidence level |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
|  |  |  |  |  |  |  |  |  |  |  |

### ۴.۵ scorecard فعلی

| Segment | Weighted / 5 | Decision |
|---|---:|---|
| کلینیک تخصصی/چندتخصصی کوچک تا متوسط با پنل مزمن | ۴٫۴۵ | Primary discovery ICP |
| درمانگاه متوسط چندشیفت | ۳٫۶۵ | Secondary; پس از org/location/role maturity |
| مطب تک‌پزشک | ۳٫۳۰ | Core ممکن؛ Care Loop فقط با ظرفیت روشن |
| payer/employer | ۲٫۸۰ | Defer |
| hospital/large health system | ۲٫۵۵ | Defer |
| direct-to-consumer | ۲٫۲۰ | Kill برای thesis فعلی |

این امتیازها تا زمان field research قطعی نیستند.

---

## ۵. Opportunity Scorecard

هر workflow یا قابلیت با این ابعاد ارزیابی می‌شود:

| بعد | سؤال | وزن |
|---|---|---:|
| Frequency | چند بار در هفته/ماه رخ می‌دهد؟ | ۱۰٪ |
| Consequence | رهاشدن آن چه زیان/خطر/هزینه‌ای دارد؟ | ۱۵٪ |
| Ownership clarity | آیا یک نقش مسئول واقعی دارد؟ | ۱۵٪ |
| Closure clarity | آیا outcome/evidence قابل تعریف است؟ | ۱۵٪ |
| Existing-data fit | دادهٔ لازم اکنون موجود یا قابل اخذ است؟ | ۱۰٪ |
| Staff burden | آیا بار افزوده قابل‌قبول است؟ | ۱۰٪ |
| Patient value | آیا next action و confidence را بهتر می‌کند؟ | ۱۰٪ |
| Reusability | آیا در چند tenant/program تکرار می‌شود؟ | ۱۰٪ |
| Safety tractability | آیا boundary و escalation روشن است؟ | ۵٪ |

### تصمیم

- بالاتر از ۴٫۰: candidate برای prototype/pilot؛
- ۳٫۴ تا ۳٫۹۹: discovery بیشتر؛
- ۲٫۸ تا ۳٫۳۹: defer؛
- کمتر از ۲٫۸: kill مگر evidence جدید.

### candidateهای فعلی

| Workflow | تصمیم موقت | علت |
|---|---|---|
| post-visit follow-up | Build first | frequency بالا، owner و closure قابل تعریف |
| overdue lab/appointment | Build first | event و outcome روشن |
| refill/renewal request | Build first/next | routing ساختاریافته و value مستقیم |
| limited BP self-report → verify → review | Build next | ارزش بالا؛ وابسته به staff loop و verification |
| free-form clinical chat | Defer | scope و burden مبهم |
| HF high-acuity monitoring | Defer | staffing، alert و safety complexity بالا |
| automated medication titration | Kill for current phase | درمان خودکار و governance ناکافی |
| generic AI assistant | Kill as product wedge | pain/owner/outcome مبهم |

---

## ۶. Dependency Readiness Gate

پیش از build، هر dependency با `READY / PARTIAL / MISSING / BLOCKED` ثبت می‌شود.

```yaml
security_identity: READY|PARTIAL|MISSING|BLOCKED
tenant_scope: READY|PARTIAL|MISSING|BLOCKED
data_provenance: READY|PARTIAL|MISSING|BLOCKED
workflow_owner: READY|PARTIAL|MISSING|BLOCKED
staff_queue: READY|PARTIAL|MISSING|BLOCKED
sla_contract: READY|PARTIAL|MISSING|BLOCKED
closure_evidence: READY|PARTIAL|MISSING|BLOCKED
patient_consent: READY|PARTIAL|MISSING|BLOCKED
clinical_evidence: READY|PARTIAL|MISSING|BLOCKED
rule_governance: READY|PARTIAL|MISSING|BLOCKED
support_model: READY|PARTIAL|MISSING|BLOCKED
measurement_plan: READY|PARTIAL|MISSING|BLOCKED
rollback_plan: READY|PARTIAL|MISSING|BLOCKED
```

### hard blockها

این موارد build یا activation را متوقف می‌کنند:

- patient-facing channel بدون queue و owner؛
- clinical recommendation بدون evidence/rule version؛
- abnormal data collection بدون response boundary؛
- multi-tenant feature بدون isolation test؛
- مالی بدون immutable snapshot/audit؛
- migration بدون reconciliation و rollback؛
- claim بدون measurement plan؛
- pilot بدون incident process.

---

## ۷. Gate A — Problem Evidence

### ورودی لازم

- حداقل سه مرکز مستقل؛
- حداقل دو role در هر مرکز؛
- حداقل ده case واقعی؛
- workflow map؛
- baseline metric؛
- buyer map؛
- current workaround؛
- consequence of failure؛
- reason current tools fail.

### مصاحبه کافی نیست

برای عبور باید حداقل یکی از این‌ها وجود داشته باشد:

- observation مستقیم؛
- log/call list/spreadsheet واقعی؛
- sample de-identified cases؛
- timestampهای فرایند؛
- مالی/عملیاتی قابل تطبیق؛
- audit از موارد رهاشده.

### خروجی

```yaml
decision: GO|ITERATE|NO_GO
problem_statement: "..."
primary_segment: "..."
primary_buyer: "..."
primary_workflow: "..."
baseline:
  volume: null
  delay: null
  drop_rate: null
  rework: null
  staff_time: null
confidence: LOW|MEDIUM|HIGH
open_questions: []
```

---

## ۸. Gate B — Operating Model

### الزام‌ها

- owner هر مرحله؛
- handoff؛
- queue؛
- schedule/coverage؛
- SLA first response؛
- SLA resolution؛
- escalation؛
- waiting state؛
- closure evidence؛
- reopen condition؛
- non-digital fallback؛
- after-hours message؛
- incident owner.

### Role matrix template

| مرحله | پزشک | پرستار/پیگیر | پذیرش | مدیر | بیمار | همراه |
|---|---|---|---|---|---|---|
| detection |  |  |  |  |  |  |
| triage |  |  |  |  |  |  |
| action |  |  |  |  |  |  |
| review |  |  |  |  |  |  |
| response |  |  |  |  |  |  |
| closure |  |  |  |  |  |  |
| escalation |  |  |  |  |  |  |

### No-go patternها

- «هرکس دید انجام دهد»؛
- doctor-only queue بدون protected time؛
- SLA بدون staffing؛
- closure = status done؛
- patient submission = reviewed؛
- emergency language مبهم؛
- تیم فرض کند notification همان response است.

---

## ۹. Gate C — Usability and Comprehension

### participant minimum پیشنهادی برای هر iteration

- ۵ staff از roleهای اصلی؛
- ۵ بیمار؛
- حداقل ۲ سالمند یا فرد کم‌سواد دیجیتال؛
- حداقل ۲ caregiver؛
- یک کاربر keyboard-only یا assistive-technology در برنامهٔ کامل.

این عددها برای کشف مشکل‌اند، نه اثبات آماری.

### taskهای staff

- پیدا کردن loop overdue؛
- assign/reassign؛
- ثبت attempt؛
- waiting state؛
- escalation؛
- افزودن evidence؛
- closure؛
- reopen؛
- توضیح اینکه چه کاری در SLA است.

### taskهای patient/caregiver

- ورود و recovery؛
- فهم «اقدام امروز»؛
- ارسال measurement؛
- فهم status؛
- درخواست refill؛
- تشخیص اینکه برای emergency چه کند؛
- دعوت/لغو caregiver؛
- تشخیص هویت انجام‌دهندهٔ action.

### معیارهای پیشنهادی

- task success ≥ ۸۰٪؛
- critical error = صفر؛
- unsafe misunderstanding = صفر؛
- median path برای action اصلی کوتاه و بدون navigation پیچیده؛
- کاربر next step را با زبان خود توضیح دهد؛
- خطا recoverable باشد؛
- text scaling و mobile layout شکسته نشود.

### Critical error

- اقدام برای بیمار اشتباه؛
- ارسال داده به tenant اشتباه؛
- برداشت اینکه پیام فوراً توسط پزشک دیده می‌شود؛
- برداشت اینکه recommendation دستور درمان قطعی است؛
- caregiver بدون scope به داده دسترسی یابد؛
- closure بدون evidence؛
- emergency به inbox عادی هدایت شود.

---

## ۱۰. Gate D — Feasibility Pilot

### طراحی پیشنهادی

```text
2 clinics minimum
4–8 weeks baseline
4–8 weeks live pilot
limited patient cohort
limited hours and scope
mixed methods
weekly safety review
predefined stop rules
```

مدت و حجم نهایی باید با workflow واقعی تعیین شود.

### implementation outcomes

- acceptability؛
- adoption؛
- appropriateness؛
- feasibility؛
- fidelity؛
- cost؛
- penetration/reach؛
- early sustainment signal.

### service outcomes

- timeliness؛
- safety؛
- efficiency؛
- patient-centeredness؛
- equity؛
- continuity.

### client outcomes

در feasibility pilot، client outcome باید exploratory باشد. claim اثربخشی مجاز نیست.

### thresholdهای اولیه

| Metric | GO hypothesis | Watch | NO_GO signal |
|---|---:|---:|---:|
| loops with owner | ≥۹۰٪ | ۸۰–۸۹٪ | <۸۰٪ |
| first response in SLA | ≥۸۰٪ | ۶۵–۷۹٪ | <۶۵٪ |
| closed loops with complete evidence | ≥۹۰٪ | ۷۵–۸۹٪ | <۷۵٪ |
| invisible/unassigned work | <۵٪ | ۵–۱۰٪ | >۱۰٪ |
| serious safety incident | ۰ | — | ≥۱ attributable event |
| median added documentation | ≤۲ دقیقه/loop | ۲–۴ | >۴ بدون value روشن |
| after-hours activity change | ≤۱۵٪ | ۱۵–۲۵٪ | >۲۵٪ |
| staff weekly adoption | ≥۸۰٪ target users | ۶۰–۷۹٪ | <۶۰٪ |
| workaround outside system | <۱۰٪ | ۱۰–۲۵٪ | >۲۵٪ |

### interpretation

- یک metric سبز برای GO کافی نیست.
- safety hard stop است.
- workload و fidelity باید کنار adoption دیده شوند.
- threshold باید بر اساس complexity stratify شود.

---

## ۱۱. Gate E — Patient Channel

Patient channel فقط پس از Gate D staff loop فعال می‌شود.

### ورودی

- queue و owner live؛
- response hours؛
- status contract؛
- emergency copy؛
- consent/privacy؛
- caregiver model؛
- accessible recovery؛
- fallback channel؛
- capacity admission control.

### thresholdهای اولیه

| Metric | GO hypothesis |
|---|---:|
| دعوت‌شده‌هایی که حداقل یک action کامل می‌کنند | ≥۶۰٪ |
| submission کامل با status روشن | ≥۹۵٪ |
| clinical request بدون owner | ۰ |
| critical privacy/safety error | ۰ |
| caregiver با account مستقل | ≥۹۵٪ caregiver use |
| patient who can explain expected response | ≥۸۰٪ tested users |

### equity review

همهٔ metricها بر اساس این متغیرها، در حد مجاز و اخلاقی، stratify شوند:

- سن؛
- زبان/سواد؛
- device؛
- disability/accessibility need؛
- caregiver availability؛
- location/connectivity؛
- نوع workflow؛
- جنسیت فقط اگر هدف و مجوز روشن باشد.

### No-go

- activation بالا ولی review latency بدتر؛
- caregiver credential sharing؛
- abandonment concentrated در گروه آسیب‌پذیر بدون remediation؛
- بیمار فکر کند ۲۴/۷ monitored است؛
- abnormal submission بدون review؛
- channel جدید باعث حذف fallback شود.

---

## ۱۲. Gate F — Clinical Program and CDS

### artifactهای اجباری

```text
ClinicalProgram
ProgramVersion
EvidencePackage
Population / inclusion / exclusion
MeasurementProtocol
RuleDefinition
RuleVersion
TestManifest
ValidationReport
DeploymentScope
RecommendationInstance
FactSnapshotHash
AlertBudget
RollbackPlan
ClinicalOwner
Reviewer(s)
ReviewDate
```

### lifecycle

```text
draft
→ evidence_review
→ specialist_review
→ medication_safety_review
→ informatics_review
→ test_validated
→ shadow
→ pilot
→ active
→ paused / superseded / retired
```

### shadow gate

- rule version binding = ۱۰۰٪؛
- fact snapshot/provenance = ۱۰۰٪؛
- critical missing data fail closed؛
- sample chart review؛
- fire rate و repeat burden؛
- false-positive pattern؛
- conflict/multimorbidity review؛
- no patient-facing unreviewed recommendation؛
- no treatment automation.

### stop rule

یک serious unsafe recommendation، provenance break یا rule/version mismatch باعث pause فوری scope مربوط می‌شود تا root cause و sign-off جدید.

---

## ۱۳. Gate G — Repeatability

### سؤال

آیا محصولی ساخته شده یا یک پروژهٔ مشاوره‌ای اختصاصی؟

### metricها

- implementation hours/tenant؛
- migration exception rate؛
- number of custom code changes؛
- configuration reuse؛
- training hours/role؛
- support tickets/user؛
- time-to-first-live-loop؛
- time-to-first-patient-action؛
- tenant-specific policy count؛
- onboarding defect count؛
- rollback frequency.

### GO hypothesis

- حداقل دو tenant بعدی بدون fork؛
- زمان راه‌اندازی نزولی؛
- بیش از ۸۰٪ workflow با template + configuration؛
- critical data isolation issue = صفر؛
- migration reconciliation = GO؛
- support burden در مدل قیمت قابل پوشش.

### No-go

- branch اختصاصی برای tenant؛
- shared admin credential؛
- manual data repair بدون ledger؛
- policy در کد پراکنده؛
- tenant isolation قابل آزمون نیست؛
- هر rollout به founder intervention وابسته است.

---

## ۱۴. Gate H — Business Model

### buyer evidence

- buyer name/role؛
- pain budget؛
- procurement path؛
- contract authority؛
- current spend؛
- value recipient؛
- payer of invoice؛
- switching cost؛
- renewal criterion.

### pricing experiments

قیمت باید حداقل این مدل‌ها را مقایسه کند:

- per clinic؛
- per active clinician؛
- per active enrolled patient؛
- module-based؛
- base + usage؛
- implementation fee + subscription.

### metricها

- paid pilot conversion؛
- sales cycle؛
- onboarding revenue/cost؛
- gross margin after support؛
- contribution margin؛
- logo retention؛
- net revenue retention؛
- expansion؛
- receivable risk؛
- discount dependency.

### GO hypothesis

- ۳ از ۵ buyer واجد شرایط paid pilot/LOI مشروط؛
- delivery cost در قیمت پوشش‌پذیر؛
- value به buyer یا contract counterparty می‌رسد؛
- renewal metric پیش از فروش روشن؛
- customization fee جایگزین product discipline نمی‌شود.

### No-go

- فقط علاقهٔ رایگان؛
- buyer و value recipient متفاوت بدون contract alignment؛
- قیمت پایین‌تر از support/staffing؛
- فروش وابسته به claim outcome؛
- تخفیف دائمی برای جبران fit ضعیف؛
- implementation نامحدود در subscription.

---

## ۱۵. Build / Pilot / Defer / Kill Decision Table

| وضعیت | تعریف | اقدام |
|---|---|---|
| BUILD | evidence و dependency کافی؛ scope روشن | PRD، threat model، acceptance criteria، instrumentation |
| PILOT | فرضیه قوی ولی feasibility نامعلوم | محدود، reversible، measured، stop rules |
| ITERATE | signal مثبت ولی gate ناقص | اصلاح workflow/design، نه scale |
| DEFER | value محتمل ولی prerequisite یا economics ناقص | backlog با trigger بازگشت |
| KILL | fit، safety، adoption یا economics رد شده | توقف و ثبت rationale |

### trigger بازگشت برای DEFER

هر defer باید trigger داشته باشد:

```yaml
revisit_when:
  - "Care Loop staff pilot passes Gate D"
  - "Organization/location model is live"
  - "Two clinics request the same workflow"
  - "Clinical evidence package is signed off"
  - "External API becomes stable"
expires_on: "YYYY-MM-DD"
```

بدون trigger، defer به backlog قبرستانی تبدیل می‌شود.

---

## ۱۶. Kill Criteria سخت

بدون رأی‌گیری محصول، این موارد stop هستند:

1. serious preventable safety event منتسب به design؛
2. tenant data leakage؛
3. recommendation بدون provenance/version؛
4. patient channel بدون owner؛
5. credential sharing به‌عنوان flow رسمی؛
6. closure قابل ثبت بدون evidence در workflow حساس؛
7. نیاز به درمان خودکار برای viableشدن مدل؛
8. custom fork شرط تکرار فروش؛
9. عدم امکان export یا audit دادهٔ مشتری؛
10. inability to measure workload/cost؛
11. willingness-to-pay نزدیک صفر پس از discovery کافی؛
12. adoption فقط با حضور دائمی تیم سازنده؛
13. after-hours burden غیرقابل‌کاهش؛
14. benefit فقط با cherry-picked outcome دیده شود؛
15. گروه آسیب‌پذیر به‌طور سیستماتیک حذف شود و fallback ممکن نباشد.

---

## ۱۷. Pilot Review Packet

هر review هفتگی پایلوت باید این بسته را داشته باشد:

```text
1. Cohort and reach
2. Workflow volume and states
3. SLA and backlog
4. Workload and after-hours
5. Safety incidents / near misses
6. Patient/caregiver failures
7. Data completeness and provenance
8. Workarounds and support tickets
9. Costs and staffing
10. Adaptations made
11. Fidelity impact
12. Decision: continue / narrow / pause / stop
```

### adaptation log

```yaml
adaptation_id: ADAPT-NNN
date: YYYY-MM-DD
trigger: "..."
core_function_affected: "..."
form_changed: "..."
reason: "..."
expected_effect: "..."
safety_review: "..."
fidelity_risk: LOW|MEDIUM|HIGH
approved_by: []
result: "..."
```

اصل مهم:

> form می‌تواند با context تغییر کند، ولی core function و safety invariant نباید بی‌صدا تغییر کنند.

---

## ۱۸. Claim Registry

پیش از هر متن فروش، deck یا وب‌سایت:

| Claim | نوع | Evidence level | Population | Context | Caveat | Approved by | Expiry |
|---|---|---|---|---|---|---|---|
|  | capability / workflow / clinical / economic | E0-E6 |  |  |  |  |  |

### claimهای فعلاً مجاز

- حلقه پرونده، عملیات و حسابداری را در یک پلتفرم یکپارچه می‌کند؛ با استناد به runtime واقعی.
- Care Loop برای owner، SLA، evidence و closure طراحی شده است؛ پس از پیاده‌سازی runtime.
- CDS suggestion-only و human-reviewed طراحی می‌شود.
- migration و reconciliation ابزارهای تغییرناپذیر دارند.

### claimهای فعلاً غیرمجاز

- کاهش HbA1c؛
- کاهش فشارخون؛
- کاهش بستری؛
- کاهش هزینه؛
- افزایش درآمد؛
- کاهش workload؛
- superiority نسبت به competitor؛
- safe AI؛
- clinical accuracy؛
- ROI مشخص.

---

## ۱۹. Decision Record Template

```markdown
# STRAT-YYYY-NNN — عنوان

## سؤال

## Segment / workflow / population

## Evidence summary
- E0:
- E1:
- E2:
- E3+:

## Scorecards
- Segment:
- Opportunity:
- Dependency readiness:

## Safety and equity review

## Economics

## Alternatives

## Decision
BUILD | PILOT | ITERATE | DEFER | KILL

## Conditions

## Metrics and stop rules

## Owner

## Review date

## Evidence links
```

---

## ۲۰. اولین Decision Unit پیشنهادی

```yaml
id: STRAT-2026-001
question: >
  آیا staff-owned Care Loop برای post-visit، overdue lab/appointment
  و refill در بیماران بالغ HTN/T2D وارد prototype و سپس پایلوت شود؟
segment: >
  کلینیک تخصصی یا چندتخصصی کوچک تا متوسط با owner اجرایی پیگیری
buyer: "clinic owner / medical director / operations manager"
users:
  - physician
  - nurse_or_followup_role
  - front_desk
patient_population: "adult HTN/T2D, limited-risk pilot cohort"
proposed_outcome: >
  پیگیری مهم بدون owner، SLA، status و closure evidence رها نشود.
decision: "PROCEED_TO_GATE_A"
not_in_scope:
  - 24_7_monitoring
  - automated_titration
  - free_form_chat
  - active_patient_facing_CDS
  - hospital_integration
```

این Decision Unit باید پیش از PRD اجرایی با دادهٔ field research تکمیل شود.

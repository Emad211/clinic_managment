# دور چهارم پژوهش عمیق — مدل عملیاتی چندمستأجره و عمومی‌سازی حسابداری

**تاریخ:** ۲۰۲۶-۰۷-۱۵  
**وضعیت:** Product/Domain Architecture Research؛ نه migration plan نهایی  
**دامنه:** مطب، کلینیک، درمانگاه، چندشعبه، نقش‌ها، برنامه‌ریزی، خدمات، قیمت‌گذاری، صندوق، بیمه، پرداخت، payroll، inventory و مرز ERP

---

## ۱. مسئلهٔ محصول

ماژول حسابداری موجود از یک درمانگاه واقعی و جریان مالی مشخص تکامل یافته است. وفاداری به آن سیستم برای مهاجرت امن ضروری بود، اما همان وفاداری به‌تنهایی محصول را برای همهٔ مراکز درمانی عمومی نمی‌کند.

عمومی‌سازی درست یعنی:

> **هستهٔ مالی و عملیاتی ثابت بماند، اما ساختار سازمان، نقش، خدمت، قیمت، payer، location، workflow و approval به‌صورت داده و policy قابل پیکربندی باشند؛ بدون fork کردن کد برای هر کلینیک.**

عمومی‌سازی غلط یکی از این دو افراط است:

1. شرط‌های متعدد بر اساس `clinic_type` در تمام کد؛
2. workflow builder کاملاً آزاد که محصول را به ERP پیچیده و غیرقابل‌پشتیبانی تبدیل کند.

راه پیشنهادی: **Stable Core + Capability Modules + Opinionated Templates + Tenant Policy**.

---

## ۲. وضعیت واقعی مدل فعلی

### ۲.۱ Tenant فعلی بسیار نازک است

`platform.tenants` در برش پایه فقط این موارد را دارد:

```text
id
name
is_active
created_at
```

هنوز Organization، Location، Department، Room، legal profile، timezone policy، currency display، branding یا operating capabilities مدل نشده‌اند.

### ۲.۲ کاربر و عضویت

`platform.users` یک `tenant_id`، username، role، app و `staff_id` دارد. roleهای فعلی:

```text
admin | manager | reception | doctor | staff
```

این مدل برای tenant واحد و نقش ساده مناسب است، ولی برای این سناریوها کافی نیست:

- یک کاربر در چند شعبه؛
- نقش متفاوت در شعبه‌های مختلف؛
- accountant، cashier، nurse، midwife، technician، care coordinator و auditor؛
- محدودیت دسترسی بر department/location؛
- temporary/locum staff؛
- segregation of duties؛
- provider credentialing و specialty.

### ۲.۳ Staff فعلی

`accounting.medical_staff` فقط `doctor|nurse` را می‌پذیرد. این محدودیت legacy-driven است و برای مراکز عمومی کافی نیست. همچنین staff به location، department، specialty، license، employment arrangement یا effective dates متصل نیست.

### ۲.۴ فاکتور و پرداخت فعلی

فاکتور فعلی:

```text
patient
doctor / nurse
status: open | closed
insurance snapshots
total_amount
work_date
free-text shift
opened/closed actor and timestamps
pricing_version
```

پرداخت فعلی در سطح item ذخیره می‌شود:

```text
invoice_id
item_type
item_id
payment_type
is_paid
```

این مدل مهاجرت وفادار و paid-only close gate محکمی دارد، ولی برای revenue cycle عمومی این کمبودها را دارد:

- receipt/payment transaction مستقل؛
- پرداخت جزئی و چندروش روی یک بدهی؛
- refund و reversal؛
- void/cancel reason؛
- credit note؛
- deposit/prepayment؛
- write-off/discount/adjustment؛
- cashier/cash register/session؛
- settlement batch؛
- payment reference و terminal؛
- payer remittance؛
- balance aging؛
- invoice number policy و location scope.

`open|closed` وضعیت چرخهٔ کامل مالی نیست؛ فقط قرارداد legacy را نشان می‌دهد.

### ۲.۵ خدمت و قیمت‌گذاری

مدل فعلی چند خانوادهٔ جدا دارد:

```text
services
visit_tariffs
nursing_services
injection_types
procedure_tariffs
consumable_tariffs
insurance_nursing_exclusions
```

و چهار item type اصلی:

```text
visit | injection | procedure | consumable
```

این ساختار جریان درمانگاه مبدأ را خوب پوشش می‌دهد، اما برای مراکز دیگر ممکن است به تکثیر خانواده‌های جدول منجر شود. همچنین availability، location، provider eligibility، duration، tax، package، contract، price effective dates و modifierها به شکل عمومی مدل نشده‌اند.

### ۲.۶ بیمه

`insurance_schemes` و `visit_tariffs` پایهٔ خوبی هستند؛ بااین‌حال بخش زیادی از invoice هنوز نام بیمه را به‌صورت historical text snapshot نگه می‌دارد. برای revenue cycle عمومی نیاز به تفکیک این مفاهیم است:

```text
Payer
Plan/Product
Patient Coverage
Provider-Payer Contract
Coverage Rule
Tariff/Price Agreement
Authorization
Claim
Remittance/Denial
```

لازم نیست همهٔ این‌ها در MVP ساخته شوند، ولی مدل فعلی نباید مانع رشد به آن‌ها شود.

### ۲.۷ شیفت و مکان

شیفت عمداً free-text و per-clinic نگه داشته شده است. `shift_staff` نیز `(tenant, work_date, shift)` را به یک doctor/nurse متصل می‌کند. این برای oracle قدیمی درست است؛ ولی در مدل عمومی:

- location وجود ندارد؛
- یک شیفت ممکن است چند provider داشته باشد؛
- room/resource وجود ندارد؛
- schedule template و exception وجود ندارد؛
- role assignment با service line مرتبط نیست؛
- user active shift با cash session یکی نیست.

### ۲.۸ Payroll

تنظیمات فعلی نه ستون ثابت legacy دارد؛ پایه‌های morning/evening/night، fee و چند درصد. این قرارداد برای مرکز مبدأ وفادار است ولی برای همهٔ مراکز عمومی نیست:

- حقوق ثابت ماهانه؛
- hourly/shift rate؛
- per-service commission؛
- tiered commission؛
- provider split؛
- guarantee/minimum؛
- bonus/deduction؛
- effective-dated contract؛
- multi-location attribution؛
- leave/attendance؛
- payroll approval/freeze/reopen.

### ۲.۹ Consumables برابر Inventory نیست

`consumables_ledger` مصرف و هزینهٔ قلم را ثبت می‌کند، ولی inventory system کامل نیست. موجود نیست:

```text
stock item / SKU
warehouse/location
lot/batch
expiry
receipt/procurement
transfer
stock count
adjustment
reorder level
supplier
cost method
```

نباید به‌دلیل وجود مصرفی ادعا شود که inventory کامل داریم.

---

## ۳. مرز محصول: Revenue-Cycle OS، نه ERP کامل در فاز اول

تصمیم پیشنهادی:

> **حلقه در فازهای اولیه «Clinical Operations + Practice Management + Revenue Cycle» است؛ نه دفترکل عمومی، خزانه‌داری، خرید و ERP کامل.**

### داخل مرز اصلی

- patient registration؛
- scheduling و encounter context؛
- service delivery؛
- charge capture؛
- pricing/coverage؛
- invoice؛
- collection/payment/refund؛
- payer receivable در صورت ورود بیمه؛
- cashier reconciliation؛
- provider compensation preview/settlement؛
- operational financial reporting؛
- audit.

### خارج مرز اولیه

- double-entry general ledger جامع؛
- accounts payable عمومی؛
- procurement کامل؛
- fixed assets؛
- bank reconciliation سازمانی؛
- tax filing؛
- consolidated corporate accounting؛
- full HR/payroll statutory engine.

### چرا این مرز مهم است؟

- ارزش متمایز حلقه، بستن care loop است؛ نه رقابت با ERPها.
- revenue cycle مستقیماً به workflow درمان وصل است.
- full ledger نیازمند تخصص حقوقی/مالی، localization و هزینهٔ پشتیبانی مستقل است.
- export استاندارد به نرم‌افزار حسابداری رسمی می‌تواند نیاز اولیه را پوشش دهد.

این مرز باید با مالک و حسابدار رسمی تأیید شود.

---

## ۴. مدل سازمانی هدف

```text
Tenant
└── Organization
    ├── Legal / Billing Profile
    ├── Locations
    │   ├── Departments / Service Lines
    │   ├── Rooms / Resources
    │   ├── Cash Registers
    │   ├── Inventory Points (optional)
    │   └── Schedules / Shifts
    ├── Memberships / Roles
    ├── Clinical Programs
    ├── Service Catalogs
    ├── Pricing and Payer Contracts
    └── Policies / Capabilities
```

### ۴.۱ Tenant

مرز امنیت، قرارداد SaaS، retention و billing حلقه است. tenant لزوماً یک شعبه نیست.

### ۴.۲ Organization

شخص/نهاد عملیاتی یا حقوقی که چند location را اداره می‌کند. در MVP تک‌سازمانی، row می‌تواند ۱:۱ با tenant باشد، ولی این فرض در API و FK hardcode نمی‌شود.

### ۴.۳ Location

محل فیزیکی یا virtual care location:

```text
location_id
organization_id
code
name
address/contact
timezone
active dates
billing profile override
```

تمام موجودیت‌های عملیاتی که attribution مکانی لازم دارند باید `location_id` داشته باشند یا از encounter/shift derive شوند:

- appointment؛
- encounter؛
- invoice؛
- payment؛
- cashier session؛
- service availability؛
- stock movement؛
- staff assignment؛
- reporting.

### ۴.۴ Department / Service Line

نمونه:

```text
غدد
قلب
داخلی
تزریقات
آزمایشگاه
تصویربرداری
پذیرش
```

Department برای access control، schedule، cost attribution و queue routing مفید است؛ نباید با diagnosis یا specialty یکی فرض شود.

### ۴.۵ Room / Resource

برای scheduling عمومی:

```text
room
bed/chair
procedure station
device/resource
telehealth slot
```

### ۴.۶ Membership

```text
user_id
organization_id
location_id nullable
role_definition_id
effective_from / until
status
```

یک user می‌تواند چند membership داشته باشد. role claim تک‌رشته‌ای فعلی در بلندمدت کافی نیست.

---

## ۵. Capability model

`clinic_type` فقط template اولیه است؛ رفتار با capability کنترل می‌شود.

### ۵.۱ Capabilityهای پیشنهادی

```text
patient_registry
appointments
encounters
chronic_care
patient_portal
remote_monitoring
nursing_station
procedures
insurance_pricing
claims
cashier
provider_compensation
inventory_basic
inventory_lot_expiry
multi_location
telehealth
lab_integration
prescription_integration
```

### ۵.۲ قواعد

- capability tenant-scoped و گاهی location-scoped است؛
- feature flag فنی با purchased capability تجاری یکی نیست؛
- خاموش‌کردن capability نباید دادهٔ قبلی را حذف یا export را مسدود کند؛
- clinical safety feature به‌دلیل package مالی خاموش نمی‌شود؛
- dependencyها صریح‌اند، مثلاً claims به payer/contracts نیاز دارد؛
- entitlement و authorization دو لایهٔ جدا هستند.

### ۵.۳ Templateهای onboarding

#### Solo Office

```text
patient_registry
appointments
encounters
simple_invoicing
payments
basic_reports
optional chronic_care
```

#### Specialty Clinic

```text
multi-provider
chronic_care
patient_portal
care coordination
insurance pricing
provider compensation
```

#### Polyclinic / Treatment Center

```text
multi-department
multi-shift
nursing/procedures
cashier sessions
advanced pricing
multi-location optional
inventory optional
```

Template فقط default است؛ بعداً capabilityها قابل تغییرند.

---

## ۶. مدل نقش و مجوز

### ۶.۱ Roleهای دامنه‌ای

به‌جای یک enum کوچک global، role definition با permission bundle:

```text
organization_owner
tenant_admin
clinic_manager
medical_director
physician
nurse
midwife
technician
care_coordinator
receptionist
cashier
accountant
billing_specialist
inventory_manager
auditor
support_operator
```

### ۶.۲ Scope

هر permission با scope ارزیابی می‌شود:

```text
tenant
organization
location
department
assigned_patients
own_encounters
own_cash_session
```

### ۶.۳ Segregation of duties

نمونهٔ policy:

- cashier نمی‌تواند refund خودش را بدون approval نهایی کند؛
- tariff editor نمی‌تواند retroactive price را بدون approval منتشر کند؛
- payroll preparer و approver جدا باشند؛
- clinical staff به مالیات/حساب‌های مدیریتی غیرضروری دسترسی نداشته باشند؛
- accountant به notes بالینی minimum-necessary دسترسی دارد؛
- support access با reason، زمان محدود و audit باشد.

---

## ۷. Service Catalog عمومی

### ۷.۱ ServiceDefinition

```text
service_key
name
category
clinical/nonclinical
standard duration
unit
active dates
required capability
```

Category extensible است، نه CHECK ثابت چهارمقداری در تمام آینده:

```text
consultation
nursing
procedure
consumable
diagnostic
laboratory
imaging
telehealth
care_program
administrative
```

legacy item typeها در anti-corruption layer باقی می‌مانند.

### ۷.۲ ServiceOffering

یک service در location/provider خاص:

```text
service_id
location_id
department_id
provider_role/specific provider
duration
booking rules
availability
```

### ۷.۳ PriceBook و PriceVersion

```text
PriceBook
  scope: tenant/location/payer/private

PriceVersion
  effective_from/until
  currency_unit
  approval status
  manifest/version

PriceLine
  service
  base amount
  patient/payer split rules
  modifiers
```

قیمت historical همیشه snapshot می‌شود؛ تغییر price book فاکتور بسته را بازتفسیر نمی‌کند. `pricing_version` فعلی یک invariant درست است و باید به مدل versioned عمومی ارتقا یابد.

### ۷.۴ Package/Membership

بازار practice management، package و membership را baseline کرده است. اما در حلقه باید با اخلاق مراقبت تفکیک شود:

- package مالی مجموعه‌ای از entitlement خدمات است؛
- CarePlan بالینی نیست؛
- اتمام package نباید red-flag یا مراقبت ضروری را پنهان کند؛
- استفاده، expiry، refund و transfer policy نسخه‌دار است.

---

## ۸. Invoice و Charge Architecture

### ۸.۱ تفکیک Charge از Invoice

```text
Service Event / Charge Capture
→ Charge
→ Pricing Snapshot
→ Invoice Line
→ Invoice
→ Payment Allocation / Payer Allocation
```

در مدل legacy، visit/injection/procedure/consumable هم event و هم line مالی‌اند. برای عمومی‌شدن باید event بالینی/عملیاتی از line مالی قابل تفکیک باشد؛ هر service event ممکن است:

- رایگان؛
- package-covered؛
- payer-covered؛
- patient-paid؛
- no-charge documented؛
- bundled با خدمت دیگر باشد.

### ۸.۲ Invoice state machine پیشنهادی

```text
draft
→ issued/open
→ partially_paid
→ paid
→ finalized
→ voided
→ refunded / partially_refunded
```

این stateها باید با قوانین ایران و workflow واقعی تطبیق داده شوند. در گذار از legacy:

```text
open   → issued/open
closed → finalized یا paid/finalized بر اساس evidence پرداخت
```

### ۸.۳ Immutable financial history

پس از finalization:

- line حذف/ویرایش مستقیم ممنوع؛
- correction با adjustment/credit note/reversal؛
- actor، reason و reference اجباری؛
- snapshot payer/price/tax حفظ می‌شود؛
- report دورهٔ بسته تغییر نمی‌کند مگر reopen کنترل‌شده.

---

## ۹. Payment، صندوق و تسویه

### ۹.۱ Payment Transaction

```text
payment_id
invoice/patient/account context
amount
method
status
received_at
location
cash_register
cashier_session
external reference
received_by
```

### ۹.۲ Payment Allocation

یک payment می‌تواند به چند invoice/line تخصیص یابد و یک invoice چند payment داشته باشد.

```text
payment_id
invoice_id
invoice_line_id optional
amount
```

### ۹.۳ Methodها

Method catalog tenant-scoped:

```text
cash
card terminal
bank transfer
online gateway
wallet/deposit
base insurance
supplementary insurance
organization contract
```

`PAYMENT_TYPES` ثابت فعلی باید برای migration contract حفظ شود، ولی runtime عمومی به catalog/policy نیاز دارد.

### ۹.۴ Refund/Reversal

- original payment reference؛
- amount؛
- reason؛
- approver؛
- method؛
- status؛
- no destructive delete.

### ۹.۵ Cash Register و Cashier Session

```text
CashRegister(location)
CashierSession
  opened_by / opening_balance
  opened_at
  closed_by / closing_count
  expected / actual / variance
  approval
```

این مفهوم از `user_active_shift` جداست. شیفت کاربر با مسئولیت صندوق یکی نیست.

---

## ۱۰. Payer و Insurance roadmap

### Level 0 — Snapshot pricing

وضع موجود: نام بیمه و قیمت snapshot؛ مناسب برای migration.

### Level 1 — Plan and coverage

```text
Payer
InsurancePlan
PatientCoverage
Contract
PriceBook
CoverageRule
```

### Level 2 — Eligibility/authorization

- eligibility check؛
- authorization requirement؛
- referral/prerequisite؛
- coverage date؛
- documentation checklist.

### Level 3 — Claim lifecycle

```text
draft
submitted
accepted
rejected
denied
partially_paid
paid
appealed
closed
```

### Level 4 — Remittance and denial analytics

فقط اگر بازار و integration واقعی این scope را توجیه کند.

اصل: نام بیمه free-text به‌عنوان snapshot باقی می‌ماند، ولی عملیات جدید با IDs و versionهای معتبر انجام می‌شود.

---

## ۱۱. Staff و Provider Compensation

### ۱۱.۱ Person، Membership و Provider Profile

```text
Person/User Identity
OrganizationMembership
ClinicalProviderProfile
Employment/Contract
CompensationPlan
```

staff type ثابت doctor/nurse به role/profile extensible تبدیل می‌شود.

### ۱۱.۲ Compensation Plan

```text
plan version
effective dates
scope: staff/location/service
components:
  fixed
  per shift
  hourly
  per visit
  percentage of collected charge
  per procedure
  bonus
  deduction/tax
eligibility and caps
```

### ۱۱.۳ Calculation lifecycle

```text
preview
→ calculated
→ reviewed
→ approved
→ locked
→ exported/paid externally
→ corrected by adjustment
```

حلقه در ابتدا compensation statement و export تولید می‌کند، نه payroll statutory کامل.

### ۱۱.۴ مبنای محاسبه

باید مشخص باشد درصد بر چه چیزی است:

```text
charge
gross invoice
patient collected
payer expected
payer collected
service-specific amount
```

فرمول legacy نباید silently برای کلینیک جدید default شود.

---

## ۱۲. Scheduling و Shift

### ۱۲.۱ Schedule primitives

```text
Provider availability
Location hours
Room/resource availability
Service duration
Appointment type
Shift template
Exception/holiday
Capacity and overbooking policy
```

### ۱۲.۲ Shift

شیفت یک تعریف tenant/location است:

```text
shift_definition
start/end local time
cross-midnight policy
roles needed
location
active dates
```

Assignment چندنفره:

```text
shift_instance
staff_assignment
role_in_shift
```

`shift_staff` legacy به یک projection/adapter تبدیل می‌شود، نه مدل نهایی.

### ۱۲.۳ Appointment و financial context

appointment، encounter و invoice می‌توانند location/department/provider/shift snapshot داشته باشند ولی نباید به‌صورت غیرضروری duplicate و متناقض شوند. source-of-truth هر context باید در ADR مشخص شود.

---

## ۱۳. Inventory به‌صورت capability اختیاری

### Basic Inventory

- item catalog؛
- stock point؛
- on-hand quantity؛
- receive/use/adjust؛
- service-consumption link.

### Clinical Inventory Advanced

- lot/batch؛
- expiry؛
- supplier؛
- recall؛
- cold-chain note؛
- transfer؛
- cycle count.

### تصمیم rollout

- برای مطب ساده خاموش؛
- برای درمانگاه تزریقات/مصرفی basic؛
- lot/expiry فقط وقتی workflow و مسئول واقعی وجود دارد؛
- `consumables_ledger` تاریخچه مصرف می‌ماند و با stock movement link می‌شود.

---

## ۱۴. Configuration hierarchy

```text
Global safe defaults
→ Tenant policy
→ Organization override
→ Location override
→ Department override
→ User preference (presentation only)
```

### قواعد inheritance

- effective policy همیشه قابل نمایش است؛
- source هر value مشخص است؛
- override با effective date؛
- clinical knowledge از این hierarchy جداست؛
- null به معنی inherit و explicit off معنای جدا دارد؛
- تغییر policy audit و impact preview دارد.

`accounting.settings` key/value برای legacy و secret مناسب است، ولی policyهای مهم باید typed table/schema داشته باشند؛ key-value آزاد source of truth دامنه‌ای نمی‌شود.

---

## ۱۵. ماتریس سه archetype

| قابلیت | مطب تک‌پزشک | کلینیک تخصصی | درمانگاه چندشیفت |
|---|---|---|---|
| Location | ۱، پنهان در UX | ۱ یا چند | معمولاً چند department/shift |
| Staff | پزشک + منشی | چند provider + care team | پزشک/پرستار/تکنسین/پذیرش/صندوق |
| Schedule | ساده | provider/service-based | room/resource/shift-based |
| Billing | نقد/کارت، تعرفه ساده | بیمه/قرارداد/بسته ممکن | چند خدمت، صندوق و payer پیچیده |
| Payroll | ساده/خارج سیستم | commission/statement | shift + service + approval |
| Inventory | معمولاً خاموش | اختیاری | basic یا lot/expiry |
| Chronic care | اختیاری | core | program-specific |
| Patient portal | booking/plan | core care loop | چند department، routing مهم |
| Reporting | درآمد و نوبت | program + provider | location/shift/service/cashier |
| Onboarding | self/assisted کوتاه | assisted template | implementation project |

UI نباید همهٔ complexity درمانگاه را به مطب نشان دهد. Progressive capability disclosure ضروری است.

---

## ۱۶. UX مرکز درمانی

### ۱۶.۱ Workspace role-based

- پذیرش: صف، نوبت، ثبت بیمار، مبلغ قابل وصول؛
- cashier: بدهی، payment، receipt، session؛
- clinician: care/encounter، نه جزئیات حسابداری غیرضروری؛
- nurse/technician: work queue و service capture؛
- accountant: reconciliation، payer، aging، audit؛
- manager: capacity، quality، revenue، payroll preview؛
- owner: organization/location performance و configuration.

### ۱۶.۲ Context switch ایمن

در چندشعبه:

- location فعال همیشه واضح؛
- تغییر location نیازمند تأیید در writeهای مالی؛
- query/report scope نمایش داده شود؛
- رنگ تنها علامت location نیست؛
- user فقط locationهای membership خود را می‌بیند؛
- deep link context را امن resolve می‌کند، نه از client trust.

### ۱۶.۳ Setup UX

Onboarding به‌جای صفحهٔ بزرگ settings:

```text
نوع مرکز و template
→ سازمان و محل
→ کاربران و نقش‌ها
→ خدمات
→ قیمت/بیمه
→ روش پرداخت/صندوق
→ schedule/shift
→ برنامه‌های بالینی
→ import/reconciliation
→ go-live checklist
```

هر مرحله preview و امکان later دارد؛ ولی safety/financial mandatory fields fail-closed هستند.

---

## ۱۷. Multi-tenant isolation فراتر از RLS

RLS برای rowهای PostgreSQL ضروری است، اما leakage می‌تواند در این سطوح رخ دهد:

```text
background jobs
scheduler queues
cache keys
object storage
exports/reports
search index
analytics warehouse
logs/traces
email/SMS/push routing
payment callbacks
integration credentials
support tools
backup/restore
```

### قرارداد isolation

- tenant context explicit در message/job payload؛
- worker قبل از query GUC را set و پس از job clear می‌کند؛
- cache key با tenant prefix؛
- object path با opaque tenant namespace؛
- export دارای tenant manifest؛
- webhook mapping با secret/account binding؛
- no PHI در observability default؛
- tenant restore rehearsal؛
- support access break-glass؛
- adversarial tests برای every surface.

### Location isolation

Location معمولاً security boundary کامل نیست، اما بعضی tenantها نیاز دارند. permission layer باید location-scope را enforce کند؛ RLS می‌تواند tenant-level بماند و application/DB policy تکمیلی location را کنترل کند.

---

## ۱۸. Integration architecture

Adapterها بر اساس capability:

```text
insurance / prescription portals
payment gateways / terminals
SMS / push
laboratory
imaging
device/RPM
accounting export
identity/KYC
calendar
```

### قرارداد integration

- tenant-specific credentials encrypted؛
- provider account/location binding؛
- idempotency؛
- external reference؛
- retry/dead-letter؛
- reconciliation؛
- sandbox/mock؛
- consent/purpose؛
- outage fallback؛
- audit.

Integration نباید domain table را مستقیماً mutate کند؛ از command/service و anti-corruption layer عبور می‌کند.

---

## ۱۹. Reporting model

ابعاد حداقل:

```text
tenant
organization
location
department
service
provider
payer
payment method
cash register
shift
date/time
care program
```

Metricها:

- charge، patient liability، payer liability؛
- collected، refunded، outstanding؛
- invoice count/status؛
- service volume؛
- provider compensation basis؛
- cash variance؛
- appointment/no-show؛
- care-loop completion؛
- workload/SLA.

### اصول

- financial definitions versioned؛
- report period timezone/location aware؛
- closed period reproducible؛
- NULL با صفر فرق دارد؛
- raw export و metric dictionary؛
- manager dashboard با drill-down و scope visible؛
- هیچ claim causal از correlation درآمد/پیگیری.

---

## ۲۰. Packaging و مدل تجاری

### گزینهٔ پیشنهادی

قیمت‌گذاری ساده بر پایهٔ organization + active clinical seats، با moduleهای محدود؛ نه قیمت‌گذاری بسیار ریز بر هر feature.

```text
Core Practice
Chronic Care
Advanced Finance/Payer
Multi-location
Inventory
Patient Engagement / Messaging pass-through
```

### Guardrailها

- export و backup حق مشتری است؛
- clinical safety و audit paywall نمی‌شود؛
- patient access پایه گروگان package گران نیست؛
- SMS/device/external هزینهٔ pass-through شفاف؛
- active patient تعریف دقیق و قابل audit؛
- pilot conversion trigger از ابتدا مشخص؛
- pricing نیازمند تحقیق میدانی ایران است، عدد این دور تولید نمی‌شود.

---

## ۲۱. Capability baseline بازار

صفحات رسمی رقبا نشان می‌دهند baseline practice-management امروز فقط invoice نیست:

- Cliniko زمان‌بندی، پرونده، invoices/payments/expenses/taxes، گزارش، چند location، export و API را در یک محصول practice management عرضه می‌کند ([Cliniko Features](https://www.cliniko.com/features/)).
- Jane scheduling با staff/room/resource، documentation، intake، reporting، integrated payments، billing/insurance، invoices، packages/memberships، patient app، secure messaging، integrations و onboarding را کنار هم قرار می‌دهد ([Jane Features](https://jane.app/features)).

این صفحات اثربخشی یا برتری را ثابت نمی‌کنند، اما expectation خریدار را نشان می‌دهند: **تنظیم سریع، workflow یکپارچه، multi-location، patient experience و support بخشی از محصول‌اند.**

تمایز حلقه نباید تقلید تمام breadth رقبا باشد؛ باید practice operations کافی را با عمق مراقبت مزمن ترکیب کند.

---

## ۲۲. Gap map اولویت‌دار

### P0 — تصمیم‌های دامنه‌ای

1. مرز revenue cycle در برابر general ledger؛
2. Tenant/Organization/Location model؛
3. membership و authorization scope؛
4. service catalog و price version model؛
5. invoice/payment/refund state machine؛
6. cashier session؛
7. provider compensation boundary؛
8. payer roadmap؛
9. capability/entitlement contract؛
10. migration strategy برای legacy tables.

### P1 — عمومی‌سازی عملیاتی

1. organization/location؛
2. generalized staff role/membership؛
3. service offering + price book؛
4. payment transaction/allocation؛
5. invoice correction/void/refund؛
6. cash register/session؛
7. multi-location context UI؛
8. onboarding template؛
9. typed policy/configuration؛
10. reporting dimensions.

### P2 — توسعه بازار

1. payer contract/coverage؛
2. package/membership؛
3. compensation plan versioning؛
4. inventory basic؛
5. integrations framework؛
6. data export to external accounting؛
7. multi-organization enterprise؛
8. claims lifecycle در صورت اثبات نیاز.

---

## ۲۳. Migration strategy

اصل Evolve-not-Rewrite حفظ می‌شود.

### Strangler layers

```text
Legacy-compatible tables and APIs
→ canonical services/projections
→ new generalized entities
→ dual-write only through controlled service if required
→ backfill + reconciliation
→ switch read model
→ retire adapter, not history
```

### مثال

- `medical_staff` rows به ProviderProfile/Membership map می‌شوند؛ legacy IDs حفظ می‌شوند.
- `services/nursing/procedure/consumable` به ServiceDefinition/Offering map می‌شوند؛ item family history دست‌نخورده می‌ماند.
- item payment legacy به financial projection map می‌شود؛ payment transaction جدید برای writes آینده فعال می‌شود.
- invoice open/closed به canonical state mapping می‌شود؛ legacy rowها با pricing version قدیمی mutate نمی‌شوند.
- free-text shift به ShiftDefinition با mapping table مهاجرت می‌کند؛ unknown value conflict report دارد.

هر cutover نیازمند replay/idempotency، money reconciliation و rollback است.

---

## ۲۴. Acceptance criteria منتخب

### Location safety

```text
Given کاربر فقط عضو شعبه A است
When invoice شعبه B را با ID مستقیم درخواست می‌کند
Then پاسخ generic not-found/forbidden مطابق policy است
And هیچ دادهٔ شعبه B در search/export/cache دیده نمی‌شود
```

### Price immutability

```text
Given invoice با PriceVersion V1 نهایی شده است
When V2 منتشر می‌شود
Then lineهای invoice قبلی تغییر نمی‌کنند
And گزارش دورهٔ قبل همان digest را دارد
```

### Split payment

```text
Given invoice مبلغ ۱۰۰ دارد
When ۳۰ نقد و ۷۰ کارت دریافت می‌شود
Then دو PaymentTransaction و allocationهای مجموع ۱۰۰ ثبت می‌شوند
And invoice paid می‌شود
And حذف destructive هیچ payment مجاز نیست
```

### Refund approval

```text
Given cashier یک refund ایجاد می‌کند
When policy approval لازم دارد
Then refund pending می‌ماند
And همان cashier نمی‌تواند آن را نهایی کند
And پس از approval، reversal و audit به original payment متصل‌اند
```

### Capability UX

```text
Given tenant مطب ساده inventory ندارد
Then navigation و setup مربوط به inventory نمایش داده نمی‌شود
But historical/export contracts و schema safety شکسته نمی‌شوند
```

### Multi-location report

```text
Given manager هر دو location را دارد
When report scope=all locations است
Then totals با breakdown قابل تطبیق‌اند
And timezone/date boundary و currency unit نمایش داده می‌شوند
```

### Payroll reproducibility

```text
Given compensation period locked شده است
When plan جدید منتشر می‌شود
Then statement دوره قبلی تغییر نمی‌کند
And correction با adjustment و approval انجام می‌شود
```

---

## ۲۵. آزمایش‌های میدانی لازم

1. مصاحبه با سه archetype واقعی؛
2. مشاهدهٔ یک روز پذیرش/صندوق در درمانگاه؛
3. mapping نقش و approval؛
4. بررسی refund/void/discount واقعی؛
5. بررسی قراردادهای بیمه و settlement؛
6. payroll workshop با حسابدار؛
7. service catalog card sort؛
8. چندشعبه: context switching و گزارش؛
9. onboarding test بدون کمک توسعه‌دهنده؛
10. willingness-to-pay و packaging interview.

بدون این تحقیق، complexity مالی ممکن است بیش‌ساخته یا ناقص ساخته شود.

---

## ۲۶. تصمیم‌های موقت دور چهارم

1. `tenant` با clinic/location یکی فرض نمی‌شود.
2. Organization و Location به مدل هدف اضافه می‌شوند.
3. behavior بر capability است، نه `clinic_type` branching.
4. حلقه در فاز اول Revenue-Cycle OS است، نه ERP/general ledger کامل.
5. فاکتور، charge، payment و allocation از هم تفکیک می‌شوند.
6. refund/void/correction append-only و audit‌شده‌اند.
7. Cashier Session از User Shift جداست.
8. Service Catalog به definition/offering/price version تکامل می‌یابد.
9. staff role enum ثابت doctor/nurse به membership/profile extensible تبدیل می‌شود.
10. payroll فعلی legacy-compatible می‌ماند؛ CompensationPlan versioned مسیر آینده است.
11. inventory capability اختیاری است؛ consumables ledger مساوی inventory نیست.
12. clinical knowledge از tenant operational configuration جدا می‌ماند.
13. multi-location و support/admin access باید علاوه بر RLS threat-model شوند.
14. templateهای مطب/کلینیک/درمانگاه onboarding default هستند، نه fork محصول.

---

## ۲۷. موضوع دور پنجم

دور بعد باید یافته‌های چهار دور را به یک **Strategy-to-Roadmap Decision System** تبدیل کند:

- product pillars؛
- ICP و wedge اولیه؛
- capability/competitor matrix؛
- dependency graph؛
- risk-adjusted sequencing؛
- research gates؛
- ۱۲ تا ۱۸ ماه roadmap با outcome و kill criteria؛
- اینکه کدام بخش از PR #10 باید merge شود و کدام research branch باقی بماند.

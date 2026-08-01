# وضعیت حاکم پروژه — Clinic Management

> **این فایل Source of Truth مدیریتی مخزن است.**
>
> هر توسعه، پژوهش، آزمایش Shadow، انتشار یا مهاجرت باید پیش از شروع با این سند تطبیق داده شود. در صورت تعارض میان متن گفتگو، PR قدیمی یا حافظهٔ ایجنت با این فایل و وضعیت واقعی GitHub، ابتدا وضعیت مخزن بررسی و سپس این سند به‌روزرسانی می‌شود.

- آخرین ممیزی: `2026-08-01`
- شاخهٔ محصول مرجع: `main`
- head مرجع هنگام ممیزی: `075ddaa574c5c8b99b6d7b93c775823e6b00e3dc`
- وضعیت کلی: `PRODUCT_OPERATIONAL / CLINICAL_CONTENT_NOT_APPROVED / GOVERNANCE_RECONCILIATION_REQUIRED`

## 1. تعریف دقیق پروژه

این مخزن فقط پروژهٔ پژوهش Rule نیست. Monorepo شامل دو برنامهٔ مستقل عملیاتی و چند جریان توسعهٔ جداست:

1. `webapp/` — حسابداری مطب، Flask + SQLite، پورت 8080؛
2. `specialist_clinic/` — مدیریت بیماری مزمن، پرونده، نوبت، Worklist، پیامک، داشبورد و موتور بالینی suggestion-only، پورت 8090؛
3. Clinical Engine v2 — زیرساخت Fact، Rule package، audit، validation، dual review، activation seal و rollback؛
4. Clinical Rule Research — پژوهش شواهد برای بازسازی Rule Library؛
5. Experimental Shadow Workflows — آزمایش‌های داخلی غیرتجویزی؛
6. Release Engineering — ساخت و استقرار Windows/local/LAN؛
7. Halqe Migration — مهاجرت بلندمدت و مستقل به PostgreSQL/Next.js.

این جریان‌ها **نباید به‌جای یکدیگر تفسیر شوند**.

## 2. ماتریس مرجع جریان‌ها

| جریان | مرجع | وضعیت | اختیار | ممنوعیت فعلی |
|---|---|---|---|---|
| محصول عملیاتی | `main` | `ACTIVE_PRODUCT` | رفتار واقعی برنامه و قراردادهای فعلی | تغییر بالینی بدون گیت مستقل |
| موتور بالینی v2 | کد و تست‌های `main` | `INFRASTRUCTURE_IMPLEMENTED / ACTIVATION_GATED` | اجرای deterministic، audit و lifecycle | فعال‌سازی بدون seal و review واقعی |
| بستهٔ Rule موجود | `2026.1-draft.3` روی `main` | `LEGACY_DRAFT_QUARANTINED` | فقط artifact پیش‌نویس و تست فنی | clinical use، activation یا ادعای approval |
| پژوهش ADA جدید | PR #60 / `research/ada-2026-evidence-v0.2` | `EVIDENCE_AUTHORITY_DRAFT / FROZEN_V0_9_4` | شواهد و مبنای replacement آینده | تلقی به‌عنوان وضعیت کل محصول یا Runtime authority |
| Hypoglycemia Shadow | PRهای #62 تا #67 روی `main` | `EXPERIMENTAL_INTERNAL_SHADOW / PAUSED_FOR_RECONCILIATION` | ثبت Candidate، داوری انسانی و Review داخلی | معرفی به‌عنوان Rule معتبر، rollout بالینی یا گسترش Scope |
| Shadow disposition | `feature/hypoglycemia-shadow-disposition-v1` | `PAUSED_DO_NOT_MERGE` | هیچ؛ فقط work-in-progress حفظ‌شده | PR، merge یا توسعه تا تصمیم reconciliation |
| Release A15 | PR #59 | `STALE_DIVERGED_DRAFT` | مرجع نیازهای release engineering | merge مستقیم روی main فعلی |
| Halqe migration | PRهای Draft قدیمی | `SEPARATE_STRATEGIC_STREAM` | طراحی و rehearsal مهاجرت | تلقی به‌عنوان مسیر فعال محصول فعلی یا cutover خودکار |

## 3. وضعیت محصول عملیاتی

### 3.1 حسابداری

- برنامهٔ مستقل production؛
- دیتابیس `clinic_new.db`؛
- مطب تخصصی فقط از طریق SQLite `mode=ro` آن را می‌خواند؛
- هیچ Write از Specialist Clinic به حسابداری مجاز نیست.

### 3.2 مطب تخصصی

قابلیت‌های اصلی موجود:

- اتصال و ثبت بیمار؛
- پروندهٔ طولی بیماری‌های مزمن؛
- دارو، آلرژی، آزمایش و علائم حیاتی؛
- نوبت و Doctor Queue؛
- Encounter documentation امضاشده و append-only؛
- Plan commitment و Worklist؛
- پیامک، رضایت، تحویل، کمپین و attribution؛
- پل مالی read-only و reconciliation؛
- داشبورد و Control Room؛
- Clinical Engine v2 با حالت suggestion-only و گیت فعال‌سازی.

نتیجه: پروژه در سطح محصول **بسیار جلو رفته و قابل اجراست**؛ ناتمامی اصلی در Clinical Content approval، release engineering نهایی و reconciliation جریان‌هاست.

## 4. وضعیت موتور بالینی v2

زیرساخت موتور ساخته شده است:

- Factهای canonical، time-aware، source-aware و verification-aware؛
- Rule package و schemaهای versioned؛
- Golden Case validation؛
- append-only run/recommendation/decision/task records؛
- dual independent clinical/technical review؛
- content-bound hashes؛
- activation seal، selected rollout و rollback؛
- fail-closed current rollout contract.

این وضعیت به معنی معتبر بودن محتوای Ruleها نیست.

```text
Engine infrastructure = IMPLEMENTED
Clinical rule approval = NOT COMPLETED
Visible clinical activation = BLOCKED
```

## 5. Ruleهای موجود روی main

بستهٔ `2026.1-draft.3` شش Rule دارد:

- `T2-REDFLAG-BP`
- `T2-SAFE-MET-STOP`
- `T2-SAFE-MET-REVIEW`
- `T2-MON-A1C-DUE`
- `T2-MON-EGFR-DUE`
- `T2-MON-UACR-DUE`

Manifest فعلی:

```text
status       = DRAFT
clinical_use = NOT_APPROVED
```

از این پس این بسته رسماً به‌عنوان زیر طبقه‌بندی می‌شود:

```text
LEGACY_DRAFT_QUARANTINED
```

معنای این وضعیت:

- حذف نشده و برای provenance و تست فنی حفظ می‌شود؛
- هیچ‌کدام clinical approval واقعی ندارند؛
- پژوهش جدید به‌طور خودکار آن‌ها را supersede نکرده است؛
- هر Rule باید در reconciliation آینده یکی از تصمیم‌های `REVALIDATE / REPLACE / RETIRE` را بگیرد؛
- تا آن زمان نباید به SILENT، selected rollout یا visible activation برسد.

## 6. پژوهش بازسازی Rule Library

PR #60 فقط **Evidence Authority آینده** است، نه Source of Truth کل پروژه.

وضعیت فریز v0.9.4:

- Rule Candidate جدید: 0
- Accepted Rule جدید: 0
- Licensing: HOLD
- Clinical activation: BLOCKED
- Runtime/UI changes در خود PR: 0

پژوهش ADA 6.19 به دلیل بازده نزولی در v0.9.4 فریز است. ادامهٔ پژوهش فقط زمانی مجاز است که یکی از شرایط زیر برقرار باشد:

1. منبع جدید بتواند تصمیم موجود را تغییر دهد؛
2. یک Rule Candidate محدود و مشخص به شواهد تکمیلی نیاز داشته باشد؛
3. اختلاف مهمی برای approval یا retirement یک Rule وجود داشته باشد.

پژوهش نامحدود و نسخه‌سازی بدون خروجی تصمیمی ممنوع است.

## 7. Hypoglycemia Shadow

PRهای #62 تا #67 قابلیت‌های زیر را به `main` افزوده‌اند:

- ledger append-only رخداد و Review؛
- observability داخلی؛
- monitor manager-only؛
- ساخت Candidate موقت برای FBS کمتر از 54 mg/dL؛
- داوری انسانی `CONFIRMED / REJECTED / CONFLICT`؛
- بازکردن صریح Review توسط کاربر مجاز.

مرز فعلی:

- Clinical Rule نیست؛
- Rule Candidate پژوهشی نیست؛
- medication action یا recommendation ندارد؛
- Task، Alert، prescription، referral یا patient message خودکار ندارد؛
- rollout بالینی تأییدشده نیست.

طبقه‌بندی رسمی:

```text
EXPERIMENTAL_INTERNAL_SHADOW
PAUSED_FOR_RECONCILIATION
```

تا بسته‌شدن reconciliation موارد زیر ممنوع‌اند:

- توسعهٔ disposition UI؛
- افزودن Task/SLA/Alert؛
- اتصال به medication logic؛
- معرفی به‌عنوان اجرای Recommendation 6.19؛
- rollout برای استفادهٔ بالینی واقعی.

کد فعلی فوراً Revert نمی‌شود؛ ابتدا باید در یک تصمیم رسمی یکی از وضعیت‌های زیر را بگیرد:

```text
KEEP_AS_DATA_QUALITY_WORKFLOW
REWORK_TO_MATCH_APPROVED_CONTRACT
REVERT_FROM_PRODUCT
```

## 8. Release Engineering

PR #59 برای A15 روی head قدیمی ساخته شده و نسبت به `main` فعلی diverged است. این PR نباید مستقیم merge شود.

مسیر صحیح:

1. استخراج requirementهای معتبر A15؛
2. ساخت branch تازه از `main` فعلی؛
3. اعمال minimal release changes بدون finalizer موقت در محصول؛
4. full Linux Specialist/Accounting CI؛
5. Windows frozen build و self-test واقعی؛
6. backup/verify/restore rehearsal؛
7. فقط سپس merge.

## 9. Halqe Migration

PRهای مهاجرت Halqe یک جریان استراتژیک جدا هستند. آن‌ها وضعیت محصول فعلی Specialist Clinic را تعریف نمی‌کنند.

تا تصمیم رسمی cutover:

- Flask/SQLite فعلی product authority است؛
- Halqe migration PRها Draft باقی می‌مانند؛
- هیچ merge زنجیره‌ای یا production import خودکار انجام نمی‌شود؛
- تصمیم مهاجرت باید شامل rehearsal، clinician sign-off، financial sign-off، backup/restore و rollback باشد.

## 10. قانون Source of Truth

برای پاسخ به «الان پروژه کجاست؟» ترتیب اعتماد چنین است:

1. وضعیت واقعی `main` و PRهای GitHub؛
2. این فایل و `PROJECT_STATE.json`؛
3. README و اسناد نزدیک به کد؛
4. PR bodyها و گزارش‌های تاریخی؛
5. متن گفتگو یا حافظهٔ ایجنت.

هیچ ایجنتی نباید فقط از حافظه دربارهٔ وضعیت پروژه نتیجه‌گیری کند.

## 11. گاردریل ضد Over-research و Scope drift

پیش از هر tranche باید پنج سؤال پاسخ داده شود:

1. این کار متعلق به کدام جریان است؟
2. خروجی اجرایی یا تصمیمی آن چیست؟
3. آیا نتیجه می‌تواند وضعیت یا تصمیمی را تغییر دهد؟
4. آیا Scope متناسب با ریسک خروجی است؟
5. آیا این سند بعد از merge نیاز به به‌روزرسانی دارد؟

قواعد:

- پژوهش جدید بدون decision impact شروع نمی‌شود؛
- Shadow بدون approval به Rule تبدیل نمی‌شود؛
- تست فنی معادل clinical approval نیست؛
- Rule Draft وارد visible rollout نمی‌شود؛
- یک Conflict فقط capability وابسته به خودش را Block می‌کند؛
- هر tranche باید کوچک، قابل تست و دارای exit criterion باشد؛
- هیچ feature branch نیمه‌کاره‌ای مسیر بعدی پروژه را تعیین نمی‌کند.

## 12. ترتیب صحیح ادامهٔ پروژه

### Phase R0 — Reconciliation حاکمیتی

1. merge همین سند؛
2. توقف `feature/hypoglycemia-shadow-disposition-v1`؛
3. ساخت جدول تصمیم برای شش Rule A12: `REVALIDATE / REPLACE / RETIRE`؛
4. تصمیم رسمی دربارهٔ Hypoglycemia Shadow: keep/rework/revert؛
5. تعیین اینکه PR #60 چگونه و در چه واحدهایی به Rule Candidate تبدیل می‌شود.

### Phase R1 — Release baseline

1. بازسازی A15 از `main` فعلی؛
2. build و self-test Windows؛
3. backup/restore rehearsal؛
4. انتشار یک baseline قابل نصب و بازتولید.

### Phase R2 — Clinical content

1. Ruleها به‌صورت تک‌واحدی و محدود؛
2. evidence → computability → Rule Candidate → Golden Cases؛
3. independent clinical/technical review؛
4. SILENT و سپس pilot محدود؛
5. هیچ activation جمعی یا خودکار.

## 13. تصمیم فعلی

تا تکمیل Phase R0:

```text
New clinical research        = PAUSED except decision-changing retrieval
New clinical rules           = PAUSED
Hypoglycemia Shadow expansion= PAUSED
Disposition branch           = DO_NOT_MERGE
Release cleanup              = ALLOWED after governance merge
Bug/security fixes           = ALLOWED with focused tests
```

این توقف به معنی توقف کل پروژه نیست؛ فقط جلوی ادامهٔ بدون طبقه‌بندی و مخلوط‌شدن مسیرها را می‌گیرد.

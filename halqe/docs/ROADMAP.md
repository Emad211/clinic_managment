# halqe — نقشهٔ راهِ پلتفرم (حلقهٔ ساختِ سوم، ۲۰ قدم)

> این سند **جهت و ترتیبِ** ساختِ پلتفرمِ یکپارچهٔ `halqe/` را قفل می‌کند. مبنا: سنتزِ
> دو مشاورِ تیم — **principal-architect** (ترتیبِ وابسته‌محور، code-grounded) و
> **product-manager** (ارزش/معیارِ پذیرش). هر قدم = یک افزایشِ **منسجم، مستقل‌کامیت‌شدنی،
> کاملاً قابلِ‌آزمون**. اصلِ کار: «mechanism حالا، policy بعد» برای چندمستأجری.
>
> وضعیتِ شروع (همه سبز، کامیت‌شده): ۶۵ تستِ بک‌اند + ۴۸ تستِ وب روی Docker PG16
> (کانتینرِ `halqe_pg_validate` پورت ۵۵۴۳۲). آخرین کامیت پیش از این حلقه: `19a21f7`.

## اصولِ ثابت (شکستن‌شان ممنوع)
- مرزِ یک‌طرفهٔ `clinical → accounting` (فقط‌خواندنی)؛ هرگز از halqe به accounting **ننویس**.
- موتورِ بالینی **suggestion-only**؛ تصمیم با پزشک، تصمیم لاگ می‌شود.
- زمانِ ایرانِ UTC+3:30؛ تاریخِ Jalali در UI؛ هیچ پیامکِ واقعی در تست (NullProvider).
- schema-first (`managed=False`)؛ DDL در `specialist_clinic/docs/migration_tools/schema_pg_slice*.sql`.
- هر قدم: یک ایجنتِ hands-on می‌سازد + خود-اعتبارسنجیِ Docker → بازبینیِ من → کامیت/پوش.

---

## خوشهٔ A — سخت‌سازیِ بنیادی (قفلِ قرارداد؛ همه ارزان، اول)

- [ ] **۱. اتصالِ کم‌امتیاز به DB + اثباتِ واقعیِ مرز.**
  اپ به‌جای superuser با رولِ ورودِ عضوِ `platform_app` وصل می‌شود (env-configurable)؛
  superuser فقط برای `apply_schema`/seedِ accounting. تستِ نو: از اتصالِ اپ، نوشتنِ خام در
  `accounting.*` توسطِ Postgres رد می‌شود (permission denied) — مکملِ تستِ ORM-router.
  هر مسیرِ نهفته‌ای که زیرِ نقابِ superuser به accounting می‌نوشت، آشکار و اصلاح می‌شود.
  **پذیرش:** ۶۵ تست زیرِ اتصالِ کم‌امتیاز سبز + تستِ permission-denied سبز. — *api-platform-engineer*
- [ ] **۲. plumbingِ tenant-context.** middleware که در ابتدای هر request
  `SELECT set_config('app.current_tenant', …)` (GUC) را ست کند + حذفِ `tenant_id=1`ِ
  hardcode از مسیرهای audit/login (`config/api.py`) — tenant از خودِ کاربر resolve شود.
  **پذیرش:** GUC در هر اتصالِ request ست است؛ هیچ tenant ثابتِ ۱ در مسیرِ نوشتن نمی‌ماند. — *api-platform-engineer*
- [ ] **۳. قراردادِ خطای یکدست + paginationِ مشترک.** schema خطای استاندارد
  (code+message) به‌جای dictهای خام؛ استخراجِ الگوی limit/offset/total از
  `list_patients`/`list_worklist` به یک utility مشترک. **پذیرش:** هر endpoint قالبِ خطای
  یکسان می‌دهد؛ تستِ قرارداد. — *backend-engineer*
- [ ] **۴. UNIQUEِ idempotency روی `vital_readings`.** افزودنِ کلیدِ طبیعیِ مرکبِ
  tenant-safe (با planِ dedupe)؛ additive + idempotent (`IF NOT EXISTS`). **پذیرش:** درجِ
  دوگانه → یک ردیف؛ ساختِ constraint روی دادهٔ موجود امن. — *data-engineer*

## خوشهٔ B — تکمیلِ موتور و منبعِ حقیقت (ارزان، روی A)

- [ ] **۵. مدلِ `managed=False` روی VIEWِ `clinical.observations`** (UNIONِ vitals+labs) و
  تغذیهٔ `build_facts` از آن → سیم‌کشیِ lab به موتور. **پذیرش:** بیمار با egfr/ldl در
  lab_results → قاعده‌های lab-سورس fire شوند. — *backend-engineer*
- [ ] **۶. تثبیتِ age fact.** یک helperِ واحد که `demographics` را همیشه به موتور بدهد
  (هرجا engine صدا زده می‌شود) + تستِ قاعده‌های age-gated (fail-closed درست است). — *backend-engineer*
- [ ] **۷. وضعیتِ قبلیِ accept/dismiss در `get_suggestions`** (join با `SuggestionLog`) →
  `prior_action`. **پذیرش:** پس از dismiss، re-fetch وضعیت را برمی‌گرداند. — *backend-engineer*
  - [ ] **۷b. UI:** پنلِ Suggestions حالتِ قبلی را رندر کند (بدونِ رفرش). — *frontend-web-engineer*

## خوشهٔ C — مسیرِ نوشتن / encounter (نیمهٔ گم‌شدهٔ care-loop؛ روی A+B)

> schema از قبل ساخته شده (slice4b: `clinical.encounters`, `prescription_items`,
> `appointments`, `encounter_id` روی vitals/labs/notes/prescriptions). فقط مدل+سرویس+endpoint.

- [ ] **۸. مدل‌های `Encounter`/`Appointment`/`LabResult`** (managed=False روی schema موجود). — *backend-engineer*
- [ ] **۹. سرویسِ encounter** (state-machine؛ encounter = aggregate root). — *backend-engineer*
- [ ] **۱۰. POST encounter + نوشتنِ vital/lab زیرِ encounter** (مرزِ accounting دست‌نخورده؛
  `accounting_invoice_id` فقط snapshotِ شناسه، نه نوشتنِ مالی) + UIِ ثبتِ ویزیت. — *backend + frontend*
- [ ] **۱۱. مدل + مسیرِ نوشتنِ `Prescription`/`PrescriptionItem`** (نسخهٔ آزادِ غیربیمه‌ای؛
  پلِ بیمه بعداً و **بلاک‌شده**). — *backend-engineer*
- [ ] **۱۲. تولیدِ خودکارِ `followup_tasks` از موتور** (پورتِ `followup_engine.due_clinical_events`)
  — اتصالِ تشخیص→قیف. — *backend-engineer*

## خوشهٔ D — خواندنِ مالی/پذیرش (روی Port؛ مرزِ read-only)

- [ ] **۱۳. توسعهٔ `accounting_port`** برای revenue/visits/invoices (read-only، آینهٔ تعریفِ
  `webapp/accounting_bridge`). — *integrations-engineer*
- [ ] **۱۴. صفِ ویزیتِ پزشک** (`doctor_visit_log` snapshotِ مرزی). — *backend-engineer*
- [ ] **۱۵. control-room/cohort** (پورتِ `control_room_service`) + ستونِ درآمدِ manager-only در worklist. — *backend + frontend*

## خوشهٔ E — تعامل/SMS + صفِ تأیید (روی C)

- [ ] **۱۶. مدل‌های engagement** (`engagement_events`/`engagement_dispatch` با UNIQUEهای موجود). — *backend-engineer*
- [ ] **۱۷. صفِ تأییدِ پزشک** (`engagement_approvals`) — SMS فقط پس از تأیید. — *integrations-engineer*
- [ ] **۱۸. provider abstraction + scheduler** (پورتِ `engagement_service`؛ KYCِ کاوه‌نگار
  بلاک → NullProvider در عمل). — *integrations-engineer*

## خوشهٔ F — چندمستأجریِ واقعی (آخر، پرریسک)

- [ ] **۱۹. سیاست‌های RLS** روی جداولِ clinical با GUCِ `app.current_tenant` (آمادهٔ قدم ۲). — *api-platform-engineer*
- [ ] **۲۰. onboarding/مدیریتِ tenant + تستِ end-to-endِ ایزولاسیون با رولِ واقعی** (نه superuser). — *api-platform-engineer + qa-automation-engineer*

---

### ریسک‌ها/نامعلوم‌ها که در مسیر باید حل شوند
1. **تستِ ایزولاسیونِ فعلی نمایشی است** تا قدم ۱ (اتصالِ superuser → کم‌امتیاز).
2. **UNIQUEِ vital_readings** روی دادهٔ تکراریِ موجود ممکن است شکست بخورد؛ کلیدِ طبیعی
   `(tenant_id, patient_link_id, type, measured_at, source)` باید بررسی شود.
3. **مدلِ روی VIEWِ observations**: فقط read؛ سازگاریِ `distinct("type")` با obs_key بررسی شود.
4. **revenue در worklist**: staff ببیند یا فقط manager؟ — تأییدِ مالک لازم است (پیش از قدم ۱۵).
5. خارج از این ۲۰: Flutter موبایل، PDFِ نسخهٔ آزاد، پلِ بیمهٔ MV3 (بلاک‌شده تا دسترسیِ مالک).

> آخرین به‌روزرسانی: شروعِ حلقهٔ سوم. وضعیتِ هر قدم با ✅ در همین فایل علامت می‌خورد.

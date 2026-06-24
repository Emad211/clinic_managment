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

- [x] **۱. اتصالِ کم‌امتیاز به DB + اثباتِ واقعیِ مرز.**
  اپ به‌جای superuser با رولِ ورودِ عضوِ `platform_app` وصل می‌شود (env-configurable)؛
  superuser فقط برای `apply_schema`/seedِ accounting. تستِ نو: از اتصالِ اپ، نوشتنِ خام در
  `accounting.*` توسطِ Postgres رد می‌شود (permission denied) — مکملِ تستِ ORM-router.
  هر مسیرِ نهفته‌ای که زیرِ نقابِ superuser به accounting می‌نوشت، آشکار و اصلاح می‌شود.
  **پذیرش:** ۶۵ تست زیرِ اتصالِ کم‌امتیاز سبز + تستِ permission-denied سبز. — *api-platform-engineer*
  **تحویل:** `settings.py` (تفکیکِ superuser/app-role) + `ensure_app_role` command +
  `test_db_boundary.py` (۹ تست permission-denied) + رفعِ مسیرِ نهفتهٔ نوشتنِ accounting در `seed_demo`.
  ۷۴ تست سبز (۶۵+۹). کامیت `67ea79e`. ✅
- [x] **۲. plumbingِ tenant-context.** middleware که در ابتدای هر request
  `SELECT set_config('app.current_tenant', …)` (GUC) را ست کند + حذفِ `tenant_id=1`ِ
  hardcode از مسیرهای audit/login (`config/api.py`) — tenant از خودِ کاربر resolve شود.
  **پذیرش:** GUC در هر اتصالِ request ست است؛ هیچ tenant ثابتِ ۱ در مسیرِ نوشتن نمی‌ماند. — *api-platform-engineer*
  **تحویل:** `platform_core/tenant_context.py` (set/clear GUC) + `platform_core/middleware.py`
  (TenantGucMiddleware) + `auth_bearer.py` (set_tenant_guc بعد از resolve) + `auth_service.py`
  (login بدونِ tenant_id=1 + exc.tenant_id روی هر خطای پس از resolve) + `config/api.py`
  (SYSTEM_TENANT_ID=1 ثابت + audit صادقانه). ۸۲ تست سبز (۷۴ قبلی + ۸ جدید). ✅
- [x] **۳. قراردادِ خطای یکدست + paginationِ مشترک.** schema خطای استاندارد
  (code+message) به‌جای dictهای خام؛ استخراجِ الگوی limit/offset/total از
  `list_patients`/`list_worklist` به یک utility مشترک. **پذیرش:** هر endpoint قالبِ خطای
  یکسان می‌دهد؛ تستِ قرارداد. — *backend-engineer*
  **تحویل:** `config/errors.py` (ErrorSchema + error_response) + `config/pagination.py`
  (paginate helper) + custom Http404 handler روی api + `tests/test_error_contract.py`
  (11 تست: ۶ قرارداد + ۵ pagination). 93 تست سبز (82+11). ✅
- [x] **۴. UNIQUEِ idempotency روی `vital_readings`.** افزودنِ کلیدِ طبیعیِ مرکبِ
  tenant-safe (با planِ dedupe)؛ additive + idempotent (`IF NOT EXISTS`). **پذیرش:** درجِ
  دوگانه → یک ردیف؛ ساختِ constraint روی دادهٔ موجود امن. — *data-engineer*
  **تحویل:** `schema_pg_slice4c_idempotency.sql` (dedupe→MAX(id) سپس
  `UNIQUE NULLS NOT DISTINCT (tenant_id, patient_link_id, type, measured_at, source)`)
  + ۴ تستِ نگهبان در `test_pg_schema.py`. نگهبان ۷۰ (۶۶+۴)، halqe ۹۳ بدون‌تغییر. ✅

> **🏁 خوشهٔ A (سخت‌سازیِ بنیادی) کامل شد** — مرزِ واقعیِ DB، GUCِ tenant، قراردادِ خطا/pagination، idempotency.

## خوشهٔ B — تکمیلِ موتور و منبعِ حقیقت (ارزان، روی A)

- [x] **۵. مدلِ `managed=False` روی VIEWِ `clinical.observations`** (UNIONِ vitals+labs) و
  تغذیهٔ `build_facts` از آن → سیم‌کشیِ lab به موتور. **پذیرش:** بیمار با egfr/ldl در
  lab_results → قاعده‌های lab-سورس fire شوند. — *backend-engineer*
  **تحویل:** `clinical/models.py` (مدلِ `Observation` managed=False + read-only guard) +
  `clinical/rule_engine.py` (`build_facts` از `Observation.objects.distinct("obs_key")` +
  strip namespace prefix 'vital:'/'lab:' → bare key) + `tests/test_lab_engine.py`
  (7 تست: unit build_facts + rule-engine + endpoint end-to-end). 100 تست سبز. ✅
  یافته مهم: slice4a پیشوندِ 'vital:'/'lab:' به obs_key اضافه کرد — باید در همهٔ
  consumer های VIEW در نظر گرفته شود.
- [x] **۶. تثبیتِ age fact.** یک helperِ واحد که `demographics` را همیشه به موتور بدهد
  (هرجا engine صدا زده می‌شود) + تستِ قاعده‌های age-gated (fail-closed درست است). — *backend-engineer*
  **تحویل:** `clinical/suggestion_service.py` (`resolve_demographics` + `grouped_for_patient` +
  `evaluate_for_patient`) + refactor `get_suggestions` در `config/api.py` (از `_grouped_for_patient`) +
  `tests/test_age_facts.py` (6 تست: resolve/fire/no-fire/age-ineligible/evaluate/graceful-None).
  قاعدهٔ age-gated: `T2-LIPID-RX-01` (DM + age ∈ [40,75]). 106 تست سبز (100+6). ✅
  یافته: Step 12 باید `grouped_for_patient` صدا بزند، نه `rule_engine.grouped` خام — اگر نزند
  age-gated rules بی‌صدا خاموش می‌مانند.
- [x] **۷. وضعیتِ قبلیِ accept/dismiss در `get_suggestions`** (join با `SuggestionLog`) →
  `prior_action`. **پذیرش:** پس از dismiss، re-fetch وضعیت را برمی‌گرداند. — *backend-engineer*
  **تحویل:** `SuggestionRuleDTO.prior_action` (`null | "accepted" | "dismissed"`) +
  join تک‌کوئریِ `SuggestionLog` در `get_suggestions` + ۵ تست. ۱۱۱ تست سبز. ✅
  - [x] **۷b. UI:** پنلِ Suggestions حالتِ قبلی را رندر کند (بدونِ رفرش). — *frontend-web-engineer*
  **تحویل:** `api.ts` (تایپِ prior_action) + `suggestion-utils.ts` (normalise/seed) +
  `page.tsx` (سه حالتِ تأییدشده/ردشده/actionable + آپدیتِ optimistic بدونِ reload) +
  ۱۸ تست. وب ۶۶ سبز (۴۸+۱۸). ✅

> **🏁 خوشهٔ B (تکمیلِ موتور) کامل شد** — lab در موتور، age پایدار، وضعیتِ قبلیِ پیشنهادها در UI.

## خوشهٔ C — مسیرِ نوشتن / encounter (نیمهٔ گم‌شدهٔ care-loop؛ روی A+B)

> schema از قبل ساخته شده (slice4b: `clinical.encounters`, `prescription_items`,
> `appointments`, `encounter_id` روی vitals/labs/notes/prescriptions). فقط مدل+سرویس+endpoint.

- [x] **۸. مدل‌های `Encounter`/`Appointment`/`LabResult`** (managed=False روی schema موجود). — *backend-engineer*
  **تحویل:** سه مدلِ managed=False در `clinical/models.py` (وفادار به slice2+slice4b شاملِ
  ستون‌های ALTERِ slice4b: `appointments.doctor_id/chief_complaint`, `lab_results.encounter_id`)
  + `tests/test_encounter_models.py` (۱۶ تست: round-trip + ردِ CHECKِ نوع/وضعیت + ردِ FK + زنجیرهٔ سه‌مدلی).
  ۱۲۷ تست سبز (۱۱۱+۱۶). یافته: `updated_at` با trigger DB مدیریت می‌شود (نه auto_now). ✅
- [x] **۹. سرویسِ encounter** (state-machine؛ encounter = aggregate root). — *backend-engineer*
  **تحویل:** `clinical/encounter_service.py` (create/complete/cancel + add_vital/add_lab؛
  گذارهای open→completed/cancelled، sealed-immutable، tenant-isolation با پیامِ یکسانِ
  not-found، duplicate-vital→DuplicateVitalReading، audit روی هر نوشتن) + سلسله‌خطاهای دامنه
  (نگاشتِ HTTP آمادهٔ قدم ۱۰) + `tests/test_encounter_service.py` (۲۰ تست) + رفعِ flakyِ
  مقایسهٔ timestamp در `test_patient_record.py`. ۱۴۷ تست سبز (۱۲۷+۲۰). ✅
- [x] **۱۰. POST encounter + نوشتنِ vital/lab زیرِ encounter** (مرزِ accounting دست‌نخورده؛
  `accounting_invoice_id` فقط snapshotِ شناسه، نه نوشتنِ مالی) + UIِ ثبتِ ویزیت. — *backend + frontend*
  **تحویل (backend):** ۶ endpoint روی `config/api.py` (create/vitals/labs/complete/cancel/list)،
  نازک روی سرویسِ قدم ۹، نگاشتِ خطا→HTTP (۴۰۴/۴۰۹/۴۲۲ با `{detail,code}`) + `test_encounter_api.py`
  (۱۶ تست). ۱۶۳ تست بک‌اند سبز (۱۴۷+۱۶). **تحویل (frontend):** `api.ts` (۶ تابع + types) +
  فرمِ «ثبت ویزیت» (create→vitals→complete + refreshِ موازیِ record/suggestions/encounters) +
  لیستِ «ویزیت‌های اخیر» با تاریخِ جلالی + `encounters.test.tsx`. وب ۱۰۵ سبز (۶۶+۳۹)، tsc پاک. ✅

> **🏁 نیمهٔ گم‌شدهٔ care-loop (نوشتنِ encounter) کامل شد** — از ثبتِ ویزیت تا اندازه‌گیری تا بستن.
- [x] **۱۱. مدل + مسیرِ نوشتنِ `Prescription`/`PrescriptionItem`** (نسخهٔ آزادِ غیربیمه‌ای؛
  پلِ بیمه بعداً و **بلاک‌شده**). — *backend-engineer*
  **تحویل:** دو مدلِ managed=False + `add_prescription_to_encounter` (اتمیک header+items،
  گاردِ `mode='insurance'`→`InsurancePrescriptionNotSupported`، validateِ frequency/route/qty)
  + `POST /encounters/{id}/prescriptions` + `tests/test_prescription.py` (۱۵ تست).
  **+ رفعِ باگِ واقعی:** `add_vital_to_encounter` اشتباهاً `encounter_id` را روی vitals ست
  نمی‌کرد (کامنتِ غلط: «slice4b فقط به lab اضافه می‌کند»)، در‌حالی‌که slice4b به vital_readings
  هم اضافه کرده — vitalها به encounterشان لینک نمی‌شدند (نقضِ aggregate-root). فیلدِ مدل +
  ست‌کردنِ encounter_id + assertion افزوده شد. ۱۷۸ تست سبز (۱۶۳+۱۵). ✅
- [x] **۱۲. تولیدِ خودکارِ `followup_tasks` از موتور** (پورتِ `followup_engine.due_clinical_events`)
  — اتصالِ تشخیص→قیف. — *backend-engineer*
  **تحویل:** پورتِ وفادارِ `clinical/followup_engine.py` (`due_clinical_events`/`generate_for_patient`/
  `generate_all`؛ از `evaluate_for_patient`ِ گاردِ قدم۶، نه موتورِ خام؛ `_last_done` روی
  vitals+labs طبقِ ADR-0005؛ dedup/idempotent؛ audit per task) + management command
  `generate_followups [--tenant]` + `tests/test_followup_engine.py` (۱۱ تست، شاملِ اثباتِ
  استفاده از evaluate_for_patient). ۱۸۹ تست سبز (۱۷۸+۱۱). ✅

> **🏁 خوشهٔ C (مسیرِ نوشتن / encounter) کامل شد** — مدل‌ها → سرویس → endpoint+UI → نسخه → تشخیص→قیف.

## خوشهٔ D — خواندنِ مالی/پذیرش (روی Port؛ مرزِ read-only)

- [x] **۱۳. توسعهٔ `accounting_port`** برای revenue/visits/invoices (read-only، آینهٔ تعریفِ
  `webapp/accounting_bridge`). — *integrations-engineer*
  **تحویل:** `get_revenue_by_patient_ids` + `get_patient_revenue_summary` +
  `get_daily_revenue_by_patient_ids` در `accounting_port/port.py` (closed-only، work_date،
  visits.price+injections.total_price+procedures.price؛ همه via `accounting_read`، SELECT-only؛
  obligationِ sync سه‌جا مستند) + `tests/test_accounting_revenue_port.py` (۱۵ تست شاملِ ردِ
  invoiceِ باز). ۲۰۴ تست سبز (۱۸۹+۱۵). ✅
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
6. **(قدم ۵، follow-up)** `build_facts` با `DISTINCT ON(obs_key)`ِ نام‌فضادار کار می‌کند؛ اگر یک
   اندیکاتور (مثل `hba1c`) هم vital و هم lab باشد، پس از strip هر دو به کلیدِ خام نگاشته می‌شوند و
   نسخهٔ vital (به‌خاطرِ ترتیبِ الفبایی) بازنویسی می‌کند — یعنی «vital برنده» نه «جدیدترینِ کلی».
   برای دمو بی‌اثر (هر اندیکاتور از یک منبع)؛ اصلاحِ آینده: dedup روی کلیدِ خام با max(observed_at).
7. **(قدم ۱۰، follow-up)** `ApiError` در وب فقط `detail` را حمل می‌کند نه `code`؛ نگاشتِ پیامِ خطای
   ویزیت با heuristicِ substring روی متن کار می‌کند (شکننده اگر متنِ `detail` تغییر کند). اصلاح:
   `apiFetch` را گسترش بده تا `code` را از body بخواند و `encounterErrorMessage` روی `code` سوییچ کند.
8. **(قدم ۱۰)** افزودنِ batchِ vital/lab atomic نیست (شکستِ آیتمِ دوم، آیتمِ اول را نگه می‌دارد)؛
   آگاهانه (هر آیتم مستقل audit)؛ اگر atomicity لازم شد، wrapper تراکنش.

> آخرین به‌روزرسانی: شروعِ حلقهٔ سوم. وضعیتِ هر قدم با ✅ در همین فایل علامت می‌خورد.

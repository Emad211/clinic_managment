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
- [x] **۱۴. صفِ ویزیتِ پزشک** (`doctor_visit_log` snapshotِ مرزی). — *backend-engineer*
  **تحویل:** `accounting_port.fetch_open_visit_invoices` (read-only) + مدلِ `DoctorVisitLog` +
  `clinical/doctor_queue_service.py` (`get_queue`/`start_visit`/`end_visit`؛ ادغامِ
  invoiceهای بازِ read-only با وضعیتِ لوکال، نگاشت به patient_link با patient_id، upsert روی
  UNIQUE(tenant,invoice)، گذارِ waiting→in_progress→done، audit) + ۳ endpoint (GET/start/done)
  + `tests/test_doctor_queue.py` (۱۳ تست). ۲۱۷ تست سبز (۲۰۴+۱۳). UI موکول. ✅
- [x] **۱۵. control-room/cohort** (پورتِ `control_room_service`) + ستونِ درآمدِ manager-only در worklist. — *backend + frontend*
  **تحویل (backend):** `clinical/control_room_service.py` (panel/cohort_ids/conversion؛ امتیازِ
  بالینی‌-اول؛ demographics از Port؛ control vitals از observations؛ revenue از پورتِ قدم۱۳،
  manager-only via `show_value=role=='manager'`) + `GET /control-room` + `/conversion` +
  `/cohort/{key}` + `include_revenue` در worklist (گیتِ manager) + `tests/test_control_room.py`
  (۱۹ تست). ۲۳۶ سبز (۲۱۷+۱۹). **تحویل (frontend):** ستونِ «درآمد» data-driven (فقط وقتی
  backend برگرداند = مدیر)، `formatToman` + `worklist-revenue.test.tsx`. وب ۱۲۲ سبز (۱۰۵+۱۷). ✅
  *(صفحهٔ کاملِ /control-room در UI موکول شد؛ endpoint + داده آماده است.)*

> **🏁 خوشهٔ D (خواندنِ مالی/پذیرش) کامل شد** — revenue، صفِ پزشک، اتاقِ کنترل؛ همه read-only از مرز.

## خوشهٔ E — تعامل/SMS + صفِ تأیید (روی C)

- [x] **۱۶. مدل‌های engagement** (`engagement_events`/`engagement_dispatch` با UNIQUEهای موجود). — *backend-engineer*
  **تحویل:** مدل‌های `EngagementEvent` + `EngagementDispatch` (managed=False) + management
  command `seed_engagement_events` (۱۴ رویدادِ پیش‌فرض، وفادار از `schema.sql`، idempotent
  ON CONFLICT) + `tests/test_engagement_models.py` (۸ تست شاملِ ردِ CHECK + UNIQUEِ
  idempotencyِ dispatch). ۲۴۴ سبز (۲۳۶+۸). یافته: FKِ مرکبِ پنهانِ slice2b
  `engagement_dispatch(tenant,event_key)→engagement_events`. ✅
- [x] **۱۷. صفِ تأییدِ پزشک** (`engagement_approvals`) — SMS فقط پس از تأیید. — *integrations-engineer*
  **تحویل:** مدلِ `EngagementApproval` + `clinical/engagement_approval_service.py`
  (`enqueue_approval` idempotent، `list_pending`، `approve`/`reject` با state-machine
  pending→approved/rejected، استثناهای دامنه، audit) + ۳ endpoint (GET صف + approve/reject
  **manager-only** با 403) + `tests/test_engagement_approvals.py` (۱۵ تست شاملِ گیتِ staff،
  ایزولاسیونِ tenant، عدمِ ارسالِ SMS). ۲۵۹ سبز (۲۴۴+۱۵). **هیچ پیامکی اینجا نمی‌رود.** ✅
- [x] **۱۸. provider abstraction + scheduler** (پورتِ `engagement_service`؛ KYCِ کاوه‌نگار
  بلاک → NullProvider در عمل). — *integrations-engineer*
  **تحویل:** `clinical/sms/provider.py` (SendResult/SmsProvider/NullProvider/KavenegarProvider/
  `get_provider`→NullProvider بدون کلید) + `sms/compliance.py` (پورت) + `clinical/engagement_service.py`
  (`dispatch_patient`/`run_all`؛ phone از Port، گاردریل‌های opt-out/cooldown/idempotency/quiet-hours؛
  worklist→task، sms→enqueue_approval) + endpointِ manager-only `POST /engagement/approvals/{id}/send`
  (جریانِ pending→approved→sent؛ ارسال فقط با NullProvider در عمل) + `run_engagement` command +
  `tests/test_engagement_dispatch.py` (۲۴ تست، شاملِ patchِ urlopen برای اثباتِ عدمِ تماسِ شبکه).
  ۲۸۳ سبز (۲۵۹+۲۴). **هیچ SMS واقعی؛ گیتِ KYC مستند.** ✅

> **🏁 خوشهٔ E (تعامل/SMS + صفِ تأیید) کامل شد** — موتورِ رویداد→کانال با گاردریل، تأییدِ انسانی، NullProvider.

## خوشهٔ F — چندمستأجریِ واقعی (آخر، پرریسک)

- [x] **۱۹. سیاست‌های RLS** روی جداولِ clinical با GUCِ `app.current_tenant` (آمادهٔ قدم ۲). — *api-platform-engineer*
  **تحویل:** `specialist_clinic/docs/migration_tools/schema_pg_slice5_rls.sql` — DO-block روی `pg_catalog`: همهٔ جداولِ `tenant_id`دارِ `clinical`+`platform` → `ENABLE`+**`FORCE`** ROW LEVEL SECURITY + policyِ idempotentِ `tenant_isolation FOR ALL` با `USING/WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::bigint)` = **fail-closed** (GUCِ خالی→NULL→صفر ردیف)؛ + `ALTER VIEW clinical.observations SET (security_invoker=true)` تا VIEW از حقوقِ مالک/superuser دور نزند (رفعِ RLS-TODOِ slice2). `accounting.*` عمداً RLS نگرفت (مرز read-only؛ موکول به T1). **استثناءِ auth:** `platform.users` یک policyِ دومِ `tenant_isolation_read (FOR SELECT USING true)` دارد چون login باید username را پیش از دانستنِ tenant بیابد — **WRITE همچنان tenant-قفل**، امنیت via JWT claim (ریسک #۱۰). **تست:** ۹ تستِ RLSِ نگهبان با **رولِ واقعیِ `clinical_login_test` (نه superuser)** — read-isolation (GUC=1→فقط t1)، fail-closed (GUC=''→۰ ردیف)، write-check (INSERT tenant_id=2→رد)، observations (security_invoker)، idempotency؛ + assertِ relrowsecurity/relforcerowsecurity + نبودِ BYPASSRLS/super روی app-roleها. رگرسیونِ ۲۸۲ تست حل شد با fixtureِ autouseِ `set_default_tenant_guc(1)` (شبیه‌سازیِ auth_bearer برای کوئریِ مستقیمِ ORM) + ست‌کردنِ GUC در `seed_engagement_events`/`test_auth._reset_user`/`test_db_boundary._app_conn`. **نگهبان ۷۹ سبز (۷۰+۹)، halqe ۲۸۲ سبز + ۱ skip** (هر دو روی Docker، بازبینیِ مستقل). ✅
- [x] **۲۰. onboarding/مدیریتِ tenant + تستِ end-to-endِ ایزولاسیون با رولِ واقعی** (نه superuser). — *api-platform-engineer + qa-automation-engineer*
  **تحویل (onboarding):** `specialist_clinic/docs/migration_tools/schema_pg_slice6_onboarding.sql` — تابعِ `platform.provision_tenant(name, admin_username, password_hash, full_name)` با `SECURITY DEFINER SET search_path=platform,pg_temp` (RLS را فقط برای provisioning امن دور می‌زند؛ `EXECUTE` فقط به `platform_app`، `REVOKE FROM PUBLIC`)؛ idempotent (`UNIQUE(name)` گاردشده با IF NOT EXISTS + `ON CONFLICT DO NOTHING` روی tenant و `(tenant_id,username)` + `setval` برای رفعِ باگِ واقعیِ IDENTITYِ seed-با-id-صریح)؛ کاربرِ مدیر `role='manager'` (از CHECKِ واقعیِ slice0) + `halqe/platform_core/onboarding_service.py` (bcrypt، فراخوانیِ تابع) + command `onboard_tenant` + `tests/test_onboarding.py` (۸ تست). endpointِ `POST /admin/tenants` موکول (نیازمندِ flag/نقشِ superadmin؛ سرویس+command کافی).
  **تحویل (e2e):** `halqe/tests/test_e2e_tenant_isolation.py` — ۱۱ تست از **مسیرِ کاملِ واقعی** (provision→login→JWT→`JWTBearer.authenticate`→`set_tenant_guc`→RLS→رولِ کم‌امتیازِ `platform_login_test`): P1/P2 خودی (شمارشِ دقیق)، **N1 cross-tenant by-id → 404 (نه 403، بی‌افشای وجود)**، N2 لیست بدونِ نشتِ B، N3 نوشتن با `tenant_id=B` در body → بسته (GUC از JWT است نه body)، N4 بدونِ JWT → 401، N5 JWTِ دستکاری/منقضی → 401، E2 `clinical.observations` (security_invoker) فقط tenant-A، E4 عدمِ UPDATEِ cross-tenantِ `platform.users`، + **گاردِ ضدِ «سبزِ کاذب»** (assert اتصال `rolsuper=false` و `rolbypassrls=false` — وگرنه superuser کلِ RLS را bypass و تست را دروغین سبز می‌کند).
  **بازبینیِ مستقلِ من روی Docker:** halqe **۳۰۱ سبز + ۱ skip** (۲۹۰+۱۱)، نگهبان **۷۹ سبز** (slice6 idempotent، اثباتِ re-apply)، + تأییدِ مستقیمِ وجودِ `clinical.observations` با `security_invoker=true`. **ریسکِ #۱ بسته شد.** ✅

> **🏁 خوشهٔ F (چندمستأجریِ واقعی) کامل شد** — RLSِ fail-closed، provisioningِ امنِ tenant، و اثباتِ e2e ایزولاسیون با رولِ کم‌امتیازِ واقعی. **هر ۲۰ قدمِ حلقهٔ سوم + ۲ قدمِ بازمانده تمام.**

---

### ریسک‌ها/نامعلوم‌ها که در مسیر باید حل شوند
1. ✅ **حل شد (قدم ۲۰):** تستِ e2e ایزولاسیون با **رولِ واقعیِ کم‌امتیازِ `platform_login_test`** (نه superuser) + گاردِ ضدِ سبزِ کاذب (assert نبودِ rolsuper/rolbypassrls) — خواندن/نوشتنِ cross-tenant از مسیرِ APIِ واقعی بسته است. (قبلاً: تا قدم ۱ نمایشی بود.)
2. **UNIQUEِ vital_readings** روی دادهٔ تکراریِ موجود ممکن است شکست بخورد؛ کلیدِ طبیعی
   `(tenant_id, patient_link_id, type, measured_at, source)` باید بررسی شود.
3. **مدلِ روی VIEWِ observations**: فقط read؛ سازگاریِ `distinct("type")` با obs_key بررسی شود.
4. **revenue در worklist**: ✅ حل شد (قدم ۱۵) — **manager-only** (گیتِ سخت در backend؛ staff هرگز نمی‌بیند)، مطابقِ الگوی `control_room_service`. اگر مالک خواست staff هم ببیند، فقط گیت تغییر کند.
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
9. **(قدم ۱۷، follow-up برای ۱۸)** `enqueue_approval` از get()-then-create استفاده می‌کند (نه
   اتمیک get_or_create) — برای schedulerِ تک‌نخی امن است؛ dispatcherِ قدم ۱۸ باید تک‌نخی بماند
   یا get_or_create شود، و **همیشه `period_key` پر باشد** (UNIQUE روی NULL کار نمی‌کند).
10. **(قدم ۱۹، امنیتِ T1) `platform.users` خواندنِ cross-tenant باز است** (`tenant_isolation_read
   FOR SELECT USING true`) — لازمهٔ loginِ username-اول است (chicken-and-egg)، ولی یعنی هر اتصالِ
   app-role می‌تواند `password_hash`/`api_token_hash`ِ همهٔ مستأجرها را بخواند (همان Finding-4/
   RLS-TODOِ slice0). **WRITE قفل است** (با `tenant_isolation`). سخت‌سازیِ T1: یک تابعِ
   `SECURITY DEFINER`ِ `auth_lookup_user(username)` که فقط همان ردیف را برگرداند و policyِ SELECTِ
   آزاد حذف شود؛ یا مسیریابیِ tenant پیش از login. تا آن زمان، اپ نباید `platform.users` را برای
   چیزی جز authٰ بخواند.
11. **(قدم ۱۹، follow-up) `set_config(..., is_local=false)`** GUC را روی کانکشن نگه می‌دارد؛ با
   PgBouncer در حالتِ transaction-pooling می‌تواند بینِ requestها نشت کند. الان pooler نیست و
   middleware در ابتدای هر request پاک می‌کند؛ در ابر (T1) قبل از افزودنِ pooler بازبینی شود.

> آخرین به‌روزرسانی: حلقهٔ چهارم — قدم‌های ۱۹ (RLS) و ۲۰ (onboarding + e2e ایزولاسیون) سبز؛ **خوشهٔ F و کلِ ۲۲ قدم تمام**. حالا فازِ ۴۰ قدمی پایین.

---

# فازِ ۴۰ قدمی (حلقهٔ چهارم) — از «پلتفرمِ اثبات‌شده» تا «محصولِ قابلِ‌فروش»

> سنتزِ **گردهماییِ ۶‌لنزه**: `product-manager` (ارزش/MVP) · `principal-architect` (وابستگی/معماری/بدهیِ عملیاتی) · `clinical-product-advisor` (عمقِ بالینی، صدای هیئت) · `clinical-data-scientist` (سنجشِ پیامد/holdout) · `ux-ui-designer` (IA/دیزاین‌سیستمِ پنل + اپ بیمار) · `marketing-growth-advisor` (بازار/SEO). هر قدم = افزایشِ **منسجم، مستقل‌کامیت‌شدنی، کاملاً‌قابل‌آزمون**؛ همان اصولِ قفل‌شده (مرزِ accounting فقط‌خواندنی، suggestion-only، Jalali/وقتِ ایران، migrationِ افزایشیِ idempotent، **هیچ پیامکِ واقعی**).
>
> **یافتهٔ مهمِ گردهمایی:** فرانتِ `halqe/web/` تقریباً **خالی** است (فقط `package.json`) — UIِ پزشک/مدیر greenfield است. بک‌اند با ۳۰۱+۱۲۲+۷۹ تستِ سبز آماده است ولی **بدهیِ عملیاتی** دارد (CI نیست، Dockerfile/health نیست، بوتِ production ناامن، نشتِ GUC با pooling=ریسک #۱۱، error-`code` در کلاینت ناقص=ریسک #۷). پس: **اول بسترِ ارزانِ‌بحرانی، موازی با UIِ visible.**
>
> **تصمیمِ scope (هم‌راستا با خواستهٔ مالک «migration مهم نیست، کیفیت اولویت است»):** پورتِ کاملِ *بدنهٔ* accounting به Postgres در این فاز **نیست**؛ پلِ read-only درآمد (قدم ۱۳) کافی است. تمرکز: محصولِ بالینیِ قابلِ‌استفاده + قابلِ‌فروش.
>
> **یادداشتِ «قاعدهٔ خاموش» (نه قدم):** سن و lab از قبل به موتور سیم‌کشی‌اند (`rule_engine` از VIEWِ `observations` می‌خواند = vital+lab؛ سن via `suggestion_service.evaluate_for_patient/grouped_for_patient` همیشه inject می‌شود — قدم ۶). کامنتِ «Deferred» در `rule_engine.py:19-23` گمراه‌کننده است (به موتورِ خالص اشاره دارد) — در قدم ۳۵ تمیز می‌شود.

## ترتیبِ اجرا و گِیت‌ها
ترتیبِ خطیِ ۲۱→۶۰ (وابسته‌محور، value-front-loaded): بسترِ بحرانی (۲۱–۲۳) و اسکلتِ وب (۲۴) اول؛ سپس UI و بسترِ باقی درهم‌تنیده؛ بعد عمقِ بالینی، سنجش، اپ بیمار، تعامل، استقرار، رشد. **گِیتِ مالک/داده** (می‌سازیم و لوکال تست می‌کنیم؛ کلیدِ نهایی با مالک): میزبانِ CI (۲۱)، VPSِ واقعی (۵۵)، KYCِ پیامک (۵۳)، قیمت‌گذاری (۶۰)، تأییدِ نهاییِ آستانه‌های بالینی توسط پزشک (۳۹/۴۰)، دادهٔ چندماههٔ واقعی برای outcome (۴۹).

## خوشهٔ G — بسترِ عملیات و سخت‌سازی (ارزانِ‌بحرانی، اول)
- [x] **۲۱. CIِ سبز** روی ۳ سوئیت (backend pytest + web jest + نگهبانِ `test_pg_schema`) با سرویس‌کانتینرِ Postgres؛ push→قرمز/سبز. *(devops-engineer + qa-automation-engineer)* — **آرتیفکت ساخته + لوکال validate؛ گِیتِ مالک: فعال‌سازیِ Actions.**
  **تحویل:** `.github/workflows/ci.yml` (۳ jobِ مستقل، هرکدام سرویسِ `postgres:16` + healthcheck): **backend** (`halqe` pytest؛ conftest خودش DBِ `halqe_app_test` + رولِ کم‌امتیازِ `platform_login_test` + همهٔ slice‌ها را می‌سازد → fresh-CI خودکفا) · **schema-guard** (`specialist_clinic/tests/test_pg_schema.py` via `PG_TEST_DSN` روی DBِ `halqe`؛ fixture خودش slice + `clinical_login_test`) · **web** (`halqe/web` jest، Node 20، `npm ci`). trigger: push/PR روی `main` + `workflow_dispatch`؛ **شکستِ هر سوئیت = CI قرمز**. + `.github/workflows/README.md` (گِیتِ مالک + قابلِ‌انتقال به Gitea/GitLab runner). **بازبینیِ مستقلِ من:** هر ۳ سوئیت لوکال سبز (**۳۰۱+۱ / ۷۹ / ۱۲۲**)؛ ریسکِ fresh-CI بسته شد (conftest:116 رولِ app را می‌سازد؛ `halqe/requirements.txt:5-6` شاملِ pytest+pytest-django)؛ YAML معتبر؛ gate با exit-code=1 اثبات. `clinic_new.db` لمس نشد، هیچ پیامکِ واقعی. **گِیتِ مالک:** Settings→Actions فعال + push. ✅
- [x] **۲۲. سخت‌سازیِ بوتِ production** — پورتِ فلگِ `PRODUCTION` (fail-fastِ `SECRET_KEY`/`DEBUG=False`/`ALLOWED_HOSTS` از env) + `.env.example` + تستِ نگهبان که default-secret در production را رد کند (`settings.py:35-39`). *(api-platform-engineer)*
  **تحویل:** `config/env.py` (توابعِ خالصِ تستی‌پذیر `is_production`/`resolve_secret_key`/`resolve_debug`/`resolve_allowed_hosts`/`resolve_cors_origins`؛ فلگِ `PRODUCTION` هم‌نام با `specialist_clinic`) + `config/settings.py` (فراخوانیِ resolverها + `PRODUCTION` read-only) + `halqe/.env.example` + `tests/test_prod_config.py` (۳۳ تست؛ `.env` در `.gitignore`). **رفتار:** production → `SECRET_KEY` خالی/دیفالت = `ImproperlyConfigured`، `DEBUG=False` اجباری، `ALLOWED_HOSTS` صریح (`*` رد)، CORS از env؛ dev/CI کاملاً دست‌نخورده. **بازبینیِ مستقلِ من (۴ سناریوی بوتِ واقعی):** S1 dev→بوت/DEBUG=True/HOSTS=['*']؛ S2 prod بدون secret→`ImproperlyConfigured`؛ S3 prod با کلید+هاست→DEBUG=False+هاستِ صریح؛ S4 prod با `*`→`ImproperlyConfigured`. سوئیت **۳۳۴+۱ سبز** (۳۰۱+۳۳)، CIِ غیرproduction نمی‌شکند. ✅
- [x] **۲۳. ADR-0008 + اصلاحِ GUC/pooling (ریسک #۱۱)** — تصمیمِ transaction-scoped GUC (`SET LOCAL` در atomic) یا قراردادِ session-pooling؛ `tenant_context` اصلاح + تستِ نشت با کانکشنِ بازیافتی. *(security-privacy-advisor + data-architect → api-platform-engineer)*
  **تصمیمِ گردهمایی:** «mechanism حالا، policy بعد» = **گزینهٔ B سخت‌شده، نه `SET LOCAL`** (data-architect اثبات کرد: `SET LOCAL` بدونِ `ATOMIC_REQUESTS` بیرونِ تراکنش گم می‌شود → RLS صفر ردیف → همهٔ endpointهای authed + fixtureِ autouse می‌شکنند؛ هزینهٔ زودرس برای صفر سود چون poolerی نیست). **امروز نشتی نیست** (`CONN_MAX_AGE=0` → کانکشنِ تازه per request؛ GUC با بستنِ کانکشن می‌میرد). **تحویل:** `specialist_clinic/docs/adr/0008-tenant-guc-lifecycle-and-pooling.md` (تصمیم + مکانیکِ Postgres session/transaction + قراردادِ **منعِ transaction-pooler** + seamِ موکولِ ۵‌گامه `SET LOCAL`+`ATOMIC_REQUESTS` برای تریگرِ T1) + `config/env.py:resolve_conn_max_age` (گاردِ بوت: `PRODUCTION=1` + `CONN_MAX_AGE>0` بدونِ `TENANT_GUC_POOLING_ACK=session-mode-only` → `ImproperlyConfigured`) + `config/settings.py` (`CONN_MAX_AGE=0` invariantِ صریح، هر دو DB) + `platform_core/middleware.py` (clearِ defense-in-depthِ `try/finally`) + `tests/test_guc_leak.py` (۶ تستِ **ضدِ سبزِ کاذب**: poison→clear، causal-proof GUC=1→rows سپس clear→۰، سوییچِ cross-tenant t1→t2) + ۱۴ تستِ گاردِ بوت. **بازبینیِ مستقلِ من:** مکانیزم دست‌نخورده (`set_config(...,false)` خطوط ۴۸/۷۳)؛ گاردِ بوت هر ۴ سناریو درست؛ سوئیت **۳۵۴+۱ سبز** (۳۳۴+۲۰). ✅
- [ ] **۲۸. health/readiness + لاگِ ساخت‌یافته** — `/healthz` (بدون DB) و `/readyz` (با DB) ۲۰۰/۵۰۳ + request-id + لاگِ PII-free. *(backend-engineer)*
- [ ] **۳۳. Dockerfile + gunicorn + compose + entrypoint(`apply_schema`)** — `docker build` سبزِ لوکال؛ بدون runserver در production. *(devops-engineer)*
- [ ] **۳۴. سخت‌سازیِ auth برای T1 (ریسک #۱۰)** — تابعِ `platform.auth_lookup_user(username)` با `SECURITY DEFINER` که فقط همان ردیف را برگرداند + حذفِ policyِ `tenant_isolation_read USING(true)` + e2e که app-role دیگر `password_hash`ِ مستأجرِ دیگر را نمی‌خواند. *(api-platform-engineer)*

## خوشهٔ H — پنلِ وبِ پزشک/مدیر (greenfield؛ Next.js App Router، RTL/Jalali)
- [x] **۲۴. اسکلت + دیزاین‌سیستم + Login + api-client** — AppShell/Sidebar/TopBar، توکن‌های رنگ/تایپ، `dir=rtl`+وزیرمتنِ آفلاین، صفحهٔ `/login` (JWT)، `apiFetch` که **`code` را از body می‌خواند** (رفعِ ریسک #۷) + utilهای `jalali`/`toFa`. *(ux-ui-designer + frontend-web-engineer)* — **یافتهٔ گراندینگ: اسکلت از قبل بود** (layout RTL، login، dashboard+Nav، `globals.css`ِ توکن‌دار، `jalali.ts`، `api.ts`ِ کامل، ۱۲۲ تست) → این قدم = **سخت‌سازیِ اسکلتِ موجود**، نه بازساخت.
  **تحویل (مرکزِ ثقل = رفعِ ریسک #۷):** `api.ts` → `ApiError.code` (backward-compatible) + `apiFetch` خواندنِ `body.code` + `errorMessageFromCode(code, fallback)` با کدهای **واقعیِ** `config/errors.py`/`api.py` (`not_found`/`validation_error`/`encounter_sealed`/`duplicate_vital`/`invalid_transition`/auth) تا صفحاتِ بعدی روی `code` سوییچ کنند نه substring (follow-up قدم ۱۰ هم بسته شد). + چکِ انقضای JWT در `getToken` (decodeِ base64urlِ بدون‌کتابخانه، evictِ توکنِ منقضی) + هوکِ `useAuth` (گاردِ متمرکز، `dashboard` مصرف‌کننده) + `login` (redirect-if-authenticated + spinner) + ۳ توکنِ additive. فونت‌های Vazirmatn در `public/fonts/` تأیید. **بازبینیِ مستقلِ من:** کدهای error با grepِ بک‌اند واقعی‌اند؛ `npm test` **۱۴۲ سبز** (۱۲۲+۲۰)، `tsc --noEmit` پاک. ✅
- [ ] **۲۵. `/patients`** لیست + جستجوی صفحهٔ جاری → پروندهٔ بیمار. *(frontend-web-engineer)*
- [ ] **۲۶. `/patients/[uuid]` پایه (record)** — بیماری/داروی فعال + ۱۰ vitalِ اخیر با `VitalTile`/`StatusBadge`. *(frontend-web-engineer)*
- [ ] **۲۷. پنلِ Suggestions + نگهبانِ معماری** — `SuggestionCard` با هِدرِ **همیشه‌نمایانِ «پیشنهاد — تأیید با پزشک»**، بنرِ red-flag، accept/dismissِ optimistic + `prior_action`؛ **تستِ نگهبان که متنِ «تأیید با پزشک» در DOM می‌ماند**. *(frontend-web-engineer + clinical-product-advisor)*
- [ ] **۲۹. `/queue`** صفِ پزشک (SWR poll، start→ویزیت). *(frontend-web-engineer)*
- [ ] **۳۰. ثبتِ ویزیتِ inline** — create→vitals→complete روی صفحهٔ بیمار + رفرشِ suggestions (یک‌پنجره، بدونِ redirect). *(frontend-web-engineer)*
- [ ] **۳۱. فرمِ نسخهٔ آزاد** — `mode=free`؛ `insurance`→۴۲۲ graceful. *(frontend-web-engineer)*
- [ ] **۳۲. `/worklist` + `/manager`** — کارتابلِ due + ستونِ درآمدِ **manager-only** (نگهبانِ DOM که staff نمی‌بیند). *(frontend-web-engineer)*

## خوشهٔ I — عمقِ بالینی و ایمنیِ موتور (هیئتِ بالینی هر قدم حاضر)
- [ ] **۳۵. شفافیتِ «قاعدهٔ خاموش»** — بنرِ «X قاعده به‌خاطرِ دادهٔ ناقص (سن/lab) ارزیابی نشد» تا پزشک بداند موتور همه را ندیده؛ + تمیزکردنِ کامنتِ گمراه‌کنندهٔ `rule_engine.py`. *(backend-engineer + clinical-product-advisor)*
- [ ] **۳۶. لایهٔ دادهٔ تداخلِ دارویی (DDI)** — جدولِ `ddi_pairs(class_a,class_b,severity,message_fa,evidence)` + سرفیسِ suggestion-only؛ ≤۱۵ جفتِ high-certainty؛ ویرایشِ مدیر. *(backend-engineer + clinical-pharmacist-advisor)*
- [ ] **۳۷. تقویمِ غربالگری** — `GET /patients/{uuid}/screening-timeline` (آخرین/سررسیدِ بعدی per آیتم) از `due_clinical_events`. *(backend-engineer + gp-family-medicine-advisor)*
- [ ] **۳۸. ردیابیِ اثرِ دارو** — `GET .../medications/{id}/effect` دلتای پیش/پسِ ۹۰روزه از observations؛ `data_insufficient` به‌جای عددِ ساختگی. *(backend-engineer + clinical-research-advisor)*
- [ ] **۳۹. گریدِ red-flag per-population** — سالمندِ frail vs جوان؛ gated، suggestion-only، آستانه با تأییدِ هیئت. *(backend-engineer + endocrinology-advisor + cardiology-advisor؛ گِیت: تأییدِ پزشک)*
- [ ] **۴۰. پاسِ روزآمدیِ آستانه‌ها** — `clinical_indicators` در برابر ADA/KDIGO/ESC + هم‌گامیِ fallbackها و docs (قانونِ threshold-sync). *(backend-engineer + clinical-research-advisor + متخصص‌ها؛ گِیت: تأییدِ پزشک)*

## خوشهٔ K — سنجشِ پیامد و کیفیتِ موتور
- [ ] **۴۱. آمارِ پیشنهاد + لاگِ رویدادمحور** — endpointِ fire/accept/dismiss per `rule_code`؛ + اصلاحِ `suggestion_log` به **append رویداد** (نه overwrite) تا تاریخچه سنجش‌پذیر شود. *(backend-engineer + clinical-data-scientist)*
- [ ] **۴۲. اصلاحِ funnel-conversion** — denominator = همهٔ followupهای تولیدشده (نه فقط done) + `cohort_age`. *(backend-engineer)*
- [ ] **۴۳. فلگِ holdoutِ تعامل** — ستونِ افزایشیِ `engagement_holdout` + skip در dispatcher + تخصیصِ تصادفیِ مدیر؛ stepped-wedge، اخلاقی (مراقبتِ ویزیت دریغ نمی‌شود). *(backend-engineer + clinical-data-scientist)*
- [ ] **۴۹. جدولِ outcomeِ کوهورت** — per-condition baseline→۳mo→۶mo (A1c/BP) + covariate (frailty/ASCVD). *(data-engineer + clinical-data-scientist؛ گِیتِ داده: نیازمندِ ماه‌ها دادهٔ واقعی)*
- [ ] **۵۰. داشبوردِ outcomeِ مدیر** — `/manager/outcomes`: acceptance، lapsed→return، funnel، time-seriesِ کنترل؛ **بدونِ ادعای causal تا holdout**. *(frontend-web-engineer + backend-engineer + clinical-data-scientist)*

## خوشهٔ J — اپ بیمار (PWA) و self-report
- [ ] **۴۴. اسکلتِ PWA + کارتِ بیمار** — `/card/[token]` فقط‌خواندنی، ارقامِ فارسیِ بزرگ + رنگِ وضعیت، بدونِ national_id در URL. *(frontend-web-engineer/mobile-engineer؛ گِیت: LAN-vs-internet)*
- [ ] **۴۵. endpointِ self-report بیمار** — `POST /patient-report/{token}` (یک‌بارمصرف، TTL)، `source='patient_self'`, `verified=false`؛ **هرگز در موتور تا تأییدِ پزشک**. *(backend-engineer + security-privacy-advisor)*
- [ ] **۴۶. فرمِ self-reportِ PWA** — BP/FBS/وزن، عددی، آفلاین cache+sync. *(frontend-web-engineer)*
- [ ] **۴۷. UIِ تأییدِ پزشک برای self-report** — آیتم‌های unverified در encounter، تأیید/رد. *(frontend-web-engineer + gp-family-medicine-advisor)*
- [ ] **۴۸. کارتِ یادآور/غربالگریِ بیمار** — از screening-timeline؛ لینکِ SMS (گِیتِ KYC). *(frontend-web-engineer)*

## خوشهٔ L — تعامل/پیامک در محیطِ واقعی
- [ ] **۵۱. schedulerِ تعامل در production** — Celery/Redis یا cronِ مدیریتیِ پایدار؛ idempotent + گاردریل‌ها؛ `run_engagement` قابل‌اعتماد. *(backend-engineer + devops-engineer)*
- [ ] **۵۲. UIِ صفِ تأیید + تنظیماتِ تعامل** — صفِ مدیر pending→approve/reject→send (NullProvider تا KYC) + quiet-hours/opt-out/daily-cap. *(frontend-web-engineer)*
- [ ] **۵۳. آمادگیِ provider پیامک + گِیتِ KYC** — اثباتِ NullProvider + مسیرِ liveِ پشتِ فلگ؛ مستندِ KYC. *(integrations-engineer؛ گِیتِ مالک: KYCِ کاوه‌نگار)*

## خوشهٔ M — استقرار و قابلیتِ‌اطمینان
- [ ] **۵۴. بکاپ + restore** — dumpِ خودکار + مانورِ restoreِ تأییدشده (PITR-ready). *(devops-engineer)*
- [ ] **۵۵. runbookِ استقرار + اولین staging** — Nginx+HTTPS+compose. *(devops-engineer؛ گِیتِ مالک: VPSِ ایرانی)*
- [ ] **۵۶. observability + نسخه‌بندیِ API** — متریک/خطایاب/uptime + سیاستِ `v1`→`v2` و typegenِ OpenAPI برای کلاینت. *(devops-engineer + api-platform-engineer)*

## خوشهٔ N — رشد و بازار (بعد از محصولِ قابل‌نمایش)
- [ ] **۵۷. Demo Sandbox برای فروش** — تک‌فرمان seed + اسکریپتِ دموی ۹۰ثانیه. *(backend-engineer + marketing-growth-advisor)*
- [ ] **۵۸. Landing + SEOِ فنیِ پایه** — RTL، روایتِ اعتمادِ داده، فرمِ درخواستِ دمو + schema.org (`MedicalClinic`/`SoftwareApplication`)، sitemap، metaِ فارسی، Lighthouse≥۸۰. *(frontend-web-engineer + seo-specialist-advisor)*
- [ ] **۵۹. آنالیتیکسِ privacy-first** — Plausible/Umamiِ self-hosted (نه Google Analytics). *(devops-engineer + marketing-growth-advisor؛ گِیت: VPS)*
- [ ] **۶۰. One-pagerِ فروش + منطقِ قیمت‌گذاری** — فقط آنچه اثبات‌شده؛ روایتِ ارزش‌محور. *(marketing-growth-advisor؛ گِیتِ مالک: قیمت)*

### ریسک‌های فاز (از گردهمایی)
- **A. نشتِ tenant با pooling = قاتلِ ایزولاسیون** (ریسک #۱۱ → قدم ۲۳، ADR-0008). تا حل نشده هیچ poolerِ transaction-mode اضافه نشود.
- **B. متریکِ گمراه‌کننده:** acceptance-rate بدونِ context = rubber-stamping؛ re-engagement بدونِ holdout = همبستگی نه علیت. تا قدم ۴۳، گزارش‌ها «همبستگی» نامیده شوند نه «lift».
- **C. ایمنیِ بالینی:** قاعدهٔ خاموشِ بی‌صدا (قدم ۳۵) و self-reportِ unverified که وارد موتور شود (قدم ۴۵) — هر دو با گاردِ صریح بسته شوند.
- **D. انطباق/بازار:** هر متنِ بازاریابی «هوش/تشخیص» نیازِ بازبینیِ حقوقی؛ قابِ «پیشنهاد — تأیید با پزشک» در همهٔ collateral حفظ شود؛ فقط فیچرِ اثبات‌شده در فروش ادعا شود.

> آخرین به‌روزرسانی: حلقهٔ چهارم — ۴۰ قدم (۲۱–۶۰) قفل؛ **۲۱ (CI)، ۲۲ (بوتِ امن)، ۲۳ (GUC/pooling)، ۲۴ (اسکلتِ وب + رفعِ ریسک #۷) ✅**. بعدی: قدم ۲۵ (`/patients` لیست + جستجو). وضعیتِ هر قدم با ✅ علامت می‌خورد.

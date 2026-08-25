# AGENT KNOWLEDGE BASE — specialist_clinic

> فایل دانش داخلی ایجنت برای اپ «کلینیک تخصصی». تولیدشده در 2026-08-23 با روش دو-موجی:
> **موج ۱:** ۱۵ ایجنت اکتشافی موازی روی حوزه‌های مجزا ← **موج ۲:** ۷ ایجنت راستی‌آزمایی مستقل که ۴۳ ادعای کلیدی را با شواهد `file:line` تأیید/اصلاح کردند.
> نشانه‌ها: ✅ = VERIFIED · ⚠️ = اصلاح/دقت مهم (بخش ۱۹).

---

## 📌 ADDENDUM — 2026-08-23 (جلسهٔ اجرای ۴ جریان؛ در تعارض با متن پایین، این بخش جدیدتر است)

### FO-6 — پیاده‌سازی موجود است، merge نشده
برنچ `origin/feature/foux-v1-fo6-governed-sms` (+۲۳/-۰ روی main HEAD `55a2a5c`): repo/schema/service/api/UI/executor + ۹۱۴ خط تست. ریویو قراردادی: **CONDITIONAL GO** (هر ۱۵ چک revalidation و ۸ red line VERIFIED؛ گپ تستی جزئی: quiet-hours و race موازی). merge منتظر push/PR + CI + UX acceptance مالک. بعد از merge: PROJECT_STATE (۶/۱۱←۷/۱۱)، AGENTS.md FOUX block، plan §9 exit gate آپدیت شوند.

### قواعد بالینی — ۴ بستهٔ DRAFT (مجموع ۱۲۰ قاعده schema-valid)
`docs/clinical_rule_research/{redflags,htn,lipid,t2d}/package/RULE_PACKAGE_*_DRAFT_v0.1.json` = ۱۶+۴۵+۲۴+۳۵ قاعده، همگی jsonschema صفرخطا (وریفای مستقل)، NOT_REVIEWED. فعال‌سازی staged: redflags ← دارو ← تیتریشن؛ هر بسته یک کلیک بازبینی پزشک. داسیه‌های مبدأ: `docs/clinical_rule_research/*/[GUIDELINE_DOSSIER|DOSING_REFRESH]_FA.md` (۴ DELTA در T2D: Jardiance تا 25mg لیبل 10/2025؛ sema خوراکی شروع 3mg؛ sitagliptin باندها؛ ISF=1800/TDD غیر-ADA). روش‌شناسی از برنچ `research/ada-2026-evidence-v0.2` سبک‌شده (بدون قفل‌های zero-output).

### کد اعمال‌شده روی working tree (uncommitted)
- **Stream A:** toggle تک-اپراتور موتور v2 — `simple_activate()`، inline promote در activate('on')، validation خودکار (bound 60min)، حذف distinctness gates (triggerهای attestation/review با DROP+CREATE بازنویسی)، روت `activate-simple`، CLI fix `mapproval_*→approval_*`. seal/append-only/rollback دست‌نخورده. تست‌های مراسم قدیمی بازنویسی + `test_clinical_engine_v2_simple_activate.py`.
- **Stream C فاز ۰:** تک-پوسته — `automation_base.html` **حذف شد**؛ هر ۱۱ صفحه extend base.html؛ هر دو asset در base.
- **فاز ۱ا:** بخش `settings-engagement` در تنظیمات واحد (فرم گاردریل‌ها POST به `engagement_settings`؛ ⚠️ مقادیر ذخیره‌شده نمایش داده نمی‌شوند — route دست‌نخورده، نیاز به تصمیم مالک)؛ هاب پیامک دقیقاً ۳ تب (تأییدها/کمپین‌ها/گزارش)؛ engagement فقط ماتریس routing + breadcrumb به تنظیمات.
- **فاز ۱ب-۱ ✓:** '/' ← redirect صف پزشک؛ هر دو dashboard حذف؛ sidebar جدید؛ control-room/automation-health ← مدیریت/ابزارهای پیشرفته.
- **Cutover worklist ✓ (۹۱۱ تست سبز، 2026-08-24):** unified reads بدون فلگ (گیت GET حذف شد — rollback فقط با revert کامیت؛ env دیگر reads را disable نمی‌کند)؛ worklist.html حذف + 302 shim؛ detail.html لینک‌ها ← مرکز کارها؛ ۹ شکست گذار فیکس شد + `test_worklist_cutover.py` (۵ سناریو). **پک حاکمیتی:** `docs/cutover_governance/` (۴ سند apply-ready — امضای مالک لازم).

### D-ops — وریفای عملیاتی ✓
specialist.db: backup `backups/pre_dops_verify_20260823_172533.db`؛ backfill dry-run سالم (`source_truth_unchanged`)؛ `prepare_seeded_followup_view.py` اجرا شد ← **۸۵ ردیف Projection** (۳۴ ACTION_REQUIRED، RECEPTION=47). فلگ‌ها env-scoped.

### ⚠️ working tree دو لایهٔ uncommitted دارد
لایهٔ WIP مالک از ۸/۲۲ (تم fail-loud ~۲۰ فایل: accounting_bridge، secret_resolver، ...) + لایهٔ ۸/۲۳ ایجنت‌ها (Stream A/C + بسته‌ها). هنگام commit جدا شوند!

### موارد کهنه‌شدهٔ همین فایل
«FO-6 صفر consumer» ← برنچ کامل دارد (merge نشده) · «automation_base.html» ← حذف شده · «dashboard_v1 خانه است» ← در حال جایگزینی با صف پزشک. بقیهٔ بخش ۱۹ معتبر.

### ⏭️ EXACT CONTINUATION POINT (2026-08-24 پایان جلسه)
```text
DONE = Stream A (single-operator toggle) + Frontend کامل (تک-پوسته، خانه=صف پزشک،
       هاب ۳لایه، cutover worklist) + ۱۲۰ قاعده در ۴ بسته + پک حاکمیتی cutover
TESTS = 911 passed / 0 failed
WORKING_TREE = uncommitted، دو لایه (WIP مالک ۸/۲۲ + ایجنت ۸/۲۳-۲۴) — قبل از commit جدا شوند
NEXT-1 (مالک) = جدا‌سازی commit + push/PR برنچ FO-6 → CI → UX acceptance → merge
NEXT-2 (مالک) = امضای docs/cutover_governance/GOVERNANCE_NOTE_CUTOVER_FA.md
NEXT-3 (برادر) = بازبینی staged ۱۲۰ قاعده: redflags ← دارو ← تیتریشن (هر بسته یک کلیک)
NEXT-4 (پس از merge) = آپدیت PROJECT_STATE/AGENTS/ROADMAP از docs/cutover_governance/PROPOSED_*.md + فعال‌سازی staged بسته‌ها
```

---

## ۰. ترتیب اعتماد و منابع حاکم

1. وضعیت واقعی GitHub (`main`, PRها, CI)
2. `../PROJECT_STATE.md` + `../PROJECT_STATE.json` (**در ریشهٔ workspace، نه داخل specialist_clinic**)
3. `AGENTS.md` (specialist_clinic) و ریشه
4. اسناد canonical: `docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md` v1.8.0، `docs/FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md` v1.3.0، `CLAUDE.md`
5. حافظهٔ گفتگو

محیط: `specialist.db = TEST_ONLY / SYNTHETIC_OR_RESETTABLE` — PHI واقعی انتظار نمی‌رود ولی هیچ guardrail ساده نمی‌شود.

## ۱. هویت پروژه

| مورد | مقدار |
|---|---|
| چیستی | Flask + SQLite دسکتاپ مدیریت بیماری مزمن (دیابت/فشار خون)، فارسی RTL جلالی |
| پورت / DB | `127.0.0.1:8090` / `specialist.db` (WAL) |
| ورودی | `start.py` ← Waitress threads=8؛ dev جایگزین: `python src/app.py` |
| پل حسابداری | فقط-خواندنی به `../webapp/clinic_new.db` — کلید اتصال `patient_links.national_id` |
| venv معتبر | `.venv` (Python 3.13) |

درخت دوم workspace: `webapp/` حسابداری (8080) — ارتباط فقط read-only.

## ۲. وضعیت حاکمیتی FOUX-V1

```
FO-0..FO-5 = VALIDATED (پذیرش مالک Emad211)
FO-6      = AUTHORIZED / IMPLEMENTATION PENDING   ← Issue #109، Governance PR #110
FO-7..10  = BLOCKED        پیشرفت = 6/11 = 54.5%
```

- FO-6 scope (plan doc :225-320): policy levels CLINICIAN_ONLY/MANUAL_APPROVAL/AUTO_GUARDED؛ allowlist فقط `appointment_reminder`+`refill_due`؛ purpose فقط CARE؛ TTL 24h کران 1..72h؛ revalidation کامل؛ executor صریح بدون GET/startup send.
- فلگ‌ها: ۱۰ عدد در `src/config/settings.py:14-25,78-91` همه default OFF. ✅ **FOLLOWUP_SMS_AUTO_GUARDED صفر consumer دارد در src/** — FO-6 واقعاً شروع نشده.

## ۳. معماری و Bootstrap

لایه‌بندی اجباری: `api/ (route+auth) → services/ (قواعد) → adapters/sqlite/ (تمام SQL)`.

create_app (`src/app.py:30-527`) ترتیب: frozen-detect :32-39 ← config ← audit-marker :49-53 ← SECRET_KEY policy (PRODUCTION+کلید ضعیف=RuntimeError :55-66) ← session cookies :75-83 ← csrf :84 ← teardown :90 ← logging چرخشی :92-104 ← schema بحرانی :106-121 ← user-loader/context :123-138 ← **۱۸ blueprint به همین ترتیب** :163-183 (auth, dashboard, patients, clinical_reconciliation, clinical_alerts, vitals, appointments, followups, unified_followups, finance_review, sms, manager, hypoglycemia_shadow_monitor, control_room, ext, doctor_queue, patient_card, health) ← گیت first-run :185-212 ← فیلترها :214-243 ← CLI clinical-v2 :254-425 ← error handlers ← Scheduler :511-526.

God nodes گراف: get_db(673) create_app(176) iran_now(161) SmsRepository(109) log_activity(108).

## ۴. لایهٔ دیتابیس ✅

- `get_db()` per-request روی g._database (:563,:576). PRAGMA: foreign_keys=ON :578, busy_timeout=10000 :581, WAL/NORMAL/autocheckpoint غیر-memory :582-585.
- bootstrap: executescript(schema.sql) :594 ← _run_migrations :595 ← _ensure_default_admin :596 ← schema_contract_ok (۳ اندیس بحرانی) :597-600 ← _initialized. (برای :memory:/مسیر جدید re-run.)
- الگوی migration: `_ensure_column` (:85-91) = PRAGMA table_info ← ALTER ADD. دامنهٔ جدید ← ماژول `<x>_schema.py` با `ensure_<x>_storage(db)` idempotent + trigger + fail-loud، wire در _run_migrations.
- ⚠️ schema modules lazy خارج core: followup_projection/episode، clinical_context — ممیزی باید `*_schema.py` را ببیند.
- `patient_links` جدول بیمار است (جدول `patients` وجود ندارد؛ تنها CREATE TABLE patients در فیکسچر تست/سلف‌تست سمت حسابداری است).
- جداول پیامک/فلگ/v2/اقتصاد همگی append-only با trigger RAISE(ABORT).
- ⚠️ `clinical_rules` و `suggestion_log` در schema canonical نیستند (v2 جایگزین شد).

## ۵. نقشهٔ HTTP (~133 endpoint)

| Blueprint | Prefix | نکته |
|---|---|---|
| auth | /auth | setup عمومی فقط-loopback→403؛ manager_required = alias SECURITY_GRANT_MANAGE :77 |
| dashboard | root | GET / + POST /finance/reconcile [OPERATIONAL_HEALTH_VIEW] |
| patients | /patients | 32 روت؛ sms-consent [SMS_CONSENT_MANAGE]؛ ۴ mutation توسط guards جایگزین |
| unified_followups | /followups/unified | نردبان فلگ READONLY←ACTIONS←ROUTING←CONTACT هرکدام abort404 (:49-69) |
| sms | /sms | POST /sms/api/check [SMS_CAMPAIGN_CREATE]؛ approvals [SMS_APPROVAL_REVIEW] |
| ext | /api/ext | Bearer-only + origin allowlist (ep.tamin.ir/localhost) + rate 60/min؛ captured @csrf_exempt |
| patient_card | /card | عمومی GET-only، gate default OFF، rate 30/min، 404 generic |
| health | /health | live/ready عمومی (ready بدون جزئیات + اجرای ensure_*)؛ details [OPERATIONAL_HEALTH_VIEW] |
| doctor_queue | /doctor-queue | ⚠️ هیچ polling JSON ندارد — server-rendered |

گاردهای جهانی: before_app_request enforce_effective_route_permissions + گیت first-run.

## ۶. موتور بالینی v2 (گیت‌شده) ✅

محل: `src/services/clinical_engine/` + `src/domain/clinical_engine/` (+schemas سه‌گانه؛ ruleset.schema جدا ندارد) + repos adapters.

Pipeline capture: load_bundle(SAVEPOINT) ← Legacy/Reconciled adapter ← FactBuilder.build (snapshot فروزن sha256) ← RuleCompiler.compile (jsonschema+freeze) ← ContextualRuleEvaluator ← SafetyKernel (PREFLIGHT→SAFETY→ROUTINE، abstain نامشخص) ← ConflictResolver (dedup فقط semantic_key؛ تضاد action-type=withhold همه) ← RecommendationComposer (DTO خنثی؛ هرگز تجویز/mutate/task) ← AuditRepository persist (append-only).

گیت fail-closed (همه VERIFIED):
- get_mode ناشناخته/بی-seal ⇒ "off" (fact_repo:79-91)
- approve نیازمند report_hash منطبق گزارش PASS معتبر (activation.py:471-478)
- activate("on") نیازمند seal on_selected + rollout verification + ruleset ACTIVE (:535-553)
- نوشتن seal خودکار checkpoint audit bind + re-hash — قابل عبور نیست (activation_repo put_json:114-147)
- assert_current_rollout_contract: mode/raw/version/ruleset_id(context∧seal)/revision==clinical_data_revision/hash64/valid_seal (:48-91)
- Shadow: off یا on_selected خارج TEST0001..0010 ⇒ None (fact_builder:288-305)
- CLI: `flask --app src.app clinical-v2 {compare,status,approve,activate,verify-selected,promote-ruleset,rollback}`

چرخه: off/shadow → on_selected → on. rollback فوری، audit حفظ.

## ۷. موتور v1: بازنشسته ✅

- rule_engine.py سنگ‌قبر: evaluate()=[] (:58)، فقط shadow-capture. نگهبانان: test_v1_runtime_retired (صفر consumer)، test_parallel_clinical_logic_retired.
- بازنشسته (بازیابی از git): THRESHOLDS hba1c 7/8 fbs 130/180 sys 130/140 dia 80/90 (c689bca)؛ TARGETS {7,130,130,80} و ماشین‌حساب انسولین basal 10U یا 0.1–0.2U/kg، bolus=round(0.1×basal) یا 4U (99e85f3)؛ seed 76 قاعده DSL (da2956d).
- مرجع فعلی فقط متنی: docs/clinical_reference.md و ada_t2_rules.md (ریشه، بخش ۰–۱۲، FROZEN).
- /manager/rules = redirect به clinical_engine؛ فقط metadata توصیفی قابل ویرایش.

## ۸. FOUX-V1 Orchestration ✅

| FO | تحویل | آرتیفاکت |
|---|---|---|
| 0 | حاکمیت/baseline/فلگ‌ها | settings.py، scripts/capture_followup_fo0_baseline.py |
| 1 | Episode identity+backfill | backfill+identity، episode_schema/repo |
| 2 | Projection سایه+Next Action | projection_service+next_action_policy+source_state، projection_repo |
| 3 | Worklist یکپارچه read-only | read_model+timeline_service، unified_worklist.html |
| 4 | Claim/Routing/SLA مؤثر | ownership_service (event-stream مشتق، claim اتمیک one-winner)؛ SLA request-time بدون write |
| 5 | تماس ساختاریافته | structured_contact_service: ۹ outcome، RETRY_THRESHOLD=3 روی NO_ANSWER/BUSY؛ followup_contact_events=منبع حقیقت |
| 6 | SMS خودکار governed | فقط scope سند؛ صفر کد |

- Worklist یکپارچه فقط از cache پروجکشن می‌خواند؛ readiness هرگز auto-rebuild نمی‌کند (PROJECTION_EMPTY_WITH_SOURCE_DATA گزارش می‌شود).
- بازیابی seed: `$env:FOLLOWUP_PROJECTION_SHADOW="1"` سپس `scripts\prepare_seeded_followup_view.py --database specialist.db` (بدون فلگ hard-fail).
- start_fo5_local_review.ps1: ۶ فلگ ON / ۴ OFF (شامل AUTO_GUARDED) با backup خودکار DB.

## ۹. سامانهٔ پیامک ✅ (+ اصلاحات مهم)

- Provider: Kavenegar پیش‌فرض فعال (key در URL path)؛ Mediana selectable legacy (X-API-KEY). Timeout←SubmissionUnknown (هرگز failed/retry خودکار). بی‌کلید: NullProvider در TESTING، وگرنه UnconfiguredProvider fail-closed.
- Consent: sms_consent_events append-only؛ CARE default GRANTED، MARKETING default REVOKED؛ require_allowed پیش از هر ارسال + stale-guard.
- Guardrails: quiet 08:00–21:00 تهران؛ daily cap default 1 (کران 1..10) دو-لایه‌ای (require_allowed + داخل تراکنش create_message←SmsDailyCapExceeded)؛ cooldown per-event default 30d.
- **⚠️ اصلاح حاکمیت ارسال:** SMS engagement/per-patient الزاماً از صف تأیید پزشک engagement_approvals (claim اتمیک pending←submitting؛ approve دوباره consent/guardrail/provider). اما **کمپین تأیید per-message پزشک ندارد**: GovernedCampaignExecutionService.run فقط quiet-hours/lifecycle(DRAFT,SCHEDULED,FAILED,PREPARING قابل اجرا)/provider/claim-token/consent-per-member. مسیر مستقیم: scheduler `_run_due_campaigns` خودکار کمپین scheduled سررسیده می‌فرستد (scheduler.py:331-342) و روت دستی فقط Permission.SMS_CAMPAIGN_SEND می‌خواهد.
- Trigger submission-governance روی message_id+allowed_at_submission=1+GRANTED+provider_name است (نه patient+purpose).
- Reconciliation provider-affine هرگز resubmit نمی‌کند؛ stale بعد 72h←StatusUnknown.
- اقتصاد A6: attribution فقط response مثبت + صریح به Journey. قرارداد عملگر CLAUDE_A6.md.

## ۱۰. پل حسابداری و مالی ✅

سه لایهٔ read-only: URI mode=ro (bridge:76) + query_only=ON (adapters) + probe منفی نوشتن در validate() + تست SHA-256 روی DB واقعی (TestScenario7ZeroWrite — skipif نبودِ DB).
Path precedence: env ACCOUNTING_DB_PATH > setting accounting_db_path > app-config > Config fallback؛ save() با env قفل.
خطاها: AccountingBridgeError/Unavailable/QueryError(503). fetch_closed_invoices fail-loud — cursor فقط بعد batch موفق.
InvoiceSync: cursor invoice_sync_last_id، floor 30d، ledger idempotent؛ outreach thank_you once-per-work_date + keyword map (ear_wash/wound_care) ← صف تأیید.
DoctorQueue: canonical_snapshot هر بار re-read از حسابداری؛ walk-in فقط doctor_visit_log؛ day-guard OUTSIDE_ACTIVE_DAY.
A7/A8: reconcile یک BEGIN IMMEDIATE (observation+payer evidence+lineage snapshot sha256 supersedes-chain). ADR-0005: visibility≠attribution.

## ۱۱. جریان‌های دامنه ✅

- **ثبت‌نام:** `SpecialistProgramEnrollmentService.enroll_from_accounting` (idempotent، BEGIN IMMEDIATE: link+cutover+sms defaults). Manual هرگز لینک حسابداری را استنتاج نمی‌کند. ⚠️ `_complete_enrollment` وجود ندارد.
- **نوبت دوره‌ای:** completion-driven در mark_done (base+N ماه، parent_appointment_id) — cron ندارد.
- **Vitals/labs:** VITAL_TYPES دقیقاً ۷ نوع (bp_systolic/bp_diastolic/fbs/hba1c/weight/bmi/pulse)؛ latest_by_type ⚠️ lab_results را برای **هر test_key غیرخالی** merge می‌کند (نه فقط hba1c/fbs). سرویس DESCRIPTIVE_ONLY.
- **کارت عمومی ADR-0004:** token_urlsafe(32)، TTL 8h، صدور جدید قبلی را revoke؛ CARD_VITALS=fbs/sys/dia (بدون HbA1c خام)؛ 404 generic برای expired/revoked/missing.
- **فلگ‌ها bitemporal:** effective_at/recorded_at + CHECK، supersession یک-فرزند، append-only triggers در clinical_flag_history_schema.py؛ ویرایش POST /patients/<pid>/flags با optimistic concurrency (expected_event_ids).
- flag_catalog: 18 فلگ seed (ascvd, cvd_high_risk, hf, hf_type, hf_symptomatic, ckd_stage_g/a, hypo_risk, masld, mash_biopsy, pregnancy, childbearing_no_contraception, smoking, frailty, metabolic_surgery, monofilament, eye_exam_date, foot_exam_date).
- **Hypoglycemia Shadow:** فقط دو ledger خودش؛ وضعیت PAUSE فقط در root PROJECT_STATE pair (md:22، json:430).
- **Cockpit:** pure composer بدون SQL؛ سه-وضعیتی v2 (OFF/UNAVAILABLE/RAN) تا غیبت تحلیل = all-clear رندر نشود.
- **CareJourney:** start_accounting_visit با guard های fail-closed (SPECIALIST_CUTOVER_MISSING, ACCOUNTING_IDENTITY_MISMATCH, INVOICE_NOT_OPEN, ...).

## ۱۲. مدل امنیتی ✅

- Auth: bcrypt rounds=12؛ migration خودکار legacy werkzeug hash بعد لاگین موفق (:55-67)؛ lockout ۵←15min (کانتر reset هنگام lock)؛ پیام خطای generic.
- Tokens افزونه SECU-05: rotate→token_urlsafe(24)، TTL 90d؛ مصرف فقط `Authorization: Bearer` (هرگز query/body)؛ NULL expiry=legacy مجاز.
- Rate limit SECU-13: `allow(key, limit, per_seconds=60)` پنجرهٔ لغزان in-process thread-safe؛ reset() تستی.
- First-run: wizard فقط loopback؛ admin/admin قدیمی با must_change_password مسدود؛ بدون رمز پیش‌فرض.
- CSRF: src/security/csrf.py (auto-inject فرم POST؛ csrf_exempt فقط ext/captured).
- Activity log fail-loud: شکست ← marker `<db>.activity-audit-degraded.flag` + extensions["activity_audit_healthy"]=False؛ ack: `start.py acknowledge-audit-gap --confirm ACKNOWLEDGE-ACTIVITY-AUDIT-GAP`.
- Backup: Scheduler lease `specialist-clinic:scheduler` (TTL 1800s/beat 60s)؛ شنبه 03 ← BackupIntegrityService.create (online-backup+integrity_check+sha256 manifest+atomic replace+keep=4). restore drill با confirm phrase و pre_restore snapshot.
- Permissions: Permission StrEnum ~40 کلید؛ manager=all/staff=subsidiary؛ resolved_permissions fail-closed (خطای storage←empty frozenset)؛ overrideهای append-only security_permission_events.

## ۱۳. فرانت‌اند ✅

- Shell: base.html (RTL dark) + automation_base.html برای صفحات بازطراحی‌شده. ۴۸ template.
- Vendor JS محلی (بدون CDN): jquery/persian-date/persian-datepicker/chart.umd در static/vendor.
- window.CLINIC_THEME در base.html (:133-137): tick/grid/text/primary/ok/warn/danger/info/violet/font + Chart.defaults سراسری.
- فیلترها (app.py:214-243): `jalali`, `jalali_date`, `fa_num`. ⚠️ فیلتر `.jdate` وجود ندارد — کلاس input است.
- input.jdate auto-init: persianDatepicker format YYYY/MM/DD، initialValue:false، observer:true، دکمهٔ امروز.
- Double-submit guard سراسری (capture-phase، e.submitter mirror، aria-busy، بازیابی 8s).
- توکن‌ها: بدون hex خام؛ کنترل‌ها --control-sm/md/lg=36/42/48؛ .btn-secondary در CSS هست ولی در markup ممنوع؛ آیکون sprite #i-NAME با aria-label.
- IA guards: test_ui_information_architecture.py دقیقاً ۱۶ تست (one-home-per-capability).

## ۱۴. تست‌ها ✅ (+۲ اصلاح)

- 116 فایل test_*.py + ۱ support module (clinical_engine_current_test_support.py). ~801 تست در CI (801 Specialist + 54 Accounting).
- اجرا: `.\.venv\Scripts\python.exe -m pytest tests -q` از specialist_clinic.
- ⚠️ conftest.py پروژه‌ای وجود ندارد (فقط یک کپی third-party در .venv site-packages PyInstaller). هیچ pytest.ini/pyproject/setup.cfg هم نیست.
- ⚠️ `_flush_src_modules` در ۱۱ فایل تست تکرار شده (نه ۱۲+)؛ Config در class-body bake می‌شود پس حذف src.* از sys.modules لازم است.
- الگو: create_app({TESTING, DATABASE_PATH tmp_path, BACKUP_FOLDER, SECRET_KEY}) + core._initialized=False + _make_acc_db/fake_acc_db (جدول‌های patients/invoices/visits/injections/procedures) + env swap ACCOUNTING_DB_PATH.
- cohort TEST0001..0010 در pytest خودکار seed نمی‌شود (فقط CLI seed_demo_data.py).
- A-numbers: A1 at-least-once sync | A2 backup | A3 logging | A4 deploy capstone | A5 SMS governance | A6 economics | A7 payer adjustments | A8 service lineage | A9 encounter documentation | A10 plan commitments | A11 package intake | A12 rule library tranche | A13 dual review | A14 CI zero-baseline | A15 release readiness.
- Invariantهای enforced: descriptive-only سطوح غیر-v2؛ no-legacy-fields؛ append-only؛ fail-closed (bridge failure='unknown' نه صفر؛ engine off≠all-clear)؛ zero-write SHA-256 به clinic_new.db واقعی؛ isolation بالینی/اداری.

## ۱۵. شاخص اسناد docs/ (43 فایل)

| سند | نقش/وضعیت |
|---|---|
| FOLLOWUP plan v1.8.0 + roadmap v1.3.0 | ACTIVE canonical FOUX |
| RELEASE_RUNBOOK.md (A15) | STALE_DIVERGED_DRAFT — مرجع فقط |
| clinical_engine_hardening_plan.md | ACTIVE/GATED (فاز ۰..۷ + ترتیب PRها) |
| engagement_engine_plan.md | قفل‌شده (تأیید مالک) |
| treatment_engine_plan.md | طرح روی ada_t2_rules.md فریز |
| DESIGN_SYSTEM.md / deploy_checklist.md / kavenegar_reference.md | ACTIVE اجباری عملیاتی |
| a12 tranche + intake_contract | DRAFT/QUARANTINED |
| hypoglycemia_shadow_*.md | PAUSED_FOR_RECONCILIATION |
| ci_zero_baseline_a14 / a13 governance | ACTIVE evidence/governance |

⚠️ فقط ADR-0005 فایل دارد؛ ADR-0002/0003/0004 referenced-but-unfiled. بستهٔ `../clinical_engine_v2_research/` فقط design-input است، authority runtime نمی‌دهد.

## ۱۶. ابزار Build/Seed/Deps ✅

- build_release.ps1 ترتیب واقعی: venv-check ← pip install requirements-build.lock ← **source self-test** ← pytest tests -q --tb=short ← cleanup ایمن dist/build/release ← pyinstaller --noconfirm --clean spec ← **frozen exe self-test** ← zip + .sha256.
- Spec datas دقیقاً ۵ مورد: templates/static/schema.sql/clinical_engine/schemas/rule_artifacts؛ hiddenimports jsonschema+segno+segno.helpers+waitress-submodules؛ excludes pytest.
- seed_demo_data.py: بدون CLI arg؛ DemoCohortService.ensure(force=True)+DemoSeedFollowupPreparationService.run؛ deterministic کامل بدون RNG؛ version "2026.07-longitudinal-v2"، reference 2026-07-22 08:00؛ گریدها vitals/2mo visits/3mo labs/6mo؛ کنترل‌های مثبت ایمنی: TEST0008 BP نهایی 184/112 (red-flag)، TEST0010 متفورمین فعال با eGFR 24 (تعارض دارویی عمدی)، TEST0007 frail high-hypo-risk، TEST0009 prediabetes منفی؛ جایگزینی فقط TESTxxxx.
- Deps chain: requirements.in (7 مستقیم unpinned: Flask bcrypt jdatetime segno requests jsonschema waitress) → requirements.lock (25 pin Python3.13) → requirements.txt (= -r lock) → requirements-build.lock (lock + pyinstaller 6.15.0 + pytest 9.1.1).

## ۱۷. قراردادهای مشترک «هرگز نشکن» ✅

1. زمان: فقط `utils.iran_now()` یا معادل SQL `datetime('now','+3h','+30m')`. هرگز datetime.now()/UTC خام.
2. تاریخ: ذخیرهٔ Gregorian 'YYYY-MM-DD'؛ ورودی UI جلالی با jalali_to_gregorian_str (None=fail باید handle شود)؛ نمایش با |jalali_date؛ رقم فارسی فقط با fa_num در رندر.
3. جدول immutable جدید: جفت canonical_json/content_hash عیناً (sort_keys+compact+sha256) + append-only + supersedes/expected_event_id.
4. endpoint جدید governed: ثبت در route_policy._ENDPOINT_PERMISSIONS با Permission enum؛ fail-closed.
5. فلگ جدید: settings.py FOLLOWUP_ORCHESTRATION_FLAGS tuple، default OFF.
6. SQL هرگز در api/؛ الگوی غالب repos است (۳۶/۹۰ فایل سرویس SQL دارند — الگوی موجود اما خلاف قانون اعلامی؛ جدیدها repo بسازند).
7. سطوح غیر-v2 فقط descriptive: هیچ threshold/target/classification جدید خارج موتور v2.
8. Template: extends base/automation_base؛ token-based colors؛ RTL/Jalali حفظ؛ بعد از تغییر template تست IA اجرا شود.

## ۱۸. دستورات پرکاربرد

```powershell
# اجرا
.\.venv\Scripts\python.exe start.py                 # http://127.0.0.1:8090
# تست
.\.venv\Scripts\python.exe -m pytest tests -q
# seed cohort (بازسازی TEST0001..0010)
.\.venv\Scripts\python.exe seed_demo_data.py
# recovery نمای followup
$env:FOLLOWUP_PROJECTION_SHADOW="1"
.\.venv\Scripts\python.exe scripts\prepare_seeded_followup_view.py --database specialist.db
# engine v2
.\.venv\Scripts\python.exe -m flask --app src.app clinical-v2 status --format json
.\.venv\Scripts\python.exe -m flask --app src.app clinical-v2 compare --as-of 2026-07-22T12:00:00 --actor qa-reviewer --format text
# release
.\scripts\build_release.ps1                          # (-SkipInstall/-SkipTests)
# backup/restore
.\.venv\Scripts\python.exe start.py backup
.\.venv\Scripts\python.exe start.py restore-backup backups\<file> --confirm RESTORE-SPECIALIST-DATABASE
```

## ۱۹. دفتر اصلاحات راستی‌آزمایی (موج دوم)

| # | ادعای اولیه | حکم | واقعیت تأییدشده |
|---|---|---|---|
| 1 | کمپین پیامک بدون تأیید پزشک ارسال نمی‌شود | REFUTED | کمپین: lifecycle+consent+guardrail کافی است؛ scheduler کمپین scheduled را خودکار می‌فرستد؛ روت دستی فقط Permission. تأیید per-message فقط engagement/per-patient |
| 2 | Trigger submission-governance روی patient+purpose | PARTIAL | روی message_id+GRANTED+allowed+provider |
| 3 | latest_by_type فقط hba1c/fbs از labs | PARTIAL | هر test_key غیرخالی |
| 4 | PAUSED_FOR_RECONCILIATION فقط md:22 | دقت | md:22 + json:430 (root pair) |
| 5 | _flush_src_modules در 12+ فایل | REFUTED | دقیقاً ۱۱ فایل |
| 6 | conftest.py هیچجا نیست | دقت | پروژه‌ای ندارد؛ copy third-party در .venv/site-packages |
| 7 | THRESHOLDS/TARGETS/insulin-calc در کد | VERIFIED-retired | بازنشسته؛ مقادیر فقط git-history/docs |
| 8 | `_complete_enrollment` | REFUTED | نام وجود ندارد؛ enroll_from_accounting واقعی است |
| 9 | analytics_service TARGETS map | REFUTED | حذف شده؛ DESCRIPTIVE_ONLY (:183,:289) |
| 10 | doctor_queue polling endpoints | REFUTED | هیچ JSON poll؛ server-rendered |
| 11 | `.jdate` فیلتر Jinja | REFUTED | فقط کلاس HTML input؛ فیلترهای واقعی jalali/jalali_date/fa_num |
| 12 | `.project_flags` فایل | REFUTED | وجود ندارد در workspace |
| 13 | ADR-0002..0004 فایل دارند | دقت | فقط ADR-0005 فایل دارد؛ بقیه referenced-but-unfiled |
| 14 | PROJECT_STATE در specialist_clinic | دقت | در root workspace است |
| 15 | bootstrap یک‌بارِ مطلق | دقت | :memory:/تغییر مسیر re-run می‌کند |

## ۲۰. نقشهٔ سریع فایل‌های کلیدی

```
src/app.py                     create_app + CLI clinical-v2
src/config/settings.py         config + فلگ‌ها
src/api/*                      18 blueprint
src/services/*                 90 ماژول (clinical_engine/, sms/, followup_orchestration/)
src/adapters/sqlite/core.py    get_db + migrations
src/adapters/accounting_bridge.py   پل read-only
src/security/{permissions,route_policy,csrf}.py
src/common/{utils,jalali,validators,rate_limit,network_policy}.py
tests/                         117 فایل (بدون conftest)
scripts/build_release.ps1      release
seed_demo_data.py              cohort
docs/                          43 سند
ada_t2_rules.md                مرجع ADA (ریشه)
CLAUDE.md / CLAUDE_A6.md       راهنمای ایجنت + قرارداد A6
../PROJECT_STATE.{md,json}     وضعیت حاکم workspace
```


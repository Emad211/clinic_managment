# halqe — نقشهٔ راهِ MVP (از قدم ۶۸ تا اولین کلینیکِ پایلوت در پروداکشن)

> این سند ادامهٔ [`ROADMAP.md`](ROADMAP.md) است (که در قدم ۶۸ / خوشهٔ Q تمام شد) و مسیر را
> تا **پایانِ MVP** قفل می‌کند. روشِ ساخت: **شورای ۱۶ مشاوره در ۲ دورِ مذاکره** (Opus 4.8) →
> **سنتزِ مستقلِ من** → **پنلِ ۸ منتقدِ خصمانه (دور ۳)** → سنتزِ نهایی پس از **راستی‌آزماییِ کد**.
> دو سطح: نقشهٔ کلانِ قدم‌ها همین‌جاست؛ **ساب‌تسک‌های هر قدم هنگامِ رسیدن به آن قدم پروارتر و
> دقیق‌تر می‌شوند** (هر قدم یک افزایشِ منسجم، مستقل‌کامیت‌شدنی، کاملاً آزمون‌پذیر).

## تعریفِ «پایانِ MVP» (اجماعِ کامل)
**یک** کلینیکِ پایلوتِ واقعی که halqe را **در پروداکشن روی زیرساختِ ایرانی** اجرا می‌کند و
**حلقهٔ مراقبت را روزانه روی بیمارانِ واقعیِ خودش** می‌گرداند (پذیرش/ویزیت → اندازه‌گیری → پیشنهاد
→ پیگیری → تعامل از طریقِ worklist) — **به‌شکلِ ایمن**: ایزولاسیونِ داده **اثبات‌شده**، وبِ
در‌دسترس روی TLS، **schedulerِ تعامل که واقعاً در پروداکشن tick می‌زند**، کارکنانِ onboard‌شده،
و مبنای **حقوقی + تجاریِ امضاشده**. **Billing = موکول به فاکتورِ دستیِ امضاشدهٔ مالک** (نه ماژول،
نه درگاه). **SMS = موکول به NullProvider + fallbackِ worklist** (KYC بیرونی است؛ MVP را بلاک نمی‌کند).
معیار = «کلینیکِ متعهد می‌تواند **ایمن** کارِ روزانهٔ مراقبتِ مزمن را انجام دهد» — نه feature-complete.

## اصولِ مقدس (شکستن ممنوع — از ROADMAP.md ادامه دارد)
مرزِ حسابداری فقط‌خواندنی؛ موتور suggestion-only (تصمیم با پزشک، لاگ می‌شود)؛ دادهٔ **تأییدنشده هرگز
واردِ موتور نمی‌شود**؛ هیچ پیامکِ واقعی تا KYC (NullProvider)؛ هیچ PHI در URL/SMS؛ Jalali + زمانِ
ایران؛ migrationهای **برشِ numericِ افزایشیِ idempotent** (managed=False، هرگز فرضِ DBِ تازه)؛
آفلاین (بدونِ CDN)؛ **هرگز عددِ پیامد یا تأییدِ بالینی جعل نشود**؛ مراقبت و red-flag هرگز دریغ نمی‌شود؛
**اپِ حسابداریِ پروداکشن (`webapp`) باید سالم بماند**.

## آنچه از MVP حذف شد (اجماع — موکول به پس از پایلوت)
1. ماژولِ Billing/Subscription + درگاهِ پرداخت → فاکتورِ دستی؛ `slice17` فقط در کلینیکِ دوم.
2. فعال‌سازیِ خط‌به‌خطِ کاملِ RLS + auditِ مستأجرِ دوم → کلینیکِ دوم (T1)؛ جایش = تضمینِ تک‌مستأجر + تستِ نشت.
3. ارسالِ واقعیِ SMS → NullProvider + fallbackِ worklist (KYC، بیرونی).
4. مسیرِ اینترنتیِ کارت / WireGuard / PWAِ عمومی → فقط LAN/QRِ درون‌کلینیکی.
5. بازنویسیِ set-based analytics → تریگرِ داده (>۵۰۰ بیمار / >۵۰هزار obs / p95>۸۰۰ms).
6. فعال‌سازیِ CI Actions → خوب ولی روی مسیرِ ایمنیِ پایلوت نیست.
7. **wizardِ self-serve onboarding** و **APIِ users-create/clinic-profile** → برای پایلوت CLI کافی است؛ به کلینیکِ دوم موکول.
8. per-population red-flag auto-approve (قدم ۳۹) → sign-offِ بالینی؛ پایلوت per-patient suggestion-only می‌ماند.
9. پلِ نسخهٔ بیمه → owner-blocked، خارج از scope (مسیرِ نسخهٔ آزاد کافی است).
> توجه: **seedِ طولیِ واقع‌گرایانهٔ تست** حذف **نشده** (قدم S6/۷۴) — یک fixtureِ یکپارچگیِ سنجش است، نه «demo seed».

---

## خوشهٔ R — گِیت‌های مالک و کاغذِ تجاری/حقوقی  (مالک‌محور، موازی؛ بلاک‌کنندهٔ گام‌های PHIِ واقعی، نه کد)

> پیش‌نویسِ الزاماتِ R4 را **من همین‌حالا و موازی** می‌نویسم؛ فقط نهایی‌سازیِ وکیل + امضا گِیت است.

### 69 (R1) گِیتِ زیرساختِ مالک  [OWNER GATE]
مالک VPSِ ایرانی + گواهیِ TLS + رکوردِ DNS + فایروال (۸۰/۴۴۳ باز، ۸۰۰۰/۵۴۳۲ بسته) + **مقصدِ
بکاپِ cron که رمزنگاری‌شده/دسترسی‌محدود + نسخهٔ off-box است** را provision می‌کند. تنها گِیتِ مسیرِ بحرانیِ زیرساخت.

### 70 (R2) تصمیم‌های مالک، مکتوب  [OWNER GATE]
(الف) defer billing → فاکتورِ دستی؛ (ب) defer SMS → NullProvider + fallbackِ worklist؛ (ج) **پذیرشِ
کتبی** که پنل‌های پیامدِ بالینی ماه‌ها NULL می‌خوانند و تنها ادعای دفاع‌پذیرِ پایلوت = متریک‌های پذیرش +
incrementalityِ holdout است (نه efficacy/ROI). بخشِ کد (consent AND-clause، NULL-graceful) قبلاً در S آماده می‌شود؛ فقط این تصمیم‌ها owner-gate‌اند.

### 71 (R3) انتخابِ پایلوت + ورودی‌های تجاری + LOI  [OWNER GATE]
مالک کلینیکِ پایلوت + **نقشهٔ امضاکننده** (مدیر / پزشکِ‌مالک / حسابدار) + championِ روزِ اول را انتخاب
می‌کند؛ اعدادِ قیمت + واحدِ ارز (rial/toman، ADR-0007) + تعریفِ «بیمارِ مزمنِ فعال» + مبنای pass-throughِ
هزینهٔ پیامک را قفل می‌کند؛ و **یک LOI/تعهدِ تجاری (حتی غیرالزام‌آور) با triggerِ تبدیل به پولی** پیش
از سوختنِ هفته‌های مهندسی گرفته می‌شود (ریسکِ «پایلوتِ رایگانِ بی‌پایان»).

### 72 (R4) بستهٔ حقوقی + قراردادِ امضاشده  [OWNER GATE — گِیتِ سختِ پیش از اولین PHIِ واقعی]
من الزامات را پیش‌نویس می‌کنم؛ **وکیلِ دارای پروانهٔ ایرانی** نهایی می‌کند؛ کلینیک **پیش از ورودِ هر
بیمارِ واقعی** امضا می‌کند: قراردادِ SaaS + DPA (controller=کلینیک / processor=halqe، مالکیتِ داده،
خروج/نگهداری، **وظیفهٔ اطلاع‌رسانیِ نقض + بازهٔ زمانی**، مجوزِ صریحِ خواندنِ پلِ read-only حسابداری،
قابِ مسئولیتِ suggestion-only، تعهدِ ایزولاسیونِ چندمستأجری، **بندِ تبدیل به پولی** + اجازهٔ
reference-case، قابِ wallet=اعتبار) + متنِ رضایتِ بیمار (**رضایتِ پردازشِ داده** و **رضایتِ پیامک**،
هر دو affirmative نه opt-out) + privacy notice. (مشورتی — جایگزینِ وکیل نیست.)

## خوشهٔ S — کفِ ایمنی  (کد؛ **اول از همه**؛ بدونِ گِیتِ مالک — بیشترش موازی و infra-مستقل)

### ✅ 73 (S1) auditِ پوششِ RLS + اثباتِ رولِ کم‌امتیاز  [⚠️ پرریسک — اولین قدمِ کدیِ کلِ MVP] — کامیت `452bcca`
> **تصحیحِ مهم (راستی‌آزماییِ کد):** فرضیهٔ «enable-loopِ slice5 قبل از slice7..16 اجرا شده پس جداول
> RLS خاموش دارند» **نادرست** است — راستی‌آزمایی شد: slices ۸/۹/۱۰/۱۲/۱۳ خودشان inline RLS را
> ENABLE می‌کنند؛ slice11 فقط **ستون** به `patient_links` (که از قبل تحتِ سیاستِ slice5 است) اضافه
> می‌کند؛ و `platform.*` (شاملِ `platform.settings`/slice16) **عمداً بدونِ RLS** است و
> tenant-scopingِ **سطحِ‌اپلیکیشن** (WHERE tenant_id) دارد. پس این قدم یک **auditِ تجربی** است، نه «رفعِ یک خاموشیِ سیستمیِ شناخته‌شده».
- **ساب‌تسک:** روی PGِ local/staging که تا head اعمال شده (برش‌های ۰..۱۶): assert که **هر جدولِ
  `clinical.*` دارای ستونِ tenant_id**، relrowsecurity + relforcerowsecurity + سیاستِ `tenant_isolation`
  دارد؛ برای `platform.*` (users/tenants/settings) **تأیید کن** که scopingِ سطحِ‌اپ سازگار است و هیچ
  PHIِ بالینی آنجا نیست. اگر — و فقط اگر — auditِ تجربی یک جدولِ `clinical.*`ِ پوشش‌نداده یافت، یک
  enable-loopِ idempotentِ canonical به‌عنوانِ **آخرین برش** اضافه کن (DROP POLICY IF EXISTS …).
- **+ اثباتِ رولِ کم‌امتیاز:** دستورِ `ensure_app_role` از قبل وجود دارد (قدم ۱/خوشهٔ A) — این قدم آن
  را روی staging/prod **اجرا و تأیید** می‌کند که `platform_app` فاقدِ BYPASSRLS/SUPERUSER و non-owner
  است (بدونِ آن FORCE RLS بی‌اثر است). این پیش‌نیازِ هر تضمینِ RLS است.
- **پذیرش:** گزارشِ audit صفر جدولِ بالینیِ پوشش‌نداده؛ رولِ اپ بدونِ BYPASSRLS اثبات‌شده.
- **✅ انجام شد (کامیت `452bcca`):** تنها جدولِ پوشش‌نیافته = `platform.settings` بود → inline RLS+FORCE+tenant_isolation
  در slice16 افزوده شد (داوریِ من بینِ security[afzudan] و data-architect[allowlist]: دفاع‌در‌عمق). `test_rls_coverage.py`
  (۶ تست) با allowlistِ **خالی** سبز شد → اثباتِ تجربیِ پوششِ کاملِ clinical+platform. بازبینیِ من: backend **703**/۱skip،
  guard **118**، slice16 دوبار idempotent روی DBِ populated.

### ✅ 74 (S2) تستِ نشتِ بین‌مستأجری + تضمینِ تک‌مستأجر (prod config) — کامیت `430538e`
گسترش/اجرای `test_e2e_tenant_isolation` + `test_guc_leak`: دو مستأجرِ مصنوعی، assert صفر ردیفِ
مستأجرِ نادرست در هر کوئریِ clinical/patient/card/engagement + scopingِ `card_resolve_token` + **fail-CLOSED
وقتی GUC ست‌نشده/نادرست**، زیرِ `DEBUG=False`. تضمینِ **تک‌مستأجر** (دقیقاً یک tenant_id؛ کلینیکِ
دوم provision نشود). همین تست = گِیتِ کلینیکِ دوم. **S4 فقط پس از اعمالِ نتیجهٔ S3 اجرا شود** (جلوگیری از green کاذب).
- **✅ انجام شد (کامیت `430538e`):** تیم (qa + security) تأیید کرد **TEST scope از قبل کاملاً پوشش دارد** (test_e2e_tenant_isolation
  + test_guc_leak + test_patient_card_token + test_engagement_dispatch/approvals + test_control_room + اثباتِ table-wideِ قدم ۷۳) →
  تستِ نوِ ایزولاسیون نساختم (over-engineering). تنها deliverable = **گاردِ تک‌مستأجریِ prod-only** در `provision_tenant`
  (ACK=`ALLOW_ADDITIONAL_TENANT=clinic-2-approved`، idempotent-safe، dev no-op) + `test_single_tenant_guarantee.py` (۴ تست).
  داوریِ من: prod-only Python حالا؛ **enforcementِ سختِ DB-level به T1 موکول** (blast-radius). بازبینیِ من: backend **707**/۱skip.

### ✅ 75 (S3) رضایت: AND-clauseِ پیامک + برشِ رضایتِ پردازشِ داده (invariantِ بوت → ۷۶) — کامیت `b1cc925`
> راستی‌آزمایی: ستونِ `sms_consent` در slice0 **هست** (پس AND-clause همین‌حالا روی آن ساختنی است)، اما
> ستونِ **رضایتِ پردازشِ داده وجود ندارد** → نیازِ یک برشِ افزایشی.
- (الف) در dispatcher، ارسالِ پیامک را علاوه بر `sms_opt_out` به `sms_consent` هم گِیت کن (default-deny
  وقتی رضایت ثبت نشده) — همین‌حالا، حتی با SMS خاموش، تا flipِ بعدیِ KYC safe-by-default باشد. **assert
  که مسیرِ worklist/NullProvider به consent گِیت نمی‌شود** (فقط ارسالِ واقعیِ SMS).
- (ب) یک برشِ افزایشیِ idempotent برای `data_consent` + `data_consent_at`/`version`/`source` (ADD COLUMN
  IF NOT EXISTS، هرگز فرضِ DBِ تازه).
- (ج) invariantِ بوت **→ به قدم ۷۶ موکول شد** (داوریِ legal+backend: نسخهٔ consent-onlyِ آن tautological
  است چون گیتْ کدِ همیشه-فعال است؛ در ۷۶ کنارِ sanitize به یک Django system checkِ fail-closedِ معنادار تبدیل می‌شود).
- **توجهِ ترتیبی:** سطحِ **capture**ِ رضایت (UI + متنِ privacy) به قدمِ **پذیرش/۸۵ (U2)** و به متنِ
  نهاییِ وکیل (R4) گره می‌خورد و از **config** رندر می‌شود، نه hardcode.
- **✅ انجام شد (کامیت `b1cc925`):** گاردِ consent فقط در `send_approved_sms` (نه worklist/dispatch — care دریغ نمی‌شود)؛
  slice17 data_consent (column-only، بدونِ منطقِ خواننده، جدا از sms_consent)؛ تستِ مثبتِ no-consent + ۳ نگهبانِ slice17.
  داوریِ من بینِ legal(send-only) و backend(blast-radius): گاردِ send-only، seedِ پایه consented، (ج) به ۷۶. بازبینیِ من:
  backend **708**/۱skip، guard **121** (۲ باگ گرفت: رگرسیونِ enrichment + NameErrorِ نگهبان).

### ✅ 76 (S4) sanitizeِ محتوای بالینی در SMS (R3) + invariantِ بوت — کامیت `e6a9e8b`
`compliance` را گسترش بده تا **محتوای بالینی** (نامِ دارو، دوز، تشخیص، مقدارِ آزمایش) را — نه فقط واژهٔ
تبلیغاتی — از متنِ SMS حذف/مسدود کند. (با گِیتِ KYC حرکت می‌کند ولی همین‌حالا ساخته می‌شود تا flip ایمن باشد.)
- **+ invariantِ بوت (منتقل‌شده از ۷۵):** یک Django system check (در apps.ready) که اگر provider بتواند live شود
  (`SMS_LIVE_ENABLED` + کلید) ولی پیش‌نیازهای ایمنی (consent-gate + sanitizeِ محتوای بالینی) فراهم نباشد → خطای
  fail-closed در بوت. اینجا — جایی که sanitize ساخته می‌شود — این check غیرتاتولوژیک و معنادار است (legal: fail-closed).
- **✅ انجام شد (کامیت `e6a9e8b`):** تیم clinical-pharmacist + security. (الف) `find_phi`/`is_phi_free` عدد-محور
  (دوز/lab-anchor+عدد/BP-ratio/drug+عدد) با نرمال‌سازیِ ارقامِ فارسی + **حذفِ زمینهٔ خوش‌خیم** (تاریخ/ساعت/تلفن) →
  بدونِ false-positive؛ (ب) **BLOCK** در send_approved_sms قبل از provider.send (auto-reject، نه strip)؛ (ج) system
  checkِ `clinical.E001` (production + live + بی‌کلید → Error؛ نه tautology/toggle). داوریِ من: BLOCK نه strip، فشار/bp
  به regexِ نسبتی واگذار. بازبینیِ من: backend **732**/۱skip سبزِ اولین اجرا (۸ MUST-PASS/۶ MUST-CATCH + spy: send صفر بار).

### ✅ 77 (S5) پوششِ audit-log — کامیت `6193ec7`
تأیید کن visit / نوشتنِ نسخه / accept پیشنهاد / approve تعامل / issue-revoke توکن هرکدام tenant + user +
patient را لاگ می‌کنند؛ گپ‌ها را پر کن. (verification است نه ساختِ سنگین — ردِ شواهدِ حقوقی + پیش‌نیازِ incident-response.)
- **✅ انجام شد (کامیت `6193ec7`):** تیم security. **مسیرِ نوشتنِ audit از قبل کامل بود** (هر اقدام log_activity را با
  tenant+user+patient_link_id صدا می‌زند) → کدِ logging-نو لازم نبود؛ فقط **گاردِ coverage**: `test_audit_coverage.py`
  (۳ تست: encounter_created/prescription_created/card_token_issued، assertِ وجودِ ردیف با patient_link_id چون log_activity
  best-effort است). داوریِ من: رفعِ card_token_revoked patient_link_id را skip کردم (revoke فقط token_id دارد؛ query
  افزودن طبقِ توصیهٔ security اجتناب شد)؛ read-access-log موکول (O-3). بازبینیِ من: backend **735**/۱skip سبزِ اولین اجرا.

### ✅ 78 (S6) بنیانِ یکپارچگیِ سنجش — رفعِ باگِ `enrolled_at` + seedِ طولیِ تست  [⚠️ پرریسک] — کامیت `e8e8705`
> **باگِ واقعیِ راستی‌آزمایی‌شده:** `clinical/models.py:40` → `enrolled_at = auto_now_add=True`. این
> ORM **هر مقداری که import ست کند را بی‌صدا دور می‌اندازد** و زمانِ درجِ ردیف را می‌نشاند → هر بیمارِ
> import‌شده `enrolled_at = روزِ import` می‌گیرد → **پنجرهٔ baseline و freezeِ holdout برای همیشه
> خراب** می‌شود (slice0:129 هم DEFAULT now() دارد). بازگشت‌ناپذیر.
- **ساب‌تسک:** `auto_now_add` را بردار؛ `enrolled_at` را صریحاً settable کن؛ migrationِ افزایشیِ
  idempotent؛ روی یک کپی اثبات کن که importِ backdated تاریخِ واقعی را حفظ می‌کند.
- **+ seedِ طولیِ واقع‌گرایانه** (~۳۰–۵۰ بیمار، ~۲ سال vitals/labs در چند بیماری) و **اعتبارسنجیِ کاملِ
  pipelineِ outcome + holdout یک‌بار** (پنجره/baseline/paired-subset/شمارندهٔ holdout همه fire شوند) —
  جایی که باگِ `enrolled_at` گرفته می‌شود. (این **پیش از** خوشهٔ V است، نه parallel-W؛ چون freezeِ holdoutِ
  واقعی در V بازگشت‌ناپذیر است و pipeline باید قبلش روی دادهٔ مصنوعی اثبات شود.)
- **✅ انجام شد (کامیت `e8e8705`):** تیم data-architect + clinical-data-scientist. رفع: `enrolled_at = DateTimeField(db_default=Now())`
  (نه auto_now_add، نه null=True) — settable + unset→DEFAULT now()ِ DB؛ **بدونِ تغییرِ schema**، blast-radius صفر (هیچ
  PatientLink.objects.create در کدبیس نیست). تست: `test_enrolled_at.py` (۲ تست ORM-create). **یافتهٔ صادقانهٔ CDS (چهارمین
  «از قبل پوشش‌دار»):** seed + اعتبارسنجیِ outcome از قبل در test_cohort_outcomes (۳۵-بیمار، N>=30، verified-gate، thin-gate)؛
  holdout در test_engagement_holdout H8/H9/H10 → **seed/تستِ حجمِ نو نساختم** (over-engineering). داوریِ من: D1 negative-control
  skip (تستِ موجود anchoring را مثبت اثبات می‌کند). بازبینیِ من: backend **737**/۱skip سبزِ اولین اجرا.

> 🏁🏁 **خوشهٔ S (کفِ ایمنی، قدم‌های ۷۳–۷۸) کامل شد** — auditِ RLS · تک‌مستأجر · رضایت · sanitizeِ PHI · پوششِ audit-log · رفعِ enrolled_at.
> backend ۷۳۷ / guard ۱۲۱، همه روی main. بعدی: **خوشهٔ T (بخش‌های محلیِ بدونِ‌VPS: T1 webِ Dockerfile/compose، T2 scheduler)** سپس خوشهٔ U.

## خوشهٔ T — ستونِ استقرار  (گِیت: R1/VPS؛ T1ِ وب **محلی و موازی** ساختنی است)

### ✅ 79 (T1) artifactِ استقرارِ `halqe/web`  [⚠️ مسیرِ بحرانیِ go-live] — کامیت `088ea88`
> راستی‌آزمایی: Dockerfileِ بک‌اند (`halqe/Dockerfile`) **هست** و serviceِ `app` آن را build می‌کند؛ اما
> در `docker-compose.yml` **serviceِ web و scheduler وجود ندارد** و هیچ Dockerfileِ Next.js نیست.
- Dockerfileِ Next.js (یا buildِ pinnedِ host) که وب را پشتِ nginx/TLS در‌دسترس کند + serviceِ `web`
  در compose، سیم‌کشی به origin/CORS؛ **فونت/asset خودمیزبان (بدونِ CDN)** + scopeِ SwRegistrar تأیید شود.
- **مسیر:** محلی و موازی ساختنی است (نیازِ VPS ندارد) ولی **پیش‌شرطِ سختِ go-live**؛ به فهرستِ پیش‌نیازِ قدم ۹۶ افزوده شود.
- **✅ انجام شد (کامیت `088ea88`):** تیم delivery + frontend. `halqe/web/Dockerfile` (multi-stage node:22 standalone، non-root،
  offline-npm note) + `.dockerignore` + `next.config output:"standalone"` + سرویسِ `web` در compose (internal، بدونِ port) +
  nginx `upstream halqe_web`+`location /`→web (locationهای rate-limitedِ API دست‌نخورده) + بازنویسیِ runbook §11. **داوریِ من:
  same-origin (نه دو-هاست)** → `_core.ts` پیش‌فرضِ API_BASE به **relativeِ `/api/v1`** (حذفِ تله‌ی build-time-bakingِ NEXT_PUBLIC +
  CORS). بازبینیِ من: `docker compose config` PASS، web jest **508/508**، tsc پاک. **buildِ کاملِ ایمیج (npm آفلاین) انجام نشد →
  صادقانه به deploy/گِیتِ VPS موکول.**

### ✅ 80 (T2) provisionِ schedulerِ تعامل/پیگیری  [⚠️ پرریسک — «حلقهٔ نیمه‌مرده»] — کامیت `8e9ec50`
serviceِ scheduler در compose (host cron یا compose-loop) که `run_engagement` + `generate_followups`
را با advisory-lockِ موجود صدا می‌زند؛ **یک مالکِ واحد**؛ **DISABLED provision شود** و `run_engagement`
فقط پس از تأییدِ freezeِ holdout (V3) via یک فلگِ per-tenantِ `onboarding_complete` فعال شود (تا علیهِ
holdoutِ منجمدنشده tick نزند → حفاظت از ادعای incrementality). **heartbeatِ «آخرین tick» + موفقیتِ
بکاپ از همان بوتِ اول** قابلِ‌رؤیتِ اپراتور باشد (نه پس از گِیتِ T5).

> **انجام‌شده (۸۰):** تیمِ موازیِ Opus = delivery-reliability + clinical-data-scientist. سرویسِ
> `scheduler` در `docker-compose.yml` (همان imageِ backend، `profiles:["scheduler"]` → با `up` معمولی
> بالا نمی‌آید = «DISABLED provision»؛ entrypoint به حلقهٔ `sh` override شد تا apply_schema را تکرار
> نکند؛ `depends_on app:service_started`). هر tick: `generate_followups` (همیشه — مراقبت دریغ نشود) سپس
> `run_engagement $WL`؛ `|| echo` بعدِ **هر دو** چون generate_followups در خطا `raise` می‌کند.
> **گِیتِ holdout:** `SCHEDULER_WORKLIST_ONLY` پیش‌فرض `"1"` (fail-safe — outreach تا freezeِ holdout
> خاموش، سپس مالک به `"0"` flip می‌کند) — جایگزینِ ساده و درستِ ایدهٔ فلگِ per-tenantِ نقشه، چون
> `run_engagement --worklist-only` همین‌حالا کانالِ SMS را کامل می‌بندد. **heartbeat:** نوشتنِ timestamp در
> `/tmp/scheduler.heartbeat` (کانتینر non-root → volumeِ root-owned نوشتنی نیست) + خطِ لاگ + healthcheckِ
> `stat`+`date` (پنجره ۳× interval → «up ولی گیرکرده» را unhealthy می‌کند). داورِ داده: enqueue/worklist
> هم می‌توانند holdout را آلوده کنند → پیش‌فرضِ worklist-only درست؛ توالیِ assignment→baseline→activation
> نگرانیِ runbook است (مستند شد). **بازبینیِ من:** `docker compose config` PASS (scheduler خارج از
> default، داخلِ `--profile scheduler`، فقط nginx پورت publish، `$$` runtime درست، env interpolation درست).
> بدونِ Python/schema → بدونِ pytest/guard. اجرای زندهٔ کانتینر (اولین tick + گذارِ healthcheck) به deploy
> موکول (صادقانه، مثلِ ۷۹). فایل‌ها: `docker-compose.yml` + `.env.example` (`SCHEDULER_*`) +
> `docs/runbook_engagement.md` (بخشِ sidecar بازنویسی شد). موکولِ مستندشده: جدولِ persistentِ last-tick +
> ثبتِ freeze/activation-date برای تحلیلِ stepped-wedge؛ چک‌لیستِ go-live = فعال‌بودنِ scheduler.

### 81 (T3) dry-runِ اجباریِ staging روی hostِ هم‌سانِ VPS
walkِ گاردهای بوت؛ `apply_schema` از clean **سپس** re-apply روی کپیِ **populated** (idempotency، صفر
تغییرِ داده)؛ شکستِ عمدیِ `.env`؛ burstِ ۴۲۹؛ **re-pointِ پلِ read-only حسابداری روی کپیِ
`clinic_new.db`ِ واقعیِ کلینیک** (اثباتِ RAISE روی write + smokeِ غیرخالیِ national_id/درآمد +
**چکِ هم‌زمانی: خواندنِ mode=ro همزمان با نوشتنِ webappِ زنده بلاک/خطا نکند** — SQLite WAL)؛ DRY-RUNِ
importِ V2 روی همان کپی؛ `restore_drill` PASS؛ تمرینِ backup-before-deploy + rollback. ارتقا فقط وقتی سبز.

### 82 (T4) استقرارِ پروداکشن روی VPSِ ایرانی
کلِ stack (api+pg+nginx+**web**+**scheduler**) روی TLS؛ secrets تزریقی نه committed (JWT/DB/Kavenegar)؛
**ایجاد + تأییدِ رولِ کم‌امتیازِ اپ روی prod** (`ensure_app_role`؛ پیش‌نیازِ invariantِ بوت)؛ بکاپ
**رمزنگاری‌شده + دسترسی‌محدود + نسخهٔ off-box + custodyِ کلید**؛ `restore_drill` PASS **ثبت‌شده روی hostِ
prod** + اثباتِ **restore روی hostِ تازه** (سناریوی فاجعهٔ تک‌سایت)؛ پلِ حسابداری mount + RAISE-روی-write +
smokeِ غیرخالی **به‌عنوانِ شرطِ go/no-goِ deploy**؛ **assertِ بدونِ-egress** (بدونِ font-CDN/تله‌متری/
Kavenegarِ خاموش — residency)؛ health/ready سبز؛ heartbeatها زنده.

### 83 (T5) گِیتِ ایمنیِ دادهٔ زنده  [⛔ گِیتِ سختِ پیش از هر PHIِ واقعی — ⚠️ پرریسک]
روی PGِ prodِ زنده زیرِ prod config یک‌بار **بازتأیید** کن: auditِ RLS (S1) + تستِ نشت (S2) + تضمینِ
تک‌مستأجر + **گِیتِ verified (۶ فیلترِ مقدس: build_facts/card/۳×engagement/followup)**؛ گِیتِ regressionِ
prod-config (`test_db_boundary` + `test_prod_config` + سوئیتِ isolation). **مالک نتیجهٔ تستِ نشت را
امضا می‌کند.** هیچ ردیفِ بیمارِ واقعی پیش از سبزشدنِ این گِیت درج نمی‌شود. (تضمینِ تک‌مستأجر اینجا — روی DBِ
زنده پس از امکانِ provision — دوباره چک می‌شود، نه فقط روی DBِ خالیِ S2.)

## خوشهٔ U — رابطِ حلقهٔ مراقبت  (روی **مسیرِ بحرانیِ go-live**؛ پس از T1؛ ۸۷ ایمنی‌مرتبط = آیتمِ UAT)

### ✅ 84 (U1) صفحهٔ وبِ `/control-room` — کامیت `9f71992`
wrapperِ نازک روی ۳ endpointِ GETِ موجود (ترتیبِ بالینی‌اول، برجستگیِ red-flag، ستونِ درآمدِ
manager-only). تستِ نگهبانِ معماری (صفر نوشتنِ حالت). **اول diff قراردادِ control_room/manager با
`docs/openapi.json`.**

> **انجام‌شده (۸۴):** تیمِ موازیِ Opus = ux-ui-designer + frontend-dev-advisor؛ سازنده = frontend-web-engineer
> (Opus). diffِ قرارداد با `docs/openapi.json` اول انجام شد (خالصِ فرانت — endpointها از قبل بودند، صفر تغییرِ
> بک‌اند). فایل‌ها: `src/lib/api/control-room.ts` (کلاینتِ GET-only، typeهای دقیق، `breakdown:unknown[]` دفاعی) +
> barrel + لینکِ `Nav` (تک‌خط؛ IAِ کامل کارِ ۸۶) + `src/app/control-room/{page.tsx,control-room.module.css}` +
> `__tests__/control-room.test.tsx` (نگهبانِ GET-only + تستِ completeness که تابعِ نوشتنیِ آینده را می‌گیرد).
> چیدمان: chip-filterِ کوهورت (فیلترِ سمتِ کلاینت روی `cohorts[].ids`) → جدول → کارتِ conversion. panel+conversion با
> `Promise.allSettled` (panel خطا→کلِ صفحه؛ conversion خطا→فقط کارت؛ ۴۰۱→logout). score badge + expandِ inlineِ
> «چرا؟» (نه tooltip). red-flag = آیکن+متن+رنگ (کوررنگی). گِیتِ درآمد روی `panel.show_value` (نه getRole). قیفِ
> conversion وقتی `n_sufficient=false` **هیچ عددی نمی‌دهد**، فقط متنِ `framing` با `role="note"` (صداقت). empty=خبرِ
> خوب نه خطا. بدونِ شماره‌تلفن/PHI در جدول. **بازبینیِ مستقلِ من:** `tsc --noEmit`=0 + jest **۵۱۳/۵۱۳** (۲۵ suite،
> +۵ نسبت به ۵۰۸، صفر رگرسیون). بدونِ Python/schema→بدونِ pytest. رندرِ بصریِ مرورگر به deploy موکول (صادقانه).

### ⏸️ 85 (U2) صفحهٔ پذیرش (intake) — **موکول به گِیتِ V2/V3 (owner-gate)**
search-by-national-id که match پلِ read-only حسابداری را نشان می‌دهد + register/link + مسیرِ «بیمارِ نو»
(بازاستفادهٔ الگوهای لیستِ بیمار). **مسیرِ نوشتنش باید همان منطقِ dedupِ national_id + freezeِ holdoutِ
V2/V3 را به‌اشتراک بگذارد** (یا write-enable پس از V3) تا بیمارانِ ساخته‌شدهٔ دستی با backfill تصادم/تکرارِ
holdout نسازند. + سطحِ capture رضایت (متن از config). درِ ورودیِ روزِ اولِ حلقه.

> **تصمیمِ موکول‌سازی (در حلقه، با گراندینگِ کد):** ویژگیِ تعریف‌کنندهٔ این قدم **مسیرِ نوشتن** (ساختِ
> `patient_link` با register/link) است و این مسیر **گِیت‌بند** است:
> - در بک‌اند **هیچ endpointِ نوشتن/register/link نیست** (`clinical/api/patients.py` فقط GET: list/record/detail)؛
> - **هیچ منطقِ dedupِ `national_id` وجود ندارد** (`PatientLink` فقط در `models.py` تعریف شده، در کدِ اپ هرگز
>   create نمی‌شود — فقط seed/import)؛ و **`accounting_port` تابعِ search-by-national-id ندارد**؛
> - منطقِ canonicalِ dedup + تخصیص/freezeِ holdout را **V2 (۹۰) و V3 (۹۱)** تعریف می‌کنند که خودشان
>   **owner-gate**‌اند (خوشهٔ V: «گِیتِ T5 سبز + R4 امضاشده؛ نوشتن نیازِ رفعِ ۷۸»؛ `national_id` = PHIِ واقعی؛
>   V3 یک ⛔ گِیتِ سختِ lossy با freezeِ holdout است).
> ساختنِ مسیرِ writeِ U2 پیش از V2/V3 یا منطقِ dedup/holdout را **دوباره‌کاری/واگرا** می‌کند (دقیقاً همان
> تصادم/تکرارِ holdoutی که خطِ بالا هشدار می‌دهد) یا نیازِ گِیتِ V3 دارد. نیمهٔ read-onlyِ search هم به‌تنهایی
> فیچرِ منسجمِ قابلِ‌انتشار نیست و طراحیِ search-by-national-id را پیش از تثبیتِ V2 به ریسکِ واگرایی می‌برد.
> پس مثلِ ۸۱/۸۲/۸۳ **موکول شد** (تیم/سازنده مصرف نشد — صداقت/توکن). **پیش‌نیازِ آزادسازی:** ساخته‌شدنِ V2/V3
> (که خود نیازِ گِیتِ مالک: T5+R4+PHIِ واقعی). آن‌گاه U2 با همان dedup/holdout مشترک ساخته می‌شود.

### ✅ 86 (U3) Nav/IA + landingِ نقش‌محور — کامیت `6282269`
گسترشِ role-gatingِ `Nav.tsx` برای control-room/intake/clinic-setup + اولین‌صفحهٔ هر نقش («الان چه‌کار
کنم») + جاروی dead-link (Nav از قبل role-gated است — ویرایشِ کوچک).

> **انجام‌شده (۸۶):** تیمِ موازیِ Opus = ux-ui-designer + frontend-dev-advisor؛ سازنده = frontend-web-engineer.
> رفعِ یک **بن‌بستِ واقعیِ IA**: فقط دو صفحهٔ `manager/*` به Nav `showManagerLinks` می‌دادند → managerِ روی
> dashboard/queue/patients/worklist لینک‌های مدیریتی را نمی‌دید. حالا **Nav خودش نقش را می‌خواند** (hydration-safe:
> `getRole()` فقط در `useEffect`، هرگز در بدنهٔ render → بدونِ SSR mismatch)؛ `showManagerLinks` به **override
> اختیاری** تبدیل شد (undefined→`role==="manager"`؛ سازگارِ عقب‌رو). **`/control-room` به MANAGER_LINKS منتقل شد**
> (manager-only، برگشت‌پذیر — توصیهٔ UX) داخلِ گروهِ معناییِ `aria-label="مدیریت"`. **landingِ نقش‌محورِ
> `/dashboard`:** کارتِ «اقدامِ اولِ روز» (staff→`/queue`، manager→`/control-room`، بدونِ عددِ ساختگی) + بخشِ
> مدیریتیِ gateشده (role===null→پنهان، بدونِ flash)؛ StatCardهای بیماران/پیگیری برای **هر دو نقش** (care دریغ
> نشود). marketing `/`: فقط کامنتِ کهنه («there is NO /control-room») اصلاح شد، copy دست‌نخورده، تستِ
> `landing.test.tsx:150-152` (بنِ control-room در marketing) سبز ماند. **«intake/clinic-setup» در Nav اضافه نشد**
> چون routeهاشان موجود نیست (U2 موکول، clinic-setup هنوز نیست) → dead-link نساختیم. تست‌های جدید: `nav.test.tsx`
> + `dashboard-landing.test.tsx` + `nav-deadlink.test.ts` (fs: هر hrefِ Nav باید `page.tsx` داشته باشد).
> **بازبینیِ مستقلِ من:** `tsc --noEmit`=0 + jest **۵۳۶/۵۳۶** (۲۸ suite، +۲۳). یک رگرسیونِ واقعی (worklist-page
> چون Navِ واقعی را رندر می‌کند و حالا getRole صدا می‌زند) را سازنده گرفت و mockش را رفع کرد. بدونِ Python→بدونِ
> pytest. رندرِ بصریِ مرورگر به deploy موکول (صادقانه).

### ✅ 87 (U4) UXِ حالت و ایمنی  [آیتمِ گِیتِ UAT — نه polishِ اختیاری] — کامیت `9f29cb8`
حالت‌های NULL-graceful («هنوز داده‌ای نیست» نه «خراب»)؛ قابِ «پیشنهاد — تأیید با پزشک»؛ red-flag فوری و
جداگانه (**آیکن + متن، نه فقط رنگ**) + کفِ دسترسی‌پذیری؛ fallbackِ «شبیه‌سازی/ارسال‌نشده» + وضعیتِ
صریحِ **«تماسِ منشی / هنوز اطلاع‌داده‌نشده»** که اقدامِ due را به worklist می‌برد (مسیرِ بیمارِ کم‌سواد/سالمند).

> **انجام‌شده (۸۷):** تیمِ ممیزیِ موازیِ Opus = gp-family-medicine-advisor + ux-ui-designer؛ سازنده = frontend-web-engineer.
> **یافتهٔ کلیدی (ضدِ over-engineering):** U4 عمدتاً **از قبل ساخته و یکدست بود** — قابِ suggestion-only
> (`SuggestionsPanel`/`RuleCard`)، red-flag آیکن+متن+رنگ (control-room/SuggestionsPanel)، SMSِ «شبیه‌سازی»
> (engagement)، و NULL→`—`/empty/error در همهٔ صفحات. **بازنویسی نشد؛ کامپوننتِ مشترکِ EmptyState عمداً ساخته نشد**
> (churnِ پرریسک، خلافِ Evolve-not-Rewrite). فقط **۲ گَپِ واقعیِ گِیت‌نخورده** ساخته شد: **(۱)** نشانگرِ «⚠ سررسید
> گذشته» در worklist برای تسک‌های open که `due_date < todayِ تهران` (آیکن+وزن+رنگ، نه فقط رنگ؛ helperِ جدیدِ
> `jalali.todayTehranISO()` با Intl/Asia/Tehran نه UTC) — گَپِ ایمنیِ تریاژ که GP تأیید کرد؛ **(۲)** یکدستیِ رقمِ فارسی
> در `VitalsReview` (تک‌خط). **verified-OK بدونِ تغییر:** outcomes/report/engagement(هر دو تب) سه‌حالتی دارند؛
> card/[token] و report severity متن+aria (نه فقط رنگ). **موکولِ صریح (نه گِیت‌نخورده):** stateِ ماندگارِ «تماسِ
> منشی/اطلاع‌داده‌نشده» — هر دو مشاور گفتند نیازِ **فیلدِ بک‌اند + تأییدِ مالک بر منطقِ استنتاج** دارد و برای UAT
> بحرانی نیست (worklistِ موجود مسیرِ پیگیریِ انسانی است) → بهبودِ نزدیک، خارج از scopeِ گِیت‌نخوردهٔ این قدم.
> **بازبینیِ مستقلِ من:** `tsc`=0 + jest **۵۴۱/۵۴۱** (۲۹ suite، +۵). بدونِ Python→بدونِ pytest.

### 88 (U5) ممیزیِ سازگاریِ بین‌صفحه‌ای
RTL/Jalali/ارقامِ فارسی + offline-vendor (بدونِ CDN) در همهٔ routeها (چکِ گِیتی). *(badgeِ billing حذف شد — حذفِ منو کافی است.)*

## خوشهٔ V — Onboarding و یکپارچگیِ داده  (گِیت: T5 سبز + R4 امضاشده؛ نوشتن نیازِ رفعِ ۷۸ + اعتبارسنجیِ ۷۸)

### 89 (V1) runbookِ provisionِ مستأجر + seedِ کاتالوگِ بالینی
اجرای دستورِ موجودِ `onboard_tenant`/`provision_tenant` برای پایلوت (مستأجر، پروفایلِ کلینیک،
کاربرانِ manager/reception/doctor + نقش‌ها، تنظیماتِ engagement/quiet-hours/consent). + **seedِ
`clinical_indicators` + کاتالوگِ `clinical_rules` در مستأجرِ پایلوت** و تطبیق با docs/fallbackها
(قاعدهٔ threshold-sync) — بدونِ آن موتور هیچ پیشنهادِ درستی نمی‌سازد. **CLI-only** (APIِ staff به کلینیکِ
دوم موکول). rehearsal روی مستأجرِ مصنوعی در staging (pre-R4)؛ مستأجرِ واقعیِ پایلوت فقط post-gate.

### 90 (V2) importِ بیمارِ واقعی (علاجِ cold-start)  [⚠️ پرریسک]
دستورِ یک‌بارهٔ idempotent که `patient_links` را از پلِ read-only حسابداری با national_id backfill می‌کند
(+ fallbackِ CSV برای بیمارِ غیرحسابداری؛ بدونِ wizard). **DRY-RUNِ اعتبارِ national_id** (فرمت +
یکتایی) + reconcileِ linked/unlinked که **پیش از commit به مالک نشان داده** شود؛ re-runnable با صفر
تغییرِ خالص؛ **snapshotِ backup-before-import**. national_id = **PHIِ واقعی** → اکیداً پس از امضای T5 + R4.

### 91 (V3) بهداشتِ دادهٔ بازگشت‌ناپذیر در import  [⛔ گِیتِ سخت، lossy — ⚠️ پرریسک]
وابسته به رفعِ ۷۸: `enrolled_at = رویدادِ واقعیِ نام‌نویسی` (هرگز default now()) — با **تصمیمِ منبعِ
`enrolled_at`** (اولین‌ویزیتِ حسابداری؟ CSV؟ دستی؟ + fallback، در R3/R4 قفل شود)؛ snapshotِ baselineِ
هر-بیماری؛ **تخصیص + freezeِ گروهِ holdout**؛ گِیتِ کیفیتِ داده که baselineهای خارج‌از‌پنجره را علامت می‌زند.

### 92 (V4) خروجیِ داده + حقِ حذف
runbookِ مستندِ `pg_dump`-تک‌مستأجر (نه exporterِ ساخته‌شده؛ DBِ تک‌مستأجر = کلِ dump) + **مسیرِ
withdrawalِ رضایت / حذفِ per-patient** (فرایندِ دستیِ حداقلی یا موکولِ مستند با sign-offِ مالک + وکیل) —
تعهدِ خروج/حذفِ DPA را واقعی می‌کند.

## خوشهٔ W — توانمندسازیِ پایلوت و خواندنِ سنجش

### 93 (W1) scorecardِ عملیاتی/پذیرش + معیارِ موفقیتِ پایلوت
scorecardِ عملیاتی (نرخِ accept، throughputِ worklist، تبدیلِ followup→ویزیت، uptakeِ self-report) =
**سیگنالِ اصلیِ موفقیتِ پایلوت**، از هفتهٔ اول non-NULL. معیارِ go/no-go + پروتکلِ snapshotِ baselineِ
reference-case را **از قبل با کلینیک توافق** کن (اندازهٔ کوهورت، تعدادِ lapsed، وضعیتِ کنترل) — صادقانه، non-causal.

### 94 (W2) آموزش و پشتیبانی
راهنمای کوتاهِ RTLِ نقش‌محور (reception/doctor/manager) + توضیح‌گرِ مفهومِ care-loop + چک‌لیستِ go-live
(معیارِ خروج = یک حلقهٔ کاملاً بسته در آموزش)؛ کانالِ پشتیبانی/بازخوردِ ۲ هفته‌ای + playbookِ triage گره
به request-id logs + خواندنِ هفتگیِ سلامتِ حساب؛ **+ SLAِ بازبینیِ هم‌روزِ red-flag** (مالکِ نام‌دار،
بازبینیِ روزانهٔ worklist) چون SMS روی NullProvider است → «مراقبت هرگز دریغ نمی‌شود».

## خوشهٔ X — Go-Live و پذیرش  (گِیتِ پایانی؛ کدِ نو نمی‌سازد)

### 95 (X1) UATِ پایلوت (go/no-go)
walkِ سرتاسری روی **کپیِ** DBِ مستأجرِ واقعی: login → intake → record → ویزیت (encounter + نسخهٔ آزاد) →
accept/dismiss پیشنهاد → followup → worklist/control-room → approve تعامل. assert: لاگِ suggestion-only،
verified-gate، red-flag inline، Jalali/زمانِ ایران، fallbackِ SMS-deferred (بدونِ یادآورِ مرده)، **نسخهٔ
آزاد به پزشکِ مجوزدارِ نویسنده لاگ شود**، idempotencyِ برش‌ها. هیچ کدِ نو.

### 96 (X2) go-liveِ پایلوت
ورودِ بیمارانِ واقعی **فقط پس از**: T5 سبز + قرارداد/رضایتِ R4 امضاشده + `restore_drill` PASS روی prod +
backup-before-import + «یک حلقهٔ بسته در آموزش». اجرای روزانهٔ حلقه در بازهٔ پایلوت با کانالِ پشتیبانیِ باز؛
ثبتِ deferralِ billingِ امضاشدهٔ مالک + رکوردِ مصرف. **پیش از go-live، رویهٔ abort/kill-switch + rollbackِ
PHI تعریف شود** (migrationها forward-only‌اند → abort = freeze + restore بکاپِ pre-load + بازگشت/حذفِ دادهٔ مطابقِ DPA).

### 97 (X3) خواندنِ نتیجهٔ پایلوت + تبدیل
در پایانِ پایلوت scorecardِ صادقانهٔ non-causal خوانده می‌شود؛ **تبدیل به پولیِ قراردادی** (اقدامِ مالک /
فلگِ وضعیت طبقِ بندِ R4) trigger می‌شود؛ reference-case با اجازهٔ کتبیِ کلینیک capture می‌شود.

---

## قدم‌های پرریسک (تمرکزِ بازبینیِ بیشتر هنگامِ اجرا)
**۷۳** (auditِ RLS — بنیانِ ادعای ایزولاسیون) · **۷۸/۹۱** (`enrolled_at` بازگشت‌ناپذیر + freezeِ holdout —
تنها ادعای دفاع‌پذیرِ پایلوت) · **۸۰** (scheduler — حلقهٔ نیمه‌مرده اگر tick نزند) · **۸۳** (گِیتِ
ایمنیِ زندهٔ go/no-go) · **۹۰** (importِ بیمارِ واقعی — جایی که PHIِ واقعی، قانون، و مرزِ read-only هم‌زمان لمس می‌شوند).

## ⛔ فهرستِ کاملِ گِیت‌های مالک
1. **VPSِ ایرانی + TLS + DNS + فایروال + بکاپِ رمزنگاری‌شده/off-box** (R1) — گِیتِ زیرساخت.
2. **تصمیمِ billing** (defer-to-manual توصیه‌شده) + اعدادِ قیمت + واحدِ ارز (ADR-0007) + تعریفِ بیمارِ فعال + pass-throughِ پیامک (R2/R3).
3. **انتخابِ کلینیکِ پایلوت + نقشهٔ امضاکننده + champion + LOI/تعهد** (R3).
4. **قرارداد/DPA/رضایتِ بیمار/privacy، نهاییِ وکیل** (R4) — گِیتِ سختِ پیش از هر PHIِ واقعی.
5. **امضای مالک روی نتیجهٔ تستِ نشت** پیش از هر PHIِ واقعی (T5).
6. **KYC کاوه‌نگار** — فقط گِیتِ SMS؛ صریحاً **DECOUPLED**، هرگز بلاک‌کنندهٔ MVP نیست.
7. **per-population red-flag** (قدم ۳۹) — sign-offِ بالینی؛ پایلوت per-patient suggestion-only می‌ماند.
8. **sign-offِ R3 PHI-sanitization** — با flipِ KYC/SMS حرکت می‌کند.
9. **پذیرشِ کتبیِ مالک** که پنل‌های پیامد ماه‌ها NULL می‌خوانند (R2).
10. **منبعِ `enrolled_at`** (اولین‌ویزیتِ حسابداری/CSV/دستی + fallback) — پیش از import قفل شود (R3/R4).

## دنباله‌های موکول (پس از MVP، گِیت‌بسته — صریحاً در MVP نیست)
go-liveِ SMS (KYC + R1 + R3 + sign-offِ ۳۹) · `slice17` billing در کلینیکِ دوم · فعال‌سازیِ کاملِ
خط‌به‌خطِ RLS + auditِ مستأجرِ دوم (T1) · مسیرِ اینترنتیِ کارت (VPS+WireGuard+KYC) · بازنویسیِ set-based
analytics (تریگرِ داده) · فعال‌سازیِ CI Actions · APIِ self-serve staff/onboarding · پلِ نسخهٔ بیمه (owner-blocked).

---
*ساخته‌شده با شورای ۱۶ مشاوره (۲ دور) + پنلِ ۸ منتقدِ خصمانه + سنتزِ مستقل + راستی‌آزماییِ کد. نقدِ
خصمانه چند موردِ واقعی را اصلاح کرد: باگِ `enrolled_at=auto_now_add` (verified)، تصحیحِ رازِ نادرستِ S3،
رولِ کم‌امتیاز/seedِ کاتالوگ/red-flag-SLA/kill-switchِ گم‌شده، و trimِ over-engineering (billing-badge،
exporter، staff-API، uptime-monitor).*

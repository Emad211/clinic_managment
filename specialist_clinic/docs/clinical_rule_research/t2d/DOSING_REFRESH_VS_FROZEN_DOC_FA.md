# DOSING_REFRESH — راستی‌آزمایی و تکمیل اعداد دوز/تیتراسیون سند منجمد `ada_t2_rules.md` (v0.9.4)

> **هدف:** تبدیل پروفایل‌های §6.3.1–6.3.8 و §6.4 سند منجمد به مجموعهٔ اعدادِ دقیق، مستند و قابل‌تبدیل به ~۳۵ قانون دوز اجرایی (DSL: `suggest_med` / `set_target` / `create_followup` با پارامترهای dose-string).
>
> **روش:** سند منجمد خط پایه است. هر عدد در برابر (الف) ADA Standards of Care 2026 (*Diabetes Care* 2026;49(Suppl.1) — §6، §9: S183، §10، §11) و (ب) آخرین Prescribing Information معتبر FDA هر دارو بررسی شد.
>
> **قرارداد علائم:**
> - ✅ = عدد در سند منجمد موجود بود و با منبع فعلی **تأیید** شد.
> - 🆕 = سند منجمد عدد نداشت («به PI ارجاع داده») و اینجا از **label/guideline** تکمیل شد.
> - ⚠️ **DELTA** = تعارض یا اصلاح نسبت به فرض/عدد موجود.
>
> **دیسکلیمر:** همهٔ خروجی‌ها «پیشنهاد برای تأیید پزشک» است؛ منبع نهایی تجویز، PI سازنده و قضاوت بالینی است. تاریخ راستی‌آزمایی: 2026-08-23.

---

## ۱) جدول‌های کلاس‌به‌کلاس

### ۱.۱ متفورمین

| فیلد | سند منجمد | مقدار تأییدشدهٔ فعلی | منبع |
|---|---|---|---|
| شروع IR | 🆕 نداشت | **500 mg BID** یا 850 mg QD همراه غذا | Glucophage PI (FDA) |
| تیتراسیون | 🆕 نداشت | **+500 mg هفتگی** (یا 850 mg هر ۲ هفته) تا حداکثر تحمل | Glucophage PI |
| Max | 🆕 نداشت | IR: **2550 mg/day** (3×850)؛ دوز نگهدارندهٔ معمول 2000 mg/day | Glucophage PI |
| ER | 🆕 نداشت | شروع **500–1000 mg QD با شام**؛ تیتر +500 mg هفتگی؛ Max **2000 mg/day** | Glucophage XR PI |
| کلیوی | ✅ eGFR<30 منع؛ <45 شروع نکن/کاهش؛ <30 قطع | همان + جزئیات label: در افت به <45 ارزیابی منفعت/خطر و **نصف‌کردن دوز**؛ 30–45 شروع ممنوع | ADA 2026 Table 9.2 + Glucophage PI §2.3 |
| کبدی | 🆕 نداشت | عدم تحمل خوراکی/AKI → قطع موقت (sick-day)؛ هیپوکسی/الکلی شدید احتیاط | ADA 2026 §6 sick-day + PI |
| ریسک هیپو | ✅ بدون هیپو | بدون هیپو (مونوتراپی) | ADA 2026 Table 9.2 |
| وزن | ✅ خنثی/کاهشی | خنثی تا کاهش خفیف | ADA 2026 Table 9.2 |
| CV/HF/CKD flag | ✅ منفعت میکروواسکولار/مرگ (legacy UKPDS) | flag CV/HF/CKD مستقل از A1c ندارد؛ فقط پایهٔ گلایسمیک | ADA 2026 §9 |

### ۱.۲ مهارکننده‌های SGLT2 — per-agent

| دارو | شروع | تیتراسیون | Max | تنظیم کلیوی | منبع |
|---|---|---|---|---|---|
| **Empagliflozin** | 🆕 **10 mg صبح QD** | 🆕 پس از تحمل، برای کنترل گلایسمی بیشتر → **25 mg QD** | **25 mg** | کنترل گلایسمی در eGFR <30 توصیه نمی‌شود؛ اندیکاسیون HF/CKD طبق label مستقل | Jardiance PI (FDA, rev 10/2025) §2.2 |
| **Dapagliflozin** | 🆕 **5 mg صبح QD** | 🆕 پس از تحمل و نیاز → **10 mg QD** | **10 mg** | شروع برای کنترل گلایسمی نیازمند eGFR ≥45؛ اندیکاسیون HF/CKD با 10 mg حتی eGFR پایین‌تر مجاز | Farxiga PI (FDA) §2.2 |
| **Canagliflozin** | 🆕 **100 mg قبل از اولین وعده** | 🆕 eGFR ≥60 و نیاز → **300 mg** | eGFR≥60: **300 mg**؛ eGFR 30–<60: **100 mg** | eGFR <30: شروع ممنوع (ادامهٔ 100 mg فقط اگر آلبومینوری >300 برای حفاظت کلیوی)؛ دیالیز: منع | Invokana PI (FDA, rev 08/2020) §2.2 Table 1 |

⚠️ **DELTA-1 (empagliflozin):** فرض رایج «Max T2D = 10 mg» **دیگر برابر label فعلی نیست** — label US بازنگری‌شده (rev 10/2025) افزایش به **25 mg** برای کنترل گلایسمی اضافه را در بیمارانِ متحمل مجاز می‌داند (بدون شرط eGFR روی خودِ افزایش؛ فقط «کنترل گلایسمی در eGFR<30 توصیه نمی‌شود»). قانون engine باید max=25 با گیتِ tolerance داشته باشد.

🆕 **قواعد مشترک کلاس (تأیید سند منجمد):** شروع تا eGFR ≥20 مجاز و تا دیالیز/پیوند ادامه‌پذیر؛ اثر کاهندهٔ گلوکز در eGFR <45 حداقلی (ADA 2026 §9.10/Table 9.2). قطع **≥3 روز** پیش از جراحی با ناشتایی طولانی (Jardiance PI §2.3؛ سند منجمد ✅).

### ۱.۳ آگونیست‌های GLP-1 و dual GIP/GLP-1 — per-agent escalation

| دارو | شروع | گام‌های تیتراسیون (حداقل فاصله) | Max | تنظیم کلیوی | منبع |
|---|---|---|---|---|---|
| **Semaglutide SC (Ozempic)** | 🆕 **0.25 mg هفتگی ×4 هفته** (دوز آغازین، درمانی نیست) | 0.25→**0.5** (بعد 4w)→**1** (بعد ≥4w)→**2** (بعد ≥4w) | **2 mg/week** | بدون تنظیم | Ozempic PI (FDA, 2026) §2.1 |
| **Semaglutide خوراکی (Rybelsus R1)** | 🆕 **3 mg/day ×30 روز** (دوز آغازین) | 3→**7** (روز 31)→**14** (بعد ≥30d در صورت نیاز) | **14 mg/day** | بدون تنظیم | Rybelsus PI (FDA) §2.2 |
| **Liraglutide (Victoza)** | 🆕 **0.6 mg/day ×≥1 هفته** | 0.6→**1.2**→**1.8** (هر گام بعد ≥1w) | **1.8 mg/day** | بدون تنظیم | Victoza PI (FDA, 2025) §2.1 |
| **Dulaglutide (Trulicity)** | 🆕 **0.75 mg هفتگی ×≥4w** | 0.75→**1.5**→**3**→**4.5** (گام‌های 1.5 mg، هر ≥4w) | **4.5 mg/week** | بدون تنظیم | Trulicity PI (Lilly USPI) §2.1 |
| **Tirzepatide (Mounjaro)** | 🆕 **2.5 mg هفتگی ×4w** (آغازین) | **+2.5 mg** هر ≥4 هفته (2.5→5→7.5→10→12.5→15) | **15 mg/week** (بزرگسال) | بدون تنظیم | Mounjaro PI (FDA, 2026) §2.1 |
| **Exenatide BID (Byetta)** | 🆕 **5 mcg BID ×1 ماه**، ≤60 دقیقه قبل از دو وعدهٔ اصلی | 5→**10 mcg BID** | **10 mcg BID** | ⚠️ eGFR/CrCl ≤30 اجتناب (ADA) | Byetta PI (DailyMed) §2.1 + ADA 2026 Table 9.2 |
| **Exenatide ER (Bydureon BCise)** | 🆕 **2 mg هفتگی** | بدون تیتر | 2 mg/week | eGFR ≤30 اجتناب | Bydureon PI + ADA |
| **Lixisenatide (Adlyxin)** | 🆕 **10 mcg/day ×14 روز** | 10→**20 mcg/day** | 20 mcg/day | eGFR ≤30 اجتناب | Adlyxin PI + ADA |

⚠️ **DELTA-2 (semaglutide خوراکی):** عبارت «sema 0.25→… oral» در ورودی طراحی **غلط** است — مسیر خوراکی از **3 mg** شروع می‌شود نه 0.25. (0.25 فقط SC/Ozempic است.) ضمناً label 2026 نشان می‌دهد فرمولاسیون قرصی جدید **R2 (1.5/4/9 mg)** نیز ثبت شده که rule engine فعلاً فقط R1 (3/7/14) را مدل کند و R2 را به‌عنوان variant علامت بزند.

✅ **تأیید سند منجمد:** sema/dula/lira/tirz نیاز به تنظیم کلیوی ندارند؛ lixi/exenatide در eGFR ≤30 اجتناب؛ هشدارهای کلاس (پانکراتیت، گاستروپارزی، قطع پیش از بیهوشی، NAION، پایش رتینوپاتی) همگی مطابق ADA 2026 Table 9.2 معتبرند.

### ۱.۴ مهارکننده‌های DPP-4 — renal-adjusted

| دارو | دوز نرمال | eGFR 45–59 | eGFR 30–44 | eGFR <30 / دیالیز | منبع |
|---|---|---|---|---|---|
| **Sitagliptin** | 🆕 **100 mg QD** | 100 mg | 🆕 **50 mg QD** | 🆕 **25 mg QD** (شامل HD، بعد دیالیز) | Januvia PI (FDA) §2.2 |
| **Saxagliptin** | 🆕 **5 mg QD** (با مهارکنندهٔ قوی CYP3A4/5: 2.5) | — | — | 🆕 **eGFR <45 → 2.5 mg QD** | Onglyza PI (FDA, 2024) §2.2 |
| **Linagliptin** | 🆕 **5 mg QD** | 5 | 5 | 5 (بدون تنظیم) | Tradjenta PI |
| **Alogliptin** | 🆕 **25 mg QD** | 25 | 🆕 **12.5 mg QD** | 🆕 **6.25 mg QD** | Nesina PI |

⚠️ **DELTA-3:** فرض ورودی «sitagliptin eGFR30-45→25» **نادرست** است؛ در بازهٔ eGFR 30–<45 دوز **50 mg** است و 25 mg فقط برای eGFR <30/دیالیز.

✅ سایر موارد سند منجمد تأیید شد: saxagliptin سیگنال HF، منع ترکیب DPP-4i با GLP-1/dual (ADA 9.18، B)، خنثی‌بودن وزن/CV.

### ۱.۵ پیوگلیتازون (TZD)

| فیلد | سند منجمد | مقدار فعلی | منبع |
|---|---|---|---|
| شروع | 🆕 نداشت | **15 یا 30 mg QD**؛ در HF NYHA I/II شروع محدود به **15 mg** | Actos PI (Takeda) §2.1 |
| تیتراسیون | 🆕 نداشت | **+15 mg** بر اساس پاسخ HbA1c (عملی: هر 8–12 هفته) | Actos PI + clinical practice |
| Max | 🆕 نداشت | **45 mg/day** | Actos PI |
| کلیوی | ✅ بدون تنظیم دوز ولی توصیه نمی‌شود در اختلال کلیوی | همان (احتباس مایع) | ADA 2026 Table 9.2 |
| کبدی | 🆕 نداشت | شروع در بیماری کبدی فعال یا ALT >2.5×ULN توصیه نمی‌شود؛ LFT قبل از شروع | Actos PI §2.1 |
| هیپو/وزن/HF | ✅ کم‌هیپو؛ وزن‌افزا؛ HF ممنوع | تأیید؛ منع NYHA III/IV | ADA 2026 + Actos PI warnings |

### ۱.۶ سولفونیل‌اوره‌ها

| دارو | شروع | تیتراسیون | Max | کلیوی | منبع |
|---|---|---|---|---|---|
| **Glimepiride** | 🆕 **1–2 mg QD با صبحانه**؛ پرخطرِ هیپو/سالمند/CKD → **1 mg** | 🆕 **+1–2 mg هر 1–2 هفته** | **8 mg/day** | شروع 1 mg، تیتر محتاطانه | Amaryl PI (Sanofi) §2.1 |
| **Glipizide** | 🆕 **2.5–5 mg قبل از صبحانه** | +2.5–5 mg | IR: **40 mg/day**؛ XL: **20 mg/day** | شروع 2.5 mg در CKD | Glucotrol PI |
| **Glyburide** | ✅ در CKD توصیه نمی‌شود | — | — | ❌ CKD | ADA 2026 Table 9.2 |

✅ هیپوی بالا، وزن‌افزایی، ایمنی CV نسبی glimepiride، تداخل آنتی‌بیوتیک‌ها (سند منجمد §6.3.7) تأیید شد.

---

## ۲) انسولین — اعداد دقیق initiation/titration

### ۲.۱ شروع basal (✅ تأیید — ADA 2026 §9/Fig 9.5)
- **شروع: 10 U/day** یا **0.1–0.2 U/kg/day** بر اساس درجهٔ هایپرگلیسمی. *(منبع: Diabetes Care 2026;49(Suppl.1):S183 — عیناً «starting doses can be estimated based on body weight (0.1–0.2 units/kg/day)».)*
- هدف FPG معمولاً **80–130 mg/dL** (Table 6.3).

### ۲.۲ الگوریتم‌های تیتراسیون FPG-target
| الگوریتم | گام | منبع |
|---|---|---|
| سریع | ✅ **+2 U هر 3 روز** تا FPG هدف بدون هیپو | ADA 2026 Fig 9.5 (S183) |
| درصدی | ✅ **+1–2 U یا +10–15% دو بار در هفته** | ADA 2026 Fig 9.5 |
| Treat-to-Target جدولی | 🆕 نسخهٔ کارآزمایی: FPG هدف ≤130 با +2 IU هر 3 روز (Riddle 2003) یا +2 U هفتگی/دوباردرهفته (Davies 2005) | Trials-derived؛ خارج از متن ADA — فقط الگوی جایگزین |

- **هیپوگلیسمی بدون علت مشخص → کاهش 10–20% دوز** (✅ ADA Fig 9.5).
- **تبدیل basal-to-basal:** واحد‌به‌واحد؛ کاهش **10–20%** در کنترل سخت‌گیرانه/پرخطرِ هیپو؛ معمولاً لازم هنگام سوئیچ از NPH یا به U-300/degludec (✅ سند منجمد §6.4.3).

### ۲.۳ Basal-plus و prandial
- **افزودن بولوس اول: 4 U** یا **10% دوز basal** با بزرگ‌ترین وعده (✅ ADA Fig 9.5).
- اگر **A1c <8%**: هنگام افزودن بولوس، basal را **4 U یا 10%** کم کن (✅).
- تیتر بولوس: **+1–2 U یا 10–15% دو بار در هفته** (✅).

### ۲.۴ Correction bolus
⚠️ **DELTA-4:** فرمول ISF **جزو ADA نیست** — قرارداد بالینی (Walsh/Roberts):
- آنالوگ سریع: **ISF ≈ 1800/TDD** («1800 rule»)
- انسولین regular: **ISF ≈ 1500/TDD**
- عدد «1700» گاهی نقل می‌شود اما استاندارد مرجع 1800/1500 است؛ در rule engine باید به‌عنوان *estimate با تأیید پزشک* و صرفاً برای TDD پایدار استفاده شود.
- Correction dose = (BG − target)/ISF؛ فقط با BGM/CGM و بدون هم‌پوشانی با دوز وعدهٔ اخیر.

### ۲.۵ Overbasalization check
- آستانهٔ ADA: basal **> ~0.5 U/kg/day** → نشانهٔ overbasalization → افزودن GLP-1 RA/dual یا prandial به‌جای افزایش basal (✅ ADA 2026 §9؛ سند منجمد §6.4.4 سیگنال‌ها را دارد ولی عدد 0.5 را ندارد → 🆕 تکمیل).
- ⚠️ یادداشت: Clinical Diabetes 2025;43:123 این آستانه را heuristic می‌داند (نه حد ایمنی مطلق) — قانون را soft-flag کنیم نه hard-stop.

### ۲.۶ ترکیب با GLP-1
✅ 9.22 (A): افزودن GLP-1 RA/dual به basal توصیه می‌شود؛ بازارزیابی دوز انسولین؛ FRC (IDegLira/iGlarLixi) گزینه است.

---

## ۳) هیپوگلیسمی و روز بیماری

### ۳.۱ طبقه‌بندی (✅ تأیید — ADA 2026 §6, Table 6.4)
- **Level 1:** <70 و ≥54 mg/dL
- **Level 2:** <54 mg/dL
- **Level 3:** رخداد شدید با اختلال ذهنی/جسمی نیازمند کمک دیگران، مستقل از عدد گلوکز

### ۳.۲ درمان (Rule of 15 / 15-15)
✅ فرد هوشیار با BG <70: **15 g کربوهیدرات سریع** (گلوکز خالص ترجیح) → چک پس از **15 دقیقه** → تکرار تا رفع («15-15»). AID users: **5–10 g**. آکاربوز: فقط گلوکز خالص. پس از رفع، در صورت ادامهٔ اثر انسولین/SU، میان‌وعده. *(ADA 2026 §6.15 + ADA patient page.)*

### ۳.۳ گلوکاگون
✅ تجویز برای **همهٔ تحت‌انسولین‌ها** (6.16، A)؛ فرم آمادهٔ تزریق/داخل‌بینی ترجیح دارد؛ آموزش اطرافیان.

### ۳.۴ Sick-day rules (✅ تأیید + تکمیل)
- Hold **metformin** و **SGLT2i** با عدم‌تحمل خوراکی/خطر AKI؛ **GLP-1/dual** با GI شدید؛ **TZD** با تشدید HF/پرحجمی؛ SU با آنتی‌بیوتیک‌های تداخلی کاهش/قطع.
- **basal حتی با نخوردن غذا قطع نشود**؛ کتون در علائم یا BG >200 (کتون خون ترجیح).
- ⚠️ هشدار **DKA یوگلایسمیک** با SGLT2i (گلوکز ممکن است <200 باشد) — در rule engine شرط «تهوع/استفراغ + کتون مثبت» باید مستقل از گلوکز fire کند.

---

## ۴) نگاشت کوموربیدیتی CV/HF/CKD → کلاس (مستقل از A1c) — ✅ تأیید §6.2 سند منجمد

| وضعیت | اقدام | سطح/منبع |
|---|---|---|
| ASCVD یا ریسک بسیار بالا | GLP-1 RA و/یا SGLT2i دارای منفعت اثبات‌شده؛ ترکیب هر دو قابل‌بررسی | 9.7 A؛ 10.40a–d (B برای ترکیب) |
| HF (HFrEF/HFpEF) | SGLT2i؛ در HFpEF+چاقی علامت‌دار: tirzepatide (9.9a A) و/یا GLP-1 RA (9.9b) | 9.8 A؛ 10.41 |
| CKD eGFR 20–60 ± آلبومینوری | SGLT2i یا GLP-1 RA | 9.10/11.7a-b A |
| eGFR <30 | GLP-1 RA ترجیح؛ دیالیز: GLP-1 غیروابسته به کلیه | 9.11 B/C |
| فینرنون | eGFR ≥25 + آلبومینوری روی max ACEi/ARB؛ K⁺ در ۱ ماه؛ شروع هم‌زمان با SGLT2i اگر UACR ≥100 و eGFR 30–90 | 11.8 A؛ 11.9 B |
| منع‌ها | TZD در HF؛ saxagliptin احتیاط HF؛ DPP-4i+GLP-1 ممنوع | Table 9.2؛ 9.18 B |

---

## ۵) فهرست DELTAها (خلاصهٔ مدیریتی)

1. **⚠️ DELTA-1 — Empagliflozin max:** label US (rev 10/2025) افزایش به **25 mg** برای کنترل گلایسمی را در متحمل‌ها مجاز می‌داند؛ فرض «10 mg max T2D» منقضی است. (سند منجمد عدد نداشت → fill با گیت tolerance.)
2. **⚠️ DELTA-2 — Semaglutide خوراکی:** شروع **3 mg** (نه 0.25)؛ مسیر 3→7→14. فرمولاسیون جدید R2 (1.5/4/9) ثبت شده — فعلاً out-of-scope، علامت‌گذاری شود.
3. **⚠️ DELTA-3 — Sitagliptin renal:** eGFR 30–<45 → **50 mg**؛ 25 mg فقط eGFR <30/HD.
4. **⚠️ DELTA-4 — ISF:** استاندارد **1800/TDD** (آنالوگ سریع) و **1500/TDD** (regular)؛ «1700» غیراستاندارد است و ISF اصلاً داخل ADA نیست → قانون estimate با تأیید پزشک.
5. **ℹ️ NOTE — Canagliflozin:** در eGFR 30–<60 سقف **100 mg** است (200 mg فقط با UGT-inducer).
6. **ℹ️ NOTE — Overbasalization:** آستانهٔ 0.5 U/kg/day heuristic است؛ soft-rule.
7. **ℹ️ NOTE — Trulicity:** برخی منابع ثانویه سقف 1.5 mg را نمایش می‌دهند؛ label رسمی بزرگسال **4.5 mg** است.

## ۶) شکاف‌ها (Gaps)

1. دوز premixed/self-mixed و الگوریتم‌های NPH دوبار‌روز (ADA عدد کامل نمی‌دهد) — برای rules فعلی out-of-scope.
2. Carb ratio (450–500/TDD) — قرارداد غیر-ADA؛ اگر لازم شد جداگانه مستند و تأیید پزشک شود.
3. دوزهای Wegovy/Zepbound (اندیکاسیون چاقی) خارج از دامنهٔ گلایسمیک این بسته.
4. Insulin concentrated (U-500/U-300/U-200) conversions — نیازمند سند جداگانه.
5. Pediatric (10–17y) dosing برای Ozempic/Mounjaro/Trulicity در label هست ولی خارج از دامنهٔ بزرگسال این ruleset.
6. فصل ۱۶ ADA (DKA/HHS بستری) همچنان استخراج‌نشده (gap سند منجمد §12.2 پابرجاست).

## ۷) نگاشت پیشنهادی به قوانین اجرایی (~۳۵ قانون)

```
T2-DOS-MET-01  start IR 500 BID (titrate +500/wk, max 2550)
T2-DOS-MET-02  start ER 500-1000 qPM (max 2000)
T2-DOS-MET-03  eGFR 30-45: no initiate / halve if falls
T2-DOS-MET-04  eGFR <30: stop/contraindicated (+B12 monitoring followup)
T2-DOS-SGLT2-01 empa start 10 → 25 if tolerated & needs (glycemic gate eGFR>=30)
T2-DOS-SGLT2-02 dapa start 5 → 10 (glycemic init eGFR>=45)
T2-DOS-SGLT2-03 cana eGFR>=60: 100→300
T2-DOS-SGLT2-04 cana eGFR 30-<60: cap 100 ; <30 no-initiate
T2-DOS-SGLT2-05 hold 3d pre-surgery/prolonged fasting (class)
T2-DOS-GLP1-01 semaSC 0.25x4w→0.5→1→2
T2-DOS-GLP1-02 semaPO 3mg x30d→7→14 (fasting rules)
T2-DOS-GLP1-03 lira 0.6x1w→1.2→1.8
T2-DOS-GLP1-04 dula 0.75x4w→1.5→3→4.5
T2-DOS-GLP1-05 tirz 2.5x4w→+2.5/q4w→15
T2-DOS-GLP1-06 exenatideBID 5mcgx1mo→10 ; exenatideER 2mg wk
T2-DOS-GLP1-07 lixi/exenatide avoid eGFR<=30
T2-DOS-DPP4-01 sita 100 / 50 (30-45) / 25 (<30)
T2-DOS-DPP4-02 saxa 5 / 2.5 (<45 or CYP3A4i)
T2-DOS-DPP4-03 lina 5 fixed ; alo 25/12.5/6.25
T2-DOS-TZD-01 pio 15-30 →45 (NYHA I-II start 15)
T2-DOS-TZD-02 pio hepatic gate ALT>2.5ULN no-initiate
T2-DOS-SU-01 glim 1-2 →8 (renal start 1)
T2-DOS-SU-02 glipizide 2.5-5 →40IR/20XL
T2-DOS-SU-03 glyburide not-in-CKD
T2-INS-BASAL-01 start 10U or 0.1-0.2 U/kg
T2-INS-BASAL-02 titrate +2U q3d to FPG target
T2-INS-BASAL-03 titrate alt +10-15% twice weekly
T2-INS-BASAL-04 unexplained hypo → reduce 10-20%
T2-INS-BASAL-05 basal >0.5 U/kg → overbasalization flag → add GLP-1/prandial
T2-INS-PRANDIAL-01 add 4U or 10% basal at largest meal
T2-INS-PRANDIAL-02 if A1c<8% reduce basal 4U/10%
T2-INS-CORR-01 ISF≈1800/TDD (rapid) estimate, physician-confirm
T2-HYPO-TX-01 L1/L2/L3 classification + 15-15 rule
T2-HYPO-TX-02 glucagon Rx for all insulin users
T2-SICKDAY-01 hold metf/SGLT2i/GLP-1/TZD per condition; keep basal
```

---
*منابع اصلی: ADA Standards of Care in Diabetes—2026 (Diabetes Care 2026;49(Suppl.1), §§6,9,10,11)؛ FDA PIs: Jardiance rev 10/2025، Farxiga، Invokana rev 08/2020، Ozempic 2026، Rybelsus، Victoza 2025، Trulicity، Mounjaro 2026، Byetta/DailyMed، Glucophage/XR، Januvia، Onglyza 2024، Nesina، Tradjenta، Actos، Amaryl/Sanofi، Glucotrol. ISF/carb-ratio: قرارداد Walsh (خارج از ADA).*

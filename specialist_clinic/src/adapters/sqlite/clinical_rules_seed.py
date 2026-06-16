"""Comprehensive seed of ADA T2D decision rules → clinical_rules table.

Covers EVERY section of docs/../ada_t2_rules.md: diagnosis, prediabetes,
individualized targets, medication selection, drug-safety/contraindications,
insulin, monitoring, complication screening, red-flags, hypoglycemia,
lifestyle, and vaccination.

Triggers use the machine-evaluable DSL evaluated by services/rule_engine.py.
Seeded idempotently (INSERT OR IGNORE by rule_code) so manager edits persist.
"""
import json

# --- trigger leaf helpers ---
DM = {"var": "condition", "op": "has", "value": "diabetes"}
HTN = {"var": "condition", "op": "has", "value": "hypertension"}


def ind(key, op, value, attr="latest"):
    return {"var": f"indicator.{key}.{attr}", "op": op, "value": value}


def flag(key, op="truthy", value=None):
    d = {"var": f"flag.{key}", "op": op}
    if value is not None:
        d["value"] = value
    return d


def med(value, op="has"):
    return {"var": "med.class", "op": op, "value": value}


def age(op, value):
    return {"var": "age", "op": op, "value": value}


# Rules that fire regardless of a single disease (e.g. a BP crisis, RAS-inhibitor
# monitoring) belong to the shared 'all' module, not one disease.
CROSS_DISEASE = {'T2-REDFLAG-BP', 'T2-MON-RAS-K'}


def _condition_for(r: dict) -> str:
    """Owning disease module for a rule. Explicit `condition_code` wins; otherwise
    by code prefix: the legacy T2-* catalog is the diabetes module, HTN-* is
    hypertension. Cross-disease rules map to 'all'."""
    if r.get('condition_code'):
        return r['condition_code']
    code = r['code']
    if code in CROSS_DISEASE:
        return 'all'
    if code.startswith('HTN-'):
        return 'hypertension'
    return 'diabetes'


# Each rule: code,title,category,trigger,human_if,rec,dosage,monitoring,contra,
#            evidence,action,params,severity,priority,source
RULES = [
    # ---------------- DIAGNOSIS / CLASSIFICATION (§3) ----------------
    dict(code="T2-DX-01", title="تشخیص دیابت", category="diagnosis",
         trigger={"any": [ind("hba1c", ">=", 6.5), ind("fbs", ">=", 126)]},
         human_if="A1c ≥۶.۵٪ یا قند ناشتا ≥۱۲۶ mg/dL",
         rec="معیار تشخیص دیابت مثبت است. در نبود علائم واضح هایپرگلیسمی، با یک تست دومِ غیرطبیعی تأیید شود.",
         evidence="B", action="classify", params={"label": "diabetes"},
         severity="warn", priority=10, source="ADA 2.1a/2.1b"),
    dict(code="T2-DX-02", title="پیش‌دیابت", category="diagnosis",
         trigger={"any": [ind("hba1c", "between", [5.7, 6.4]), ind("fbs", "between", [100, 125])]},
         human_if="A1c ۵.۷–۶.۴٪ یا قند ناشتا ۱۰۰–۱۲۵ mg/dL",
         rec="برچسب پیش‌دیابت؛ آموزش سبک‌زندگی و تستِ سالانه. کاهش وزن ۷٪ + فعالیت برای پیشگیری.",
         evidence="B", action="classify", params={"label": "prediabetes"},
         severity="info", priority=20, source="ADA Table 2.2"),

    # ---------------- INDIVIDUALIZED TARGETS (§4) ----------------
    dict(code="T2-TGT-A1C-STRICT", title="هدف سخت‌گیرانهٔ A1c", category="target",
         trigger={"all": [DM, flag("frailty", "==", "robust"), flag("hypo_risk", "!=", "high")]},
         human_if="بیمارِ سالم، ریسک هیپوگلیسمی پایین، امید زندگی کافی",
         rec="هدفِ A1c <۶.۵٪ ممکن است مناسب باشد (در صورت دستیابیِ بی‌خطر).",
         evidence="B", action="set_target", params={"indicator": "hba1c", "target": 6.5},
         severity="info", priority=30, source="ADA 6.4"),
    dict(code="T2-TGT-A1C-RELAXED", title="هدف آسان‌گیرانهٔ A1c", category="target",
         trigger={"all": [DM, {"any": [flag("frailty", "==", "complex"), age(">=", 75), flag("hypo_risk", "==", "high")]}]},
         human_if="سالمند/فراژیل، ریسک هیپو بالا، کوموربیدیتی شدید یا امید زندگیِ محدود",
         rec="هدفِ A1c کمتر سخت‌گیرانه (تا <۸٪)؛ پرهیز از هیپوگلیسمی و هایپرگلیسمیِ علامت‌دار.",
         evidence="B", action="set_target", params={"indicator": "hba1c", "target": 8.0},
         severity="info", priority=31, source="ADA 6.5 / 13.x"),
    dict(code="T2-TGT-BP-01", title="هدف فشار خون", category="target",
         trigger={"all": [DM]},
         human_if="دیابت نوع ۲ بزرگسال",
         rec="هدفِ فشار <۱۳۰/۸۰ mmHg اگر ایمن قابل‌دستیابی باشد؛ در ریسک بالای قلبی/کلیوی SBP <۱۲۰ تشویق می‌شود.",
         evidence="A", action="set_target", params={"indicator": "bp_systolic", "target": 130},
         severity="info", priority=32, source="ADA 10.4/11.5"),
    dict(code="T2-TGT-LIPID-01", title="هدف LDL در پرخطر", category="target",
         trigger={"all": [DM, age("between", [40, 75]), {"any": [flag("ascvd"), flag("cvd_high_risk")]}]},
         human_if="سن ۴۰–۷۵ + ریسک بالای قلبی-عروقی",
         rec="استاتین پرقدرت با هدفِ LDL <۷۰ mg/dL و کاهش ≥۵۰٪ از پایه.",
         evidence="A", action="set_target", params={"indicator": "ldl", "target": 70},
         severity="info", priority=33, source="ADA 10.20"),
    dict(code="T2-TGT-WEIGHT-01", title="هدف کاهش وزن", category="target",
         trigger={"all": [DM, ind("bmi", ">=", 25)]},
         human_if="دیابت نوع ۲ + اضافه‌وزن/چاقی",
         rec="کاهش وزن هدفِ اولیه باشد: ۵–۷٪ بهبود گلایسمی، >۱۰٪ منافع بیشتر و احتمال remission.",
         evidence="A", action="educate", severity="info", priority=34, source="ADA 8.5"),

    # ---------------- MEDICATION SELECTION (§6.2) ----------------
    dict(code="T2-MED-FIRST-01", title="شروع درمان دارویی", category="medication",
         trigger={"all": [DM, ind("hba1c", ">=", 8.5)]},
         human_if="A1c حدود ۱.۵–۲٪ بالاتر از هدف",
         rec="شروع بدون تأخیر؛ درمانِ ترکیبیِ اولیه را در نظر بگیرید تا زمانِ رسیدن به هدف کوتاه شود.",
         evidence="A", action="suggest_med", severity="warn", priority=40, source="ADA 9.6"),
    dict(code="T2-MED-ASCVD-01", title="ASCVD یا ریسک بالای قلبی-عروقی", category="medication",
         trigger={"all": [DM, {"any": [flag("ascvd"), flag("cvd_high_risk")]}]},
         human_if="ASCVD مستقر یا ریسک بسیار بالای قلبی-عروقی",
         rec="GLP-1 RA و/یا SGLT2i با منفعتِ اثبات‌شدهٔ قلبی-عروقی — مستقل از A1c.",
         evidence="A", action="suggest_med", params={"classes": ["glp1_ra", "sglt2i"]},
         severity="warn", priority=41, source="ADA 9.7 / 10.40"),
    dict(code="T2-MED-HF-01", title="نارسایی قلب", category="medication",
         trigger={"all": [DM, flag("hf")]},
         human_if="دیابت نوع ۲ + نارسایی قلب (HFrEF یا HFpEF)",
         rec="SGLT2i برای کاهش بستریِ HF — مستقل از A1c. در HFpEF + چاقیِ علامت‌دار، dual GIP/GLP-1 یا GLP-1 RA.",
         contraindications="پیوگلیتازون (TZD) در HF ممنوع است.",
         evidence="A", action="suggest_med", params={"classes": ["sglt2i"]},
         severity="warn", priority=42, source="ADA 9.8 / 10.41"),
    dict(code="T2-MED-CKD-01", title="CKD (eGFR ۲۰–۶۰ یا آلبومینوری)", category="medication",
         trigger={"all": [DM, {"any": [ind("egfr", "between", [20, 60]), flag("ckd_stage_a", "in", ["A2", "A3"]), ind("uacr", ">=", 30)]}]},
         human_if="CKD با eGFR ۲۰–۶۰ و/یا آلبومینوری",
         rec="SGLT2i (شروع با eGFR ≥۲۰؛ اثر گلوکزی در <۴۵ کم) یا GLP-1 RA؛ برای کند کردن پیشرفت CKD و کاهش رخداد قلبی-عروقی.",
         evidence="A", action="suggest_med", params={"classes": ["sglt2i", "glp1_ra"]},
         severity="warn", priority=43, source="ADA 9.10 / 11.7"),
    dict(code="T2-MED-CKD-02", title="CKD پیشرفته (eGFR <۳۰)", category="medication",
         trigger={"all": [DM, ind("egfr", "<", 30)]},
         human_if="eGFR <۳۰",
         rec="GLP-1 RA ترجیح دارد (ریسک هیپوی کمتر). در دیالیز، GLP-1 غیر‌وابسته به کلیه قابل‌ادامه است.",
         contraindications="lixisenatide/exenatide در eGFR ≤۳۰ اجتناب شود.",
         evidence="B", action="suggest_med", params={"classes": ["glp1_ra"]},
         severity="warn", priority=44, source="ADA 9.11 / 11.11b"),
    dict(code="T2-MED-CKD-03", title="افزودن فینرنون", category="medication",
         trigger={"all": [DM, ind("egfr", ">=", 25), {"any": [flag("ckd_stage_a", "in", ["A2", "A3"]), ind("uacr", ">=", 30)]},
                          {"any": [med("acei"), med("arb")]}]},
         human_if="eGFR ≥۲۵ + آلبومینوری، روی حداکثر دوزِ ACEi/ARB",
         rec="افزودن nsMRA (فینرنون) برای کاهش پیشرفت CKD و رخداد قلبی-عروقی.",
         monitoring="پتاسیم را ۱ ماه پس از شروع چک کنید.",
         evidence="A", action="suggest_med", params={"classes": ["finerenone"]},
         severity="warn", priority=45, source="ADA 11.8 / 10.42"),
    dict(code="T2-MED-CKD-04", title="شروع هم‌زمان SGLT2i + فینرنون", category="medication",
         trigger={"all": [DM, ind("uacr", ">=", 100), ind("egfr", "between", [30, 90]), {"any": [med("acei"), med("arb")]}]},
         human_if="UACR ≥۱۰۰ و eGFR ۳۰–۹۰ روی مهارکنندهٔ RAS",
         rec="شروعِ هم‌زمانِ SGLT2i + فینرنون قابل‌بررسی است.",
         evidence="B", action="suggest_med", params={"classes": ["sglt2i", "finerenone"]},
         severity="info", priority=46, source="ADA 11.9"),
    dict(code="T2-MED-OBESITY-01", title="چاقی / نیاز به کاهش وزن", category="medication",
         trigger={"all": [DM, ind("bmi", ">=", 27)]},
         human_if="دیابت نوع ۲ + چاقی/اضافه‌وزن قابل‌توجه",
         rec="داروهای وزن‌کاهنده اولویت یابند؛ ترجیحاً GLP-1 RA یا dual GIP/GLP-1 (سمگلوتاید/تیرزپاتاید).",
         contraindications="انسولین/سولفونیل‌اوره/پیوگلیتازون وزن‌افزا هستند؛ با احتیاط.",
         evidence="A", action="suggest_med", params={"classes": ["glp1_ra", "dual_gip_glp1"]},
         severity="info", priority=47, source="ADA 8.16 / 8.18"),
    dict(code="T2-MED-MASLD-01", title="MASLD / MASH", category="medication",
         trigger={"all": [DM, flag("masld")]},
         human_if="دیابت نوع ۲ + کبد چربِ متابولیک",
         rec="GLP-1 RA (با منفعت در MASH) یا dual GIP/GLP-1. در MASHِ اثبات‌شده، GLP-1 RA ترجیح دارد.",
         evidence="A", action="suggest_med", params={"classes": ["glp1_ra", "dual_gip_glp1"]},
         severity="info", priority=48, source="ADA 9.12 / 9.13"),
    dict(code="T2-MED-HYPO-01", title="ریسک بالای هیپوگلیسمی", category="medication",
         trigger={"all": [DM, flag("hypo_risk", "==", "high")]},
         human_if="ریسک بالای هیپوگلیسمی",
         rec="داروهای کم‌هیپو ترجیح داده شوند؛ انسولین/سولفونیل‌اوره/مگلیتینید را deintensify یا تعویض کنید.",
         evidence="B", action="flag_risk", severity="warn", priority=49, source="ADA 6.6 / 9.17"),
    dict(code="T2-MED-OLDER-01", title="سالمند / فراژیل", category="medication",
         trigger={"all": [DM, {"any": [age(">=", 75), flag("frailty", "in", ["intermediate", "complex"])]}]},
         human_if="سالمندِ با وضعیت پیچیده/میانی یا فراژیل",
         rec="داروهای با ریسک پایین هیپوگلیسمی؛ اهداف A1c شل‌تر؛ پرهیز از هیپو و هایپرِ علامت‌دار.",
         evidence="C", action="educate", severity="info", priority=50, source="ADA 13.13"),
    dict(code="T2-MED-COMBO-01", title="منعِ ترکیب DPP-4i با GLP-1", category="drug_safety",
         trigger={"all": [med("dpp4i"), {"any": [med("glp1_ra"), med("dual_gip_glp1")]}]},
         human_if="مصرف هم‌زمانِ DPP-4i و GLP-1 RA/dual",
         rec="DPP-4i را با GLP-1 RA یا dual ترکیب نکنید — منفعتِ گلوکزیِ افزوده ندارد.",
         evidence="B", action="safety_alert", severity="warn", priority=51, source="ADA 9.18"),

    # ---------------- BP / LIPID / ANTIPLATELET (§9.4) ----------------
    dict(code="T2-BP-RX-01", title="درمان فشار خون", category="bp_rx",
         trigger={"all": [DM, ind("bp_systolic", ">=", 130)]},
         human_if="فشار سیستول ≥۱۳۰ (یا دیاستول ≥۸۰)",
         rec="شروع/تشدید ضدفشار؛ اگر ≥۱۵۰/۹۰ دو دارو هم‌زمان؛ ACEi یا ARB خط اول در آلبومینوری/CAD.",
         monitoring="eGFR و پتاسیم پس از شروع/تغییر دوز.",
         contraindications="ACEi/ARB در بارداری ممنوع.",
         evidence="A", action="suggest_med", params={"classes": ["acei", "arb"]},
         severity="warn", priority=60, source="ADA 10.6/10.7/10.8"),
    dict(code="T2-LIPID-RX-01", title="استاتین‌درمانی", category="lipid_rx",
         trigger={"all": [DM, age("between", [40, 75])]},
         human_if="سن ۴۰–۷۵ + دیابت",
         rec="استاتینِ متوسط (پرخطر → پرقدرت با LDL <۷۰)؛ اگر LDL در هدف نرسید ازتیمایب/PCSK9؛ استاتین‌ناتحمل → bempedoic acid.",
         monitoring="پروفایل لیپید ۴–۱۲ هفته پس از شروع/تغییر و سپس سالانه.",
         evidence="A", action="suggest_med", params={"classes": ["statin"]},
         severity="info", priority=61, source="ADA 10.18/10.20/10.21"),
    dict(code="T2-ASA-01", title="آنتی‌پلاکت (پیشگیری ثانویه)", category="medication",
         trigger={"all": [DM, flag("ascvd")]},
         human_if="ASCVD مستقر",
         rec="آسپرین ۷۵–۱۶۲ mg برای پیشگیری ثانویه (آلرژی → کلوپیدوگرل ۷۵).",
         evidence="A", action="suggest_med", params={"classes": ["aspirin"]},
         severity="info", priority=62, source="ADA 10.33"),

    # ---------------- DRUG SAFETY / CONTRAINDICATIONS (§6.3) ----------------
    dict(code="T2-SAFE-MET-STOP", title="متفورمین در eGFR <۳۰", category="drug_safety",
         trigger={"all": [med("metformin"), ind("egfr", "<", 30)]},
         human_if="متفورمین + eGFR <۳۰",
         rec="متفورمین را قطع کنید (منع مصرف در eGFR <۳۰؛ ریسک لاکتیک‌اسیدوز).",
         evidence="", action="safety_alert", severity="urgent", priority=5, source="ADA Table 9.2"),
    dict(code="T2-SAFE-MET-REDUCE", title="متفورمین در eGFR ۳۰–۴۵", category="drug_safety",
         trigger={"all": [med("metformin"), ind("egfr", "between", [30, 45])]},
         human_if="متفورمین + eGFR ۳۰–۴۵",
         rec="دوز متفورمین را کاهش دهید؛ شروعِ جدید توصیه نمی‌شود.",
         monitoring="ویتامین B12 دوره‌ای.",
         evidence="", action="safety_alert", severity="warn", priority=6, source="ADA Table 9.2"),
    dict(code="T2-SAFE-TZD-HF", title="پیوگلیتازون در نارسایی قلب", category="drug_safety",
         trigger={"all": [med("tzd"), flag("hf")]},
         human_if="پیوگلیتازون + نارسایی قلب",
         rec="پیوگلیتازون را قطع کنید — در HF ممنوع است (احتباس مایع).",
         evidence="", action="safety_alert", severity="urgent", priority=5, source="ADA Table 9.2"),
    dict(code="T2-SAFE-SGLT2-DKA", title="آموزش ایمنیِ SGLT2i", category="drug_safety",
         trigger={"all": [med("sglt2i")]},
         human_if="مصرف SGLT2i",
         rec="آموزش علائم DKA (حتی یوگلایسمیک، گلوکز <۲۰۰) و سنجش کتون؛ قطع ۳–۴ روز پیش از جراحی/بیماری بحرانی/روزهٔ طولانی.",
         contraindications="سابقهٔ DKA؛ مراقب گانگرن فورنیه و عفونت تناسلی.",
         evidence="", action="safety_alert", severity="info", priority=70, source="ADA Table 9.2"),
    dict(code="T2-SAFE-GLP1-SURG", title="ایمنیِ GLP-1/dual", category="drug_safety",
         trigger={"all": [{"any": [med("glp1_ra"), med("dual_gip_glp1")]}]},
         human_if="مصرف GLP-1 RA یا dual",
         rec="قبل از بیهوشی/سداسیون عمیق طبق راهنما قطع شود (ریسک آسپیراسیون). در گاستروپارزی توصیه نمی‌شود؛ مراقب پانکراتیت.",
         evidence="", action="safety_alert", severity="info", priority=71, source="ADA Table 9.2"),
    dict(code="T2-SAFE-SU-HYPO", title="سولفونیل‌اوره و هیپوگلیسمی", category="drug_safety",
         trigger={"all": [med("su"), flag("hypo_risk", "==", "high")]},
         human_if="سولفونیل‌اوره + ریسک بالای هیپو",
         rec="سولفونیل‌اوره هیپوگلیسمی‌زاست؛ deintensify یا تعویض با داروی کم‌هیپو. گلیبوراید در CKD توصیه نمی‌شود.",
         evidence="", action="safety_alert", severity="warn", priority=72, source="ADA Table 9.2"),

    # ---------------- INSULIN (§6.4) ----------------
    dict(code="T2-INS-START-01", title="شروع انسولین", category="insulin",
         trigger={"all": [DM, ind("hba1c", ">", 10)]},
         human_if="A1c >۱۰٪ یا گلوکز ≥۳۰۰ یا علائم کاتابولیسم/هایپرگلیسمی",
         rec="شروع انسولین را در نظر بگیرید. در نبودِ بحران، درمانِ مبتنی‌بر‌GLP-1 بر انسولین ترجیح دارد.",
         dosage_titration="basal: شروع ۱۰ واحد/روز یا ۰.۱–۰.۲ U/kg.",
         evidence="E", action="suggest_med", params={"classes": ["insulin_basal"]},
         severity="warn", priority=80, source="ADA 9.20/9.21"),
    dict(code="T2-INS-BASAL-01", title="تیترِ انسولین پایه", category="insulin",
         trigger={"all": [med("insulin_basal")]},
         human_if="مصرف انسولین پایه",
         rec="تیتر تا رسیدن به FPG هدف بدون هیپو.",
         dosage_titration="شروع ۱۰U یا ۰.۱–۰.۲U/kg؛ تیتر +۲ واحد هر ۳ روز (یا ۱۰–۱۵٪ دوبار/هفته)؛ هیپوی بدون‌علت → کاهش ۱۰–۲۰٪.",
         monitoring="مراقب overbasalization (هیپو، تغییرپذیریِ بالا).",
         evidence="", action="educate", severity="info", priority=81, source="ADA Fig 9.5"),
    dict(code="T2-INS-PRANDIAL-01", title="تیترِ انسولین بولوس", category="insulin",
         trigger={"all": [med("insulin_bolus")]},
         human_if="مصرف انسولین پراندیال",
         rec="افزودن بولوس با بزرگ‌ترین وعده/بیشترین جهشِ پس‌غذا.",
         dosage_titration="شروع ۴ واحد یا ۱۰٪ basal؛ اگر A1c <۸٪ basal را ۴واحد/۱۰٪ کم کن؛ تیتر +۱–۲ واحد یا ۱۰–۱۵٪ دوبار/هفته؛ هیپو → کاهش ۱۰–۲۰٪.",
         evidence="", action="educate", severity="info", priority=82, source="ADA Fig 9.5"),
    dict(code="T2-INS-GLUCAGON-01", title="گلوکاگون", category="insulin",
         trigger={"all": [{"any": [med("insulin_basal"), med("insulin_bolus")]}]},
         human_if="بیمارِ تحت انسولین",
         rec="گلوکاگون (فرم آمادهٔ تزریق/داخل‌بینی) تجویز شود؛ آموزشِ اطرافیان (هرگز انسولین در هیپو).",
         evidence="A", action="educate", severity="info", priority=83, source="ADA 6.16"),

    # ---------------- MONITORING / DRUG-SPECIFIC (§8) ----------------
    dict(code="T2-FU-A1C-01", title="پایش A1c", category="monitoring",
         trigger={"all": [DM]},
         human_if="دیابت نوع ۲",
         rec="A1c هر ۳ ماه اگر خارج هدف/تغییر درمان؛ هر ۶ ماه اگر پایدار و در هدف.",
         evidence="E", action="create_followup", params={"item": "a1c"},
         severity="info", priority=90, source="ADA 6.2"),
    dict(code="T2-MON-FINERENONE-K", title="پتاسیم پس از فینرنون", category="monitoring",
         trigger={"all": [med("finerenone")]},
         human_if="شروع فینرنون",
         rec="پتاسیم را ۱ ماه پس از شروع چک کنید.",
         evidence="A", action="create_followup", params={"item": "potassium"},
         severity="warn", priority=91, source="ADA 11.8"),
    dict(code="T2-MON-MET-B12", title="B12 با متفورمین", category="monitoring",
         trigger={"all": [med("metformin")]},
         human_if="مصرف طولانی متفورمین",
         rec="سطح ویتامین B12 را دوره‌ای پایش کنید (ریسک کمبود و تشدید نوروپاتی).",
         evidence="", action="educate", severity="info", priority=92, source="ADA Table 9.2"),
    dict(code="T2-MON-STATIN-LIPID", title="لیپید پس از استاتین", category="monitoring",
         trigger={"all": [med("statin")]},
         human_if="شروع/تغییر استاتین",
         rec="پروفایل لیپید ۴–۱۲ هفته پس از شروع/تغییر دوز، سپس سالانه.",
         evidence="A", action="create_followup", params={"item": "lipid"},
         severity="info", priority=93, source="ADA 10.17"),
    dict(code="T2-MON-RAS-K", title="eGFR/K⁺ با ACEi/ARB/MRA", category="monitoring",
         trigger={"all": [{"any": [med("acei"), med("arb"), med("finerenone")]}]},
         human_if="مصرف ACEi/ARB/MRA",
         rec="eGFR و پتاسیم را هنگام شروع و دوره‌ای پایش کنید.",
         evidence="B", action="create_followup", params={"item": "renal_function"},
         severity="info", priority=94, source="ADA 10.11/11.6b"),

    # ---------------- COMPLICATION SCREENING (§9) ----------------
    dict(code="T2-SCR-RENAL", title="غربالگری کلیه", category="screening",
         trigger={"all": [DM]},
         human_if="همهٔ بیماران دیابتی",
         rec="UACR + eGFR حداقل سالانه؛ در CKD، ۱–۴ بار در سال بر اساس مرحله.",
         evidence="B", action="schedule_screening", params={"item": "renal", "interval_months": 12},
         severity="info", priority=100, source="ADA 11.1"),
    dict(code="T2-SCR-EYE", title="غربالگری چشم", category="screening",
         trigger={"all": [DM]},
         human_if="همهٔ بیماران دیابتی",
         rec="معاینهٔ گشاد‌شدهٔ چشم در زمان تشخیص؛ سالانه (یا هر ۲ سال اگر بدون رتینوپاتی و در هدف).",
         evidence="B", action="schedule_screening", params={"item": "eye", "interval_months": 12},
         severity="info", priority=101, source="ADA 12.4/12.5"),
    dict(code="T2-SCR-NEURO", title="غربالگری نوروپاتی", category="screening",
         trigger={"all": [DM]},
         human_if="همهٔ بیماران دیابتی",
         rec="غربالگری نوروپاتی محیطی در تشخیص و سپس سالانه (مونوفیلامان ۱۰گرمی + دیاپازون).",
         evidence="B", action="schedule_screening", params={"item": "neuropathy", "interval_months": 12},
         severity="info", priority=102, source="ADA 12.17/12.18"),
    dict(code="T2-SCR-FOOT", title="معاینهٔ پا", category="screening",
         trigger={"all": [DM]},
         human_if="همهٔ بیماران دیابتی",
         rec="معاینهٔ جامع پا حداقل سالانه؛ اگر حس مختل یا سابقهٔ زخم/قطع عضو → هر ویزیت.",
         evidence="A", action="schedule_screening", params={"item": "foot", "interval_months": 12},
         severity="info", priority=103, source="ADA 12.23/12.25"),
    dict(code="T2-SCR-FOOT-FREQ", title="معاینهٔ پا در هر ویزیت", category="screening",
         trigger={"all": [DM, flag("monofilament", "==", "impaired")]},
         human_if="حس محافظتیِ پا مختل است",
         rec="معاینهٔ پا در هر ویزیت انجام شود؛ ارجاع به تیم پای دیابتی.",
         evidence="A", action="schedule_screening", params={"item": "foot", "interval_months": 0},
         severity="warn", priority=104, source="ADA 12.25"),
    dict(code="T2-SCR-MASLD", title="غربالگری کبد چرب (FIB-4)", category="screening",
         trigger={"all": [DM]},
         human_if="دیابت نوع ۲ (به‌ویژه چاقی/ریسک کاردیومتابولیک)",
         rec="FIB-4 حتی با آنزیم نرمال؛ اگر ≥۱.۳ → elastography/ELF؛ ریسک بالا → ارجاع کبد.",
         evidence="B", action="schedule_screening", params={"item": "masld", "interval_months": 12},
         severity="info", priority=105, source="ADA 4.22/4.23"),

    # ---------------- RED FLAGS (§7.4) ----------------
    dict(code="T2-REDFLAG-BP", title="بحران فشار خون", category="redflag",
         trigger={"any": [ind("bp_systolic", ">=", 180), ind("bp_diastolic", ">=", 110)]},
         human_if="فشار ≥۱۸۰/۱۱۰ mmHg",
         rec="🚨 نیاز به اقدام سریع؛ اگر همراه با علائم قلبی-عروقی، ارجاع/اورژانس فوری.",
         evidence="", action="redflag", severity="urgent", priority=1, source="ADA 10 / فصل ۶"),
    dict(code="T2-REDFLAG-SEVERE-HYPER", title="هایپرگلیسمی شدید", category="redflag",
         trigger={"any": [ind("fbs", ">=", 300), ind("hba1c", ">", 12)]},
         human_if="گلوکز ≥۳۰۰ یا A1c >۱۲٪",
         rec="🚨 ارزیابی برای کاتابولیسم/کتوز/DKA؛ شروع انسولین و در صورت علائم، اقدام فوری. مراقب DKAِ یوگلایسمیک با SGLT2i.",
         evidence="", action="redflag", severity="urgent", priority=2, source="ADA 9.20 / فصل ۶"),

    # ---------------- HYPOGLYCEMIA (§7) ----------------
    dict(code="T2-HYPO-TX-01", title="درمان هیپوگلیسمی (قاعدهٔ ۱۵)", category="hypo",
         trigger=None,
         human_if="فردِ هوشیار با گلوکز <۷۰",
         rec="۱۵ گرم کربوهیدراتِ حاویِ گلوکز؛ پس از ۱۵ دقیقه چک و در صورت ادامه تکرار. کاربر AID: ۵–۱۰ گرم. آکاربوز: فقط گلوکز خالص.",
         evidence="B", action="educate", severity="info", priority=110, source="ADA 6.15"),

    # ---------------- LIFESTYLE / EDUCATION (§5) ----------------
    dict(code="T2-DSMES-01", title="آموزش خودمدیریتی (DSMES)", category="lifestyle",
         trigger={"all": [DM]},
         human_if="همهٔ بیماران دیابتی",
         rec="DSMES در زمان تشخیص، سالانه، هنگام نرسیدن به اهداف و در گذارهای مراقبتی.",
         evidence="A", action="educate", severity="info", priority=120, source="ADA 5.1/5.2"),
    dict(code="T2-MNT-01", title="تغذیه‌درمانی (MNT)", category="lifestyle",
         trigger={"all": [DM]},
         human_if="همهٔ بیماران دیابتی",
         rec="الگوی غذاییِ فردی؛ سدیم <۲۳۰۰ mg/روز؛ فیبر ≥۱۴g/1000kcal؛ ترجیح آب؛ کاهش نوشیدنی‌های شیرین.",
         evidence="B", action="educate", severity="info", priority=121, source="ADA 5.10–5.24"),
    dict(code="T2-PA-01", title="فعالیت بدنی", category="lifestyle",
         trigger={"all": [DM]},
         human_if="بیشتر بزرگسالان دیابتی",
         rec="≥۱۵۰ دقیقه/هفته فعالیت هوازیِ متوسط (≥۳ روز)؛ مقاومتی ۲–۳ بار/هفته؛ قطع نشستنِ طولانی هر ۳۰ دقیقه.",
         evidence="B", action="educate", severity="info", priority=122, source="ADA 5.34–5.37"),
    dict(code="T2-TOBACCO-01", title="ترک دخانیات", category="lifestyle",
         trigger={"all": [DM, flag("smoking", "in", ["current", "vape"])]},
         human_if="مصرف فعلیِ دخانیات/ویپ",
         rec="توصیه به ترکِ کامل؛ مشاوره + دارودرمانیِ ترک ارائه/ارجاع شود.",
         evidence="A", action="educate", severity="warn", priority=123, source="ADA 5.40"),
    dict(code="T2-WT-SURG-01", title="جراحی متابولیک", category="lifestyle",
         trigger={"all": [DM, ind("bmi", ">=", 30)]},
         human_if="BMI ≥۳۰ (≥۲۷.۵ در آسیایی‌تبارها) و کاندیدِ مناسب",
         rec="جراحی متابولیک به‌عنوان گزینهٔ درمانی در نظر گرفته شود؛ پایش بلندمدتِ ریزمغذی/متابولیک.",
         evidence="A", action="educate", severity="info", priority=124, source="ADA 8.22/8.25"),

    # ---------------- VACCINATION (§10) ----------------
    dict(code="T2-VACC-FLU", title="واکسن آنفلوانزا", category="vaccination",
         trigger={"all": [DM]}, human_if="همهٔ بیماران دیابتی",
         rec="واکسن آنفلوانزای سه‌ظرفیتی، سالانه (نه واکسن زندهٔ تخفیف‌یافته).",
         evidence="", action="vaccine", params={"vaccine": "influenza", "interval_months": 12},
         severity="info", priority=130, source="ADA Table 4.3"),
    dict(code="T2-VACC-TDAP", title="واکسن Tdap", category="vaccination",
         trigger={"all": [DM]}, human_if="همهٔ بزرگسالان",
         rec="بوستر Tdap هر ۱۰ سال.",
         evidence="", action="vaccine", params={"vaccine": "tdap", "interval_months": 120},
         severity="info", priority=131, source="ADA Table 4.3"),
    dict(code="T2-VACC-ZOSTER", title="واکسن زوستر", category="vaccination",
         trigger={"all": [DM, age(">=", 50)]}, human_if="سن ≥۵۰",
         rec="واکسن زوستر (Shingrix) دو دوز، حتی اگر قبلاً واکسینه شده.",
         evidence="", action="vaccine", params={"vaccine": "zoster"},
         severity="info", priority=132, source="ADA Table 4.3"),
    dict(code="T2-VACC-PNEUMO", title="واکسن پنوموکوک", category="vaccination",
         trigger={"all": [DM]}, human_if="بزرگسالان دیابتی",
         rec="واکسن پنوموکوک طبق سن و دستورالعمل CDC (PCV15/PCV20/PPSV23).",
         evidence="", action="vaccine", params={"vaccine": "pneumococcal"},
         severity="info", priority=133, source="ADA Table 4.3"),
    dict(code="T2-VACC-RSV", title="واکسن RSV", category="vaccination",
         trigger={"all": [DM, age(">=", 75)]}, human_if="سن ≥۷۵ (یا ۶۰+ پرخطر)",
         rec="یک دوزِ واحد واکسن RSV.",
         evidence="", action="vaccine", params={"vaccine": "rsv"},
         severity="info", priority=134, source="ADA Table 4.3"),
    dict(code="T2-VACC-COVID", title="واکسن کووید-۱۹", category="vaccination",
         trigger={"all": [DM]}, human_if="همهٔ افراد ≥۶ ماه",
         rec="واکسیناسیون کووید-۱۹ و بوسترِ جاری طبق دستورالعمل.",
         evidence="", action="vaccine", params={"vaccine": "covid19"},
         severity="info", priority=135, source="ADA Table 4.3"),

    # ================= HYPERTENSION MODULE (standalone disease pack) =================
    # Fires for patients with the `hypertension` condition (independent of diabetes).
    dict(code="HTN-TGT-BP-01", title="هدف فشار خون", category="target",
         trigger={"all": [HTN]},
         human_if="بیمار مبتلا به فشار خون",
         rec="هدفِ <۱۳۰/۸۰ mmHg اگر بی‌خطر قابل‌دستیابی باشد؛ در سالمندِ فراژیل هدفِ شل‌تر (<۱۴۰/۹۰).",
         evidence="", action="set_target", params={"indicator": "bp_systolic", "target": 130},
         severity="info", priority=30, source="پروتکل فشار خون"),
    dict(code="HTN-MED-FIRST-01", title="شروع درمان ضدفشار", category="medication",
         trigger={"all": [HTN, {"any": [ind("bp_systolic", ">=", 140), ind("bp_diastolic", ">=", 90)]}]},
         human_if="فشار ≥۱۴۰/۹۰ با وجود اصلاح سبک‌زندگی",
         rec="شروع داروی ضدفشار؛ خط اول: تیازید، ACEi/ARB یا کلسیم‌بلاکر (CCB).",
         monitoring="فشار خانگی؛ eGFR/پتاسیم پس از شروع ACEi/ARB.",
         contraindications="ACEi/ARB در بارداری ممنوع.",
         evidence="", action="suggest_med", params={"classes": ["thiazide", "acei", "arb", "ccb"]},
         severity="warn", priority=40, source="پروتکل فشار خون"),
    dict(code="HTN-MED-COMBO-01", title="درمان ترکیبی فشار", category="medication",
         trigger={"all": [HTN, {"any": [ind("bp_systolic", ">=", 150), ind("bp_diastolic", ">=", 90)]}]},
         human_if="فشار ≥۱۵۰/۹۰",
         rec="شروع با ترکیبِ دو دارو (ترجیحاً ACEi/ARB + CCB یا تیازید) برای رسیدنِ سریع‌تر به هدف.",
         evidence="", action="suggest_med", params={"classes": ["acei", "arb", "ccb", "thiazide"]},
         severity="warn", priority=41, source="پروتکل فشار خون"),
    dict(code="HTN-MED-RAS-01", title="ACEi/ARB در آلبومینوری", category="medication",
         trigger={"all": [HTN, {"any": [ind("uacr", ">=", 30), flag("ckd_stage_a", "in", ["A2", "A3"])]}]},
         human_if="فشار خون + آلبومینوری",
         rec="ACEi یا ARB خط اول است (محافظت کلیه و کاهش آلبومینوری).",
         monitoring="eGFR و پتاسیم ۲–۴ هفته پس از شروع/تغییر دوز.",
         contraindications="ترکیبِ هم‌زمانِ ACEi با ARB توصیه نمی‌شود.",
         evidence="", action="suggest_med", params={"classes": ["acei", "arb"]},
         severity="info", priority=42, source="پروتکل فشار خون"),
    dict(code="HTN-LIFE-01", title="سبک‌زندگی در فشار خون", category="lifestyle",
         trigger={"all": [HTN]},
         human_if="همهٔ بیماران فشار خون",
         rec="کاهش سدیم (<۲۳۰۰ و در صورت امکان <۱۵۰۰ mg/روز)، الگوی غذاییِ DASH، کاهش وزن، فعالیت منظم و محدودیتِ الکل.",
         evidence="", action="educate", severity="info", priority=120, source="پروتکل فشار خون"),
]


def seed_clinical_rules(db):
    """Idempotently insert the rule catalog (manager edits are preserved) and tag
    each rule's owning disease module (condition_code) — also on existing DBs."""
    for r in RULES:
        cc = _condition_for(r)
        db.execute(
            """INSERT OR IGNORE INTO clinical_rules
               (rule_code, title, category, condition_code, trigger_json, human_if, recommendation,
                dosage_titration, monitoring, contraindications, evidence_level,
                action_type, action_params_json, severity, priority, source_ref)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["code"], r["title"], r["category"], cc,
                json.dumps(r["trigger"], ensure_ascii=False) if r.get("trigger") else None,
                r.get("human_if"), r.get("rec"), r.get("dosage_titration"),
                r.get("monitoring"), r.get("contraindications"), r.get("evidence"),
                r.get("action", "educate"),
                json.dumps(r["params"], ensure_ascii=False) if r.get("params") else None,
                r.get("severity", "info"), r.get("priority", 100), r.get("source"),
            ),
        )
        # Backfill the module tag on rows created before this column existed,
        # without clobbering an intentional non-default override.
        db.execute(
            "UPDATE clinical_rules SET condition_code=? "
            "WHERE rule_code=? AND (condition_code IS NULL OR condition_code='all')",
            (cc, r["code"]))
    db.commit()

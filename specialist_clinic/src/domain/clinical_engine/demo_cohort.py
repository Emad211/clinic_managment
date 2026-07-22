"""Canonical, deterministic longitudinal cohort used by the v2 safety gate.

These records are synthetic.  They intentionally cover different treatment
paths and safety states; they are not treatment recommendations for real people.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


DEMO_COHORT_VERSION = "2026.07-longitudinal-v2"
DEMO_REFERENCE_AT = datetime(2026, 7, 22, 8, 0, 0)
DATA_START = date(2021, 1, 15)
DATA_END = date(2026, 7, 21)


def _add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    return date(year, month, min(value.day, 28))


def _dates(step_months: int) -> list[str]:
    values: list[str] = []
    current = DATA_START
    while current < DATA_END:
        values.append(current.isoformat())
        current = _add_months(current, step_months)
    if not values or values[-1] != DATA_END.isoformat():
        values.append(DATA_END.isoformat())
    return values


OBSERVATION_DATES = _dates(2)   # 35 longitudinal clinic/self-monitoring points
VISIT_DATES = _dates(3)         # 24 documented encounters
LAB_DATES = _dates(6)           # 13 complete laboratory panels


def trend(start: float, end: float, count: int, *, wave: float = 0.0) -> list[float]:
    """Deterministic trajectory with a small repeatable clinical-looking wave."""
    if count <= 1:
        return [round(float(end), 2)]
    pattern = (0.0, 0.55, -0.35, 0.25, -0.15)
    values = []
    for index in range(count):
        base = start + (end - start) * index / (count - 1)
        perturbation = pattern[index % len(pattern)] * wave
        values.append(round(base + perturbation, 2))
    values[-1] = round(float(end), 2)
    return values


_LAB_META = {
    "hba1c": ("HbA1c", "%", 4.0, 5.6),
    "egfr": ("eGFR", "mL/min/{1.73_m2}", 60, None),
    "uacr": ("نسبت آلبومین به کراتینین ادرار", "mg/g", 0, 30),
    "ldl": ("LDL-C", "mg/dL", 0, 100),
    "hdl": ("HDL-C", "mg/dL", 40, None),
    "triglyceride": ("Triglyceride", "mg/dL", 0, 150),
    "creatinine": ("Creatinine", "mg/dL", 0.6, 1.3),
    "potassium": ("Potassium", "mmol/L", 3.5, 5.1),
    "alt": ("ALT", "U/L", 0, 40),
    "ast": ("AST", "U/L", 0, 40),
}

_VITAL_META = {
    "fbs": ("mg/dL", 6.0),
    "bp_systolic": ("mmHg", 3.0),
    "bp_diastolic": ("mmHg", 2.0),
    "weight": ("kg", 0.7),
    "pulse": ("bpm", 2.0),
}


def _med(name: str, drug_class: str, dose: str, start: str, *,
         schedule: str = "روزانه", changes=(), stop: str | None = None,
         notes: str = "") -> dict[str, Any]:
    return {
        "name": name, "drug_class": drug_class, "dose": dose,
        "start": start, "schedule": schedule, "changes": list(changes),
        "stop": stop, "notes": notes,
    }


_BASE_PATIENTS: list[dict[str, Any]] = [
    {
        "nid": "TEST0001", "name": "نمونه ۱ — دیابت پایدار", "gender": "male",
        "birth": "1975-03-10", "height_cm": 176,
        "address": "تهران، پروندهٔ مصنوعی آزمون شمارهٔ ۱",
        "summary": "دیابت نوع ۲ با کنترل پایدار روی متفورمین؛ بدون عارضهٔ شناخته‌شده.",
        "conditions": [{"code": "diabetes", "onset": "2018-04-12", "stage": "T2D", "notes": "تشخیص تأییدشده؛ هدف HbA1c فردی ۷٪."}],
        "flags": {"smoking": "never", "hypo_risk": "low", "monofilament": "normal", "eye_exam_date": "2026-02-18", "foot_exam_date": "2026-04-20"},
        "vitals": {"fbs": (148, 112), "bp_systolic": (132, 124), "bp_diastolic": (84, 78), "weight": (86, 81), "pulse": (78, 72)},
        "labs": {"hba1c": (7.4, 6.6), "egfr": (94, 88), "uacr": (12, 10), "ldl": (118, 82), "hdl": (45, 49), "triglyceride": (176, 126), "creatinine": (0.9, 1.0), "potassium": (4.2, 4.3), "alt": (31, 25), "ast": (27, 23)},
        "meds": [_med("متفورمین", "metformin", "۱۰۰۰ میلی‌گرم", "2021-01-20", schedule="همراه شام")],
        "history": [("دیابت نوع ۲", "کنترل پایدار و پایبندی مناسب.", "2018-04-12")],
        "allergies": [], "surgeries": [],
        "course": ["بدون پلی‌اوری یا افت قند؛ تحمل دارویی مناسب.", "معاینه پا طبیعی و نبض‌های محیطی قابل لمس است.", "پیاده‌روی منظم و برنامه غذایی پایدار گزارش شد.", "اهداف درمان مرور شد و درمان بدون تغییر ادامه یافت."],
    },
    {
        "nid": "TEST0002", "name": "نمونه ۲ — تشدید مرحله‌ای درمان", "gender": "female",
        "birth": "1968-07-22", "height_cm": 162,
        "address": "کرج، پروندهٔ مصنوعی آزمون شمارهٔ ۲",
        "summary": "دیابت و چاقی با کنترل نامناسب اولیه؛ پاسخ تدریجی به تشدید درمان و کاهش وزن.",
        "conditions": [{"code": "diabetes", "onset": "2015-09-03", "stage": "T2D", "notes": "سابقه کنترل نامناسب؛ بدون کتوز."}],
        "flags": {"smoking": "never", "hypo_risk": "low", "monofilament": "normal", "eye_exam_date": "2025-11-12", "foot_exam_date": "2026-05-04"},
        "vitals": {"fbs": (238, 136), "bp_systolic": (142, 128), "bp_diastolic": (90, 80), "weight": (96, 84), "pulse": (84, 74)},
        "labs": {"hba1c": (10.1, 7.2), "egfr": (86, 78), "uacr": (18, 22), "ldl": (142, 86), "hdl": (39, 44), "triglyceride": (262, 154), "creatinine": (0.8, 0.9), "potassium": (4.1, 4.2), "alt": (48, 29), "ast": (39, 25)},
        "meds": [
            _med("متفورمین", "metformin", "۱۰۰۰ میلی‌گرم", "2021-01-20", schedule="دو بار در روز", changes=[("2021-05-15", "۱۰۰۰ میلی‌گرم دو بار در روز", "افزایش به‌علت HbA1c بالا")]),
            _med("امپاگلیفلوزین", "sglt2i", "۱۰ میلی‌گرم", "2022-02-10", notes="پس از مرور عملکرد کلیه شروع شد."),
            _med("سماگلوتاید", "glp1_ra", "۰٫۲۵ میلی‌گرم", "2023-03-05", schedule="هفتگی", changes=[("2023-05-05", "۰٫۵ میلی‌گرم هفتگی", "تحمل گوارشی مناسب"), ("2023-09-05", "۱ میلی‌گرم هفتگی", "تشدید برای وزن و HbA1c")]),
        ],
        "history": [("چاقی", "BMI اولیه ۳۶٫۶؛ کاهش وزن تدریجی با مداخله ترکیبی.", "2014-01-01"), ("دیابت نوع ۲", "نیازمند تشدید مرحله‌ای درمان.", "2015-09-03")],
        "allergies": [("پنی‌سیلین", "کهیر", "متوسط")], "surgeries": [("کوله‌سیستکتومی", "2012-08-16", "بدون عارضه")],
        "course": ["پلی‌اوری اولیه کاهش یافته و افت قند گزارش نشد.", "فشار و معاینه پا پایدار؛ ادم وجود ندارد.", "ثبت غذای روزانه و ۱۵۰ دقیقه فعالیت هفتگی مرور شد.", "کاهش وزن و HbA1c پس از تشدید درمان مستند شد."],
    },
    {
        "nid": "TEST0003", "name": "نمونه ۳ — CKD پیشرونده", "gender": "male",
        "birth": "1958-01-05", "height_cm": 171,
        "address": "تهران، پروندهٔ مصنوعی آزمون شمارهٔ ۳",
        "summary": "دیابت، فشارخون و CKD آلبومینوریک؛ کاهش دوز و سپس قطع متفورمین با افت eGFR.",
        "conditions": [{"code": "diabetes", "onset": "2010-06-18", "stage": "T2D", "notes": "دیابت طول‌کشیده."}, {"code": "hypertension", "onset": "2011-02-20", "stage": "stage 2", "notes": "هدف فردی فشار کمتر از ۱۳۰/۸۰."}, {"code": "ckd", "onset": "2021-08-12", "stage": "G4/A3", "notes": "روند نزولی eGFR و آلبومینوری شدید."}],
        "flags": {"ckd_stage_g": "G4", "ckd_stage_a": "A3", "hypo_risk": "atrisk", "smoking": "former", "monofilament": "impaired", "eye_exam_date": "2026-01-10", "foot_exam_date": "2026-06-01"},
        "vitals": {"fbs": (188, 146), "bp_systolic": (166, 134), "bp_diastolic": (98, 82), "weight": (89, 84), "pulse": (82, 76)},
        "labs": {"hba1c": (8.7, 7.5), "egfr": (58, 27), "uacr": (145, 520), "ldl": (132, 68), "hdl": (38, 41), "triglyceride": (228, 172), "creatinine": (1.3, 2.5), "potassium": (4.3, 4.9), "alt": (29, 24), "ast": (25, 22)},
        "meds": [
            _med("متفورمین", "metformin", "۱۰۰۰ میلی‌گرم", "2021-01-20", schedule="دو بار در روز", changes=[("2023-07-15", "۵۰۰ میلی‌گرم روزانه", "کاهش دوز با eGFR کمتر از ۴۵")], stop="2026-01-20", notes="با رسیدن eGFR به محدوده G4 قطع شد."),
            _med("لیزینوپریل", "acei", "۱۰ میلی‌گرم", "2021-01-20", changes=[("2022-06-15", "۲۰ میلی‌گرم روزانه", "فشار و آلبومینوری")]),
            _med("داپاگلیفلوزین", "sglt2i", "۱۰ میلی‌گرم", "2021-10-01"),
            _med("فینرنون", "finerenone", "۱۰ میلی‌گرم", "2023-10-10", notes="با پایش پتاسیم."),
            _med("لیناگلیپتین", "dpp4i", "۵ میلی‌گرم", "2026-02-01"),
        ],
        "history": [("CKD آلبومینوریک", "پیگیری مشترک کلیه؛ روند eGFR و پتاسیم ثبت شده است.", "2021-08-12"), ("نوروپاتی محیطی", "کاهش حس مونوفیلامان؛ آموزش مراقبت پا.", "2024-02-03")],
        "allergies": [], "surgeries": [("آنژیوگرافی تشخیصی", "2019-05-14", "بدون مداخله")],
        "course": ["ادم خفیف ساق بدون تنگی نفس حاد؛ علائم اورمیک گزارش نشد.", "کاهش حس مونوفیلامان دوطرفه؛ زخم فعال وجود ندارد.", "محدودیت نمک و پرهیز از NSAID دوباره آموزش داده شد.", "افت eGFR موجب بازبینی و تعدیل داروها شد؛ پتاسیم پایش شد."],
    },
    {
        "nid": "TEST0004", "name": "نمونه ۴ — دیابت و ASCVD", "gender": "male",
        "birth": "1962-11-30", "height_cm": 173,
        "address": "قم، پروندهٔ مصنوعی آزمون شمارهٔ ۴",
        "summary": "دیابت با سابقه انفارکتوس؛ درمان کاهش‌دهنده ریسک قلبی و کنترل شدید LDL.",
        "conditions": [{"code": "diabetes", "onset": "2012-03-04", "stage": "T2D", "notes": "همراه ASCVD."}, {"code": "hyperlipidemia", "onset": "2012-03-04", "stage": "secondary prevention", "notes": "هدف LDL کمتر از ۷۰."}, {"code": "hypertension", "onset": "2014-09-01", "stage": "controlled", "notes": "کنترل‌شده."}],
        "flags": {"ascvd": "1", "cvd_high_risk": "1", "smoking": "former", "hypo_risk": "low", "monofilament": "normal", "eye_exam_date": "2025-12-02", "foot_exam_date": "2026-03-16"},
        "vitals": {"fbs": (178, 124), "bp_systolic": (146, 126), "bp_diastolic": (90, 78), "weight": (92, 83), "pulse": (80, 68)},
        "labs": {"hba1c": (8.3, 6.9), "egfr": (82, 74), "uacr": (28, 24), "ldl": (156, 54), "hdl": (40, 46), "triglyceride": (214, 128), "creatinine": (1.0, 1.1), "potassium": (4.2, 4.4), "alt": (33, 27), "ast": (30, 24)},
        "meds": [_med("متفورمین", "metformin", "۱۰۰۰ میلی‌گرم", "2021-01-20", schedule="دو بار در روز"), _med("سماگلوتاید", "glp1_ra", "۰٫۵ میلی‌گرم", "2021-06-01", schedule="هفتگی", changes=[("2021-09-01", "۱ میلی‌گرم هفتگی", "ریسک قلبی و کنترل قند")]), _med("امپاگلیفلوزین", "sglt2i", "۱۰ میلی‌گرم", "2022-01-15"), _med("آتورواستاتین", "statin", "۴۰ میلی‌گرم", "2021-01-20", changes=[("2021-04-20", "۸۰ میلی‌گرم شبانه", "هدف ثانویه LDL")]), _med("آسپرین", "aspirin", "۸۰ میلی‌گرم", "2021-01-20")],
        "history": [("انفارکتوس میوکارد", "PCI و استنت؛ بدون آنژین جاری.", "2019-08-11"), ("دیابت نوع ۲", "درمان با تمرکز بر کاهش ریسک قلبی.", "2012-03-04")],
        "allergies": [], "surgeries": [("PCI و استنت کرونر", "2019-08-11", "LAD؛ پیگیری قلب")],
        "course": ["درد قفسه سینه یا تنگی نفس جدید گزارش نشد.", "معاینه قلب و ریه پایدار؛ ادم وجود ندارد.", "توانبخشی قلبی و فعالیت هوازی منظم ادامه دارد.", "LDL به هدف ثانویه رسید و درمان محافظ قلب ادامه یافت."],
    },
    {
        "nid": "TEST0005", "name": "نمونه ۵ — HFpEF و چاقی", "gender": "female",
        "birth": "1965-05-18", "height_cm": 165,
        "address": "تهران، پروندهٔ مصنوعی آزمون شمارهٔ ۵",
        "summary": "دیابت، HFpEF و چاقی؛ کاهش وزن و بهبود علائم با SGLT2i و تیرزپاتاید.",
        "conditions": [{"code": "diabetes", "onset": "2016-01-12", "stage": "T2D", "notes": "همراه چاقی."}, {"code": "hypertension", "onset": "2010-05-20", "stage": "controlled", "notes": "کنترل‌شده."}],
        "flags": {"hf": "1", "hf_type": "HFpEF", "hf_symptomatic": "1", "hypo_risk": "low", "smoking": "never", "monofilament": "normal", "eye_exam_date": "2026-03-03", "foot_exam_date": "2026-05-22"},
        "vitals": {"fbs": (204, 132), "bp_systolic": (144, 126), "bp_diastolic": (88, 76), "weight": (108, 88), "pulse": (88, 74)},
        "labs": {"hba1c": (9.1, 7.0), "egfr": (76, 68), "uacr": (24, 20), "ldl": (136, 72), "hdl": (37, 43), "triglyceride": (248, 146), "creatinine": (0.9, 1.0), "potassium": (4.0, 4.3), "alt": (58, 31), "ast": (45, 27)},
        "meds": [_med("داپاگلیفلوزین", "sglt2i", "۱۰ میلی‌گرم", "2021-02-01", notes="برای دیابت و HFpEF."), _med("تیرزپاتاید", "dual_gip_glp1", "۲٫۵ میلی‌گرم", "2022-04-01", schedule="هفتگی", changes=[("2022-06-01", "۵ میلی‌گرم هفتگی", "تحمل مناسب"), ("2023-01-01", "۱۰ میلی‌گرم هفتگی", "تشدید تدریجی")]), _med("لوزارتان", "arb", "۵۰ میلی‌گرم", "2021-01-20"), _med("فوروزماید", "loop_diuretic", "۲۰ میلی‌گرم", "2021-01-20", schedule="در صورت ادم", changes=[("2023-08-15", "۲۰ میلی‌گرم یک روز در میان", "کاهش ادم")])],
        "history": [("HFpEF", "اکوکاردیوگرافی با EF حفظ‌شده؛ علائم NYHA II.", "2020-11-09"), ("چاقی", "کاهش وزن بیش از ۱۰٪ طی پیگیری.", "2010-01-01")],
        "allergies": [("کوتریموکسازول", "راش پوستی", "خفیف")], "surgeries": [("هیسترکتومی", "2010-06-04", "خوش‌خیم")],
        "course": ["تنگی نفس فعالیتی از NYHA III به II بهبود یافته است.", "ادم ساق نسبت به شروع پیگیری کمتر و ریه‌ها پاک است.", "وزن روزانه، محدودیت نمک و علائم هشدار مرور شد.", "کاهش وزن پایدار و نیاز کمتر به دیورتیک ثبت شد."],
    },
    {
        "nid": "TEST0006", "name": "نمونه ۶ — عدم تحمل استاتین", "gender": "female",
        "birth": "1972-09-09", "height_cm": 160,
        "address": "تهران، پروندهٔ مصنوعی آزمون شمارهٔ ۶",
        "summary": "دیابت و دیس‌لیپیدمی؛ میالژی با آتورواستاتین و تحمل رزوواستاتین با دوز تعدیل‌شده.",
        "conditions": [{"code": "diabetes", "onset": "2019-10-01", "stage": "T2D", "notes": "کنترل نزدیک هدف."}, {"code": "hyperlipidemia", "onset": "2017-02-11", "stage": "primary prevention", "notes": "عدم تحمل یک استاتین ثبت شده است."}],
        "flags": {"smoking": "never", "hypo_risk": "low", "monofilament": "normal", "eye_exam_date": "2025-10-20", "foot_exam_date": "2026-04-11"},
        "vitals": {"fbs": (162, 126), "bp_systolic": (132, 122), "bp_diastolic": (84, 76), "weight": (80, 75), "pulse": (76, 70)},
        "labs": {"hba1c": (7.8, 6.9), "egfr": (92, 86), "uacr": (10, 12), "ldl": (184, 76), "hdl": (36, 44), "triglyceride": (286, 158), "creatinine": (0.8, 0.9), "potassium": (4.1, 4.2), "alt": (36, 28), "ast": (32, 25)},
        "meds": [_med("متفورمین", "metformin", "۱۰۰۰ میلی‌گرم", "2021-01-20", schedule="دو بار در روز"), _med("آتورواستاتین", "statin", "۴۰ میلی‌گرم", "2021-01-20", stop="2021-05-20", notes="به‌علت میالژی منتشر قطع شد."), _med("رزوواستاتین", "statin", "۵ میلی‌گرم", "2021-07-01", schedule="یک شب در میان", changes=[("2022-01-01", "۱۰ میلی‌گرم شبانه", "تحمل مناسب و LDL بالاتر از هدف"), ("2023-06-01", "۲۰ میلی‌گرم شبانه", "تشدید با پایش علائم")]), _med("ازتیمایب", "ezetimibe", "۱۰ میلی‌گرم", "2023-09-01")],
        "history": [("میالژی مرتبط با استاتین", "با قطع آتورواستاتین برطرف شد؛ rechallenge مستند است.", "2021-05-20")],
        "allergies": [], "surgeries": [],
        "course": ["ضعف یا درد عضلانی جدید گزارش نشد.", "قدرت عضلانی طبیعی و معاینه پا بدون مشکل است.", "مصرف چربی اشباع کاهش و فعالیت منظم‌تر شده است.", "تحمل رزوواستاتین و پاسخ LDL در هر مرحله بازبینی شد."],
    },
    {
        "nid": "TEST0007", "name": "نمونه ۷ — سالمند فراژیل", "gender": "male",
        "birth": "1944-02-14", "height_cm": 168,
        "address": "تهران، پروندهٔ مصنوعی آزمون شمارهٔ ۷",
        "summary": "سالمند فراژیل با افت قند روی سولفونیل‌اوره؛ درمان کم‌خطرتر و هدف HbA1c منعطف.",
        "conditions": [{"code": "diabetes", "onset": "2004-03-10", "stage": "T2D", "notes": "هدف HbA1c فردی ۷٫۵ تا ۸٪."}, {"code": "hypertension", "onset": "2000-01-01", "stage": "controlled", "notes": "پرهیز از افت فشار وضعیتی."}],
        "flags": {"frailty": "complex", "hypo_risk": "high", "smoking": "former", "monofilament": "impaired", "eye_exam_date": "2025-08-01", "foot_exam_date": "2026-06-10"},
        "vitals": {"fbs": (142, 148), "bp_systolic": (146, 136), "bp_diastolic": (82, 74), "weight": (72, 68), "pulse": (72, 70)},
        "labs": {"hba1c": (7.2, 7.8), "egfr": (62, 51), "uacr": (34, 42), "ldl": (118, 82), "hdl": (42, 44), "triglyceride": (168, 152), "creatinine": (1.1, 1.3), "potassium": (4.3, 4.5), "alt": (24, 22), "ast": (23, 21)},
        "meds": [_med("گلیکلازید", "su", "۶۰ میلی‌گرم", "2021-01-20", changes=[("2021-04-15", "۳۰ میلی‌گرم روزانه", "افت قند شبانه")], stop="2021-07-01", notes="پس از افت قند سطح ۲ قطع شد."), _med("لیناگلیپتین", "dpp4i", "۵ میلی‌گرم", "2021-07-02"), _med("آملودیپین", "ccb", "۵ میلی‌گرم", "2021-01-20")],
        "history": [("افت قند سطح ۲", "قند ۵۲ mg/dL بدون نیاز به کمک؛ موجب deintensification شد.", "2021-04-14"), ("سقوط بدون شکستگی", "ارزیابی تعادل و داروها انجام شد.", "2022-12-01")],
        "allergies": [], "surgeries": [("کاتاراکت", "2018-03-18", "چشم راست")],
        "course": ["پس از قطع سولفونیل‌اوره افت قند تکرار نشد؛ اشتها متغیر است.", "افت فشار وضعیتی خفیف؛ زخم پا وجود ندارد.", "پیشگیری از سقوط و همراهی خانواده در مصرف دارو مرور شد.", "هدف قند منعطف و پرهیز از تشدید غیرضروری مستند شد."],
    },
    {
        "nid": "TEST0008", "name": "نمونه ۸ — انسولین و هشدار فشار", "gender": "male",
        "birth": "1960-12-01", "height_cm": 174,
        "address": "ری، پروندهٔ مصنوعی آزمون شمارهٔ ۸",
        "summary": "دیابت تحت انسولین با سابقه افت قند؛ آخرین فشار ۱۸۴/۱۱۲ برای آزمون red-flag.",
        "conditions": [{"code": "diabetes", "onset": "2008-04-01", "stage": "insulin-treated T2D", "notes": "نیازمند انسولین بازال."}, {"code": "hypertension", "onset": "2016-09-20", "stage": "uncontrolled", "notes": "آخرین اندازه‌گیری در محدوده هشدار فوری."}],
        "flags": {"hypo_risk": "high", "smoking": "former", "monofilament": "impaired", "eye_exam_date": "2025-09-14", "foot_exam_date": "2026-06-28"},
        "vitals": {"fbs": (224, 152), "bp_systolic": (152, 184), "bp_diastolic": (92, 112), "weight": (88, 86), "pulse": (82, 90)},
        "labs": {"hba1c": (9.4, 7.7), "egfr": (78, 66), "uacr": (42, 68), "ldl": (144, 78), "hdl": (39, 41), "triglyceride": (238, 174), "creatinine": (1.0, 1.2), "potassium": (4.2, 4.4), "alt": (34, 28), "ast": (29, 25)},
        "meds": [_med("متفورمین", "metformin", "۱۰۰۰ میلی‌گرم", "2021-01-20", schedule="دو بار در روز"), _med("گلارژین", "insulin_basal", "۱۰ واحد", "2021-02-01", schedule="شب‌ها", changes=[("2021-05-01", "۱۶ واحد شب‌ها", "تیتراسیون بر اساس FBS"), ("2022-01-01", "۲۲ واحد شب‌ها", "قند ناشتا بالاتر از هدف"), ("2023-02-10", "۱۸ واحد شب‌ها", "کاهش پس از افت قند")]), _med("گلی‌بنکلامید", "su", "۵ میلی‌گرم", "2021-01-20", stop="2021-03-15", notes="با شروع تیتراسیون انسولین و ریسک افت قند قطع شد."), _med("لوزارتان", "arb", "۵۰ میلی‌گرم", "2021-01-20", changes=[("2026-04-20", "۱۰۰ میلی‌گرم روزانه", "کنترل فشار")])],
        "history": [("افت قند سطح ۳", "در ۱۴۰۱ نیازمند کمک خانواده؛ آموزش گلوکاگون انجام شد.", "2023-02-09"), ("فشارخون کنترل‌نشده", "نیازمند ارزیابی فوری در آخرین مراجعهٔ نمونه.", "2026-07-21")],
        "allergies": [], "surgeries": [("ترمیم فتق اینگوینال", "2015-07-08", "بدون عارضه")],
        "course": ["الگوی افت قند شبانه پس از تعدیل انسولین کمتر شد.", "آخرین فشار بسیار بالا ثبت و تکرار اندازه‌گیری درخواست شد.", "قانون ۱۵ و کاربرد گلوکاگون با خانواده مرور شد.", "در آخرین مراجعه، red-flag فشار برای ارزیابی فوری مستند شد."],
    },
    {
        "nid": "TEST0009", "name": "نمونه ۹ — پیش‌دیابت", "gender": "female",
        "birth": "1980-06-25", "height_cm": 166,
        "address": "تهران، پروندهٔ مصنوعی آزمون شمارهٔ ۹",
        "summary": "پیش‌دیابت و اضافه‌وزن بدون دارو؛ بهبود پایدار با مداخله سبک زندگی.",
        "conditions": [],
        "flags": {"smoking": "never", "hypo_risk": "low", "monofilament": "normal", "eye_exam_date": "2025-06-10", "foot_exam_date": "2026-02-12"},
        "vitals": {"fbs": (118, 103), "bp_systolic": (128, 118), "bp_diastolic": (82, 74), "weight": (79, 70), "pulse": (78, 70)},
        "labs": {"hba1c": (6.2, 5.8), "egfr": (102, 96), "uacr": (8, 7), "ldl": (132, 104), "hdl": (43, 50), "triglyceride": (184, 126), "creatinine": (0.7, 0.8), "potassium": (4.0, 4.1), "alt": (35, 22), "ast": (29, 20)},
        "meds": [],
        "history": [("پیش‌دیابت", "پایش سالانه؛ معیار تشخیصی دیابت احراز نشده است.", "2021-01-15"), ("اضافه‌وزن", "کاهش بیش از ۷٪ وزن با مداخله سبک زندگی.", "2021-01-15")],
        "allergies": [("ایبوپروفن", "دیس‌پپسی شدید", "خفیف")], "surgeries": [],
        "course": ["علائم هایپرگلیسمی وجود ندارد.", "معاینه عمومی طبیعی و فشار در محدوده هدف است.", "فعالیت هوازی و مقاومتی منظم و کاهش کالری ادامه دارد.", "HbA1c در محدوده پیش‌دیابت رو به بهبود باقی مانده است."],
    },
    {
        "nid": "TEST0010", "name": "نمونه ۱۰ — متفورمین با eGFR پایین", "gender": "male",
        "birth": "1970-04-04", "height_cm": 172,
        "address": "شهریار، پروندهٔ مصنوعی آزمون شمارهٔ ۱۰",
        "summary": "دیابت، MASLD و CKD؛ eGFR نهایی ۲۴ با متفورمین فعال برای آزمون هشدار دارویی.",
        "conditions": [{"code": "diabetes", "onset": "2013-05-02", "stage": "T2D", "notes": "کنترل متوسط."}, {"code": "ckd", "onset": "2024-01-18", "stage": "G4/A2", "notes": "کاهش سریع eGFR؛ مغایرت دارویی عمدی در سناریوی ایمنی."}],
        "flags": {"smoking": "current", "masld": "1", "ckd_stage_g": "G4", "ckd_stage_a": "A2", "hypo_risk": "atrisk", "monofilament": "normal", "eye_exam_date": "2025-07-12", "foot_exam_date": "2026-05-30"},
        "vitals": {"fbs": (196, 142), "bp_systolic": (144, 138), "bp_diastolic": (88, 84), "weight": (98, 90), "pulse": (82, 76)},
        "labs": {"hba1c": (8.9, 7.4), "egfr": (74, 24), "uacr": (22, 168), "ldl": (152, 88), "hdl": (34, 39), "triglyceride": (310, 186), "creatinine": (1.0, 2.8), "potassium": (4.1, 4.8), "alt": (72, 44), "ast": (55, 38)},
        "meds": [_med("متفورمین", "metformin", "۱۰۰۰ میلی‌گرم", "2021-01-20", schedule="دو بار در روز", notes="فعال باقی گذاشته شده تا موتور ناسازگاری eGFR را شناسایی کند."), _med("سماگلوتاید", "glp1_ra", "۰٫۲۵ میلی‌گرم", "2022-03-01", schedule="هفتگی", changes=[("2022-05-01", "۰٫۵ میلی‌گرم هفتگی", "تحمل مناسب"), ("2022-10-01", "۱ میلی‌گرم هفتگی", "تشدید")]), _med("رزوواستاتین", "statin", "۲۰ میلی‌گرم", "2021-06-01")],
        "history": [("MASLD", "سونوگرافی و آنزیم‌های کبدی؛ کاهش وزن توصیه و پیگیری شده است.", "2021-08-01"), ("CKD با افت سریع", "نیازمند بازبینی فوری ایمنی متفورمین.", "2024-01-18"), ("مصرف دخانیات", "مداخله ترک در هر ویزیت ثبت شده است.", "1995-01-01")],
        "allergies": [], "surgeries": [],
        "course": ["تهوع شدید یا علائم اسیدوز گزارش نشد؛ خستگی اخیر ذکر شد.", "زردی وجود ندارد؛ معاینه پا طبیعی است.", "مشاوره ترک سیگار و کاهش وزن در هر دوره تکرار شد.", "eGFR به ۲۴ رسیده و مغایرت متفورمین باید توسط موتور هشدار داده شود."],
    },
]


def _build_patient(base: dict[str, Any]) -> dict[str, Any]:
    patient = {key: value for key, value in base.items() if key not in {"vitals", "labs", "course"}}
    patient["phone"] = f"0912{int(base['nid'][-4:]):07d}"
    observation_count = len(OBSERVATION_DATES)
    weight_values = trend(*base["vitals"]["weight"], observation_count, wave=0.35)
    vitals = []
    for key, (unit, wave) in _VITAL_META.items():
        values = weight_values if key == "weight" else trend(*base["vitals"][key], observation_count, wave=wave)
        for measured_on, value in zip(OBSERVATION_DATES, values):
            vitals.append({"type": key, "value": value, "unit": unit,
                           "measured_at": measured_on + " 09:30:00",
                           "source": "clinic" if key != "fbs" else "self",
                           "notes": "دادهٔ مصنوعی طولی استاندارد"})
    height_m = float(base["height_cm"]) / 100
    for measured_on, weight in zip(OBSERVATION_DATES, weight_values):
        vitals.append({"type": "bmi", "value": round(weight / (height_m ** 2), 1),
                       "unit": "kg/m²", "measured_at": measured_on + " 09:30:00",
                       "source": "clinic", "notes": "محاسبه‌شده از قد و وزن"})

    labs = []
    for key, endpoints in base["labs"].items():
        name, unit, low, high = _LAB_META[key]
        for taken_on, value in zip(LAB_DATES, trend(*endpoints, len(LAB_DATES), wave=0.25)):
            labs.append({"test_name": name, "test_key": key, "value": value,
                         "unit": unit, "ref_low": low, "ref_high": high,
                         "taken_at": taken_on + " 08:15:00",
                         "notes": "پنل دوره‌ای مصنوعی و تأییدشده"})

    notes = []
    kinds = ("symptom", "exam", "lifestyle", "general")
    for index, visit_on in enumerate(VISIT_DATES):
        notes.append({"kind": kinds[index % 4], "recorded_at": visit_on + " 10:20:00",
                      "body": base["course"][index % len(base["course"])]})

    appointments = []
    for index, visit_on in enumerate(VISIT_DATES):
        appointments.append({"scheduled_at": visit_on + " 10:00:00", "appt_type": "checkup",
                             "status": "no_show" if index == 7 else "done",
                             "notes": "ویزیت دوره‌ای پروندهٔ مصنوعی"})
    appointments.append({"scheduled_at": "2026-10-22 10:00:00", "appt_type": "checkup",
                         "status": "scheduled", "notes": "پیگیری سه‌ماهه بعدی"})

    followups = [
        {"due_date": "2021-04-15", "reason": "uncontrolled", "detail": "مرور پاسخ اولیه درمان", "status": "done", "resolved_at": "2021-04-15 11:00:00"},
        {"due_date": "2022-01-15", "reason": "visit_due", "detail": "چکاپ سالانه عوارض", "status": "done", "resolved_at": "2022-01-16 09:00:00"},
        {"due_date": "2024-07-15", "reason": "refill", "detail": "بازبینی و تمدید نسخه", "status": "done", "resolved_at": "2024-07-15 12:00:00"},
        {"due_date": "2026-10-22", "reason": "visit_due", "detail": "پیگیری بعدی بر اساس آخرین ویزیت", "status": "open", "resolved_at": None},
    ]

    prescriptions = []
    for medication in base["meds"]:
        events = [(medication["start"], medication["dose"], "شروع درمان")]
        events.extend((when, dose, note) for when, dose, note in medication["changes"])
        for issued_on, dose, reason in events:
            prescriptions.append({"kind": "diabetes-followup", "issued_at": issued_on + " 11:00:00",
                                  "mode": "free", "items": [{"name": medication["name"], "dose": dose,
                                  "schedule": medication["schedule"], "reason": reason}]})

    patient.update({"vitals": vitals, "labs": labs, "notes": notes,
                    "appointments": appointments, "followups": followups,
                    "prescriptions": prescriptions})
    return patient


DEMO_PATIENTS = tuple(_build_patient(item) for item in _BASE_PATIENTS)


def expected_totals() -> dict[str, int]:
    keys = ("vitals", "labs", "meds", "notes", "appointments", "followups",
            "prescriptions", "history", "allergies", "surgeries", "conditions")
    return {key: sum(len(patient.get(key, ())) for patient in DEMO_PATIENTS) for key in keys}

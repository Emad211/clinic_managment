"""
clinical/sms/compliance.py — SMS content compliance for Iranian SMS panels.

Faithful port of specialist_clinic/src/services/sms/compliance.py.

Iranian operators/panels reject promotional words like «رایگان» and «تخفیف» on
many lines.  We detect and auto-replace them with compliant alternatives.

The lawful framing for promotions is wallet-credit: «اعتبار هدیه» describes a
deposited credit, not a discount or free offer — this is the required framing
for the future offer engine (Phase 8 of the record redesign).

Note: «آزاد» is deliberately NOT banned — it collides with «نسخهٔ آزاد»
(free/non-insurance prescription) and would mangle legitimate clinical messages.
«هدیه» is kept allowed because «اعتبار هدیه» is the lawful framing.
"""

# Words commonly filtered by Iranian SMS panels (promotional)
BANNED_WORDS = [
    'رایگان', 'تخفیف', 'حراج', 'حراجی', 'جشنواره', 'قرعه', 'قرعه‌کشی', 'قرعه کشی',
    'جایزه', 'مسابقه', 'فروش ویژه', 'مجانی', 'بلیط', 'ارزان',
]

# Compliant rewrites that keep marketing intent without the banned trigger words.
SUGGESTIONS: dict[str, str] = {
    'رایگان': 'با اعتبار هدیه',
    'مجانی': 'با اعتبار هدیه',
    'تخفیف': 'اعتبار ویژه',
    'حراج': 'شرایط ویژه',
    'حراجی': 'شرایط ویژه',
    'جشنواره': 'برنامه ویژه',
    'قرعه‌کشی': 'برنامه ویژه اعضا',
    'قرعه کشی': 'برنامه ویژه اعضا',
    'قرعه': 'برنامه ویژه اعضا',
    'جایزه': 'اعتبار هدیه',
    'مسابقه': 'برنامه ویژه',
    'فروش ویژه': 'شرایط ویژه',
    'مجانی ': 'با اعتبار هدیه ',
    'بلیط': 'دعوت‌نامه',
    'ارزان': 'مقرون‌به‌صرفه',
}


def find_banned(text: str) -> list[str]:
    """Return the list of banned words present in text."""
    if not text:
        return []
    found = []
    for w in BANNED_WORDS:
        if w in text and w not in found:
            found.append(w)
    return found


def sanitize(text: str) -> str:
    """
    Auto-replace banned words with compliant alternatives.

    Longer phrases are replaced first to avoid partial-overlap mangling.
    """
    if not text:
        return text
    out = text
    for w in sorted(SUGGESTIONS.keys(), key=len, reverse=True):
        if w in out:
            out = out.replace(w, SUGGESTIONS[w])
    return out


def is_compliant(text: str) -> bool:
    """Return True if text contains no banned words."""
    return len(find_banned(text)) == 0


# ===========================================================================
# Clinical-content (PHI) detection — step 76 / R3
# ===========================================================================
# A patient SMS must never carry THIS patient's clinical SPECIFICS: lab/vital
# VALUES, drug doses/changes, or BP readings. Detection is NUMBER-ANCHORED to
# avoid false-positives on legitimate PHI-free reminders ("وقتِ آزمایشِ دوره‌ای
# شما رسیده", "یادآوریِ ویزیتِ کنترلِ فشار", "نوبتِ شما فردا ساعت ۱۰").
#
# Designed with clinical-pharmacist-advisor + security-privacy-advisor. The
# enforcement is BLOCK, never strip — there is no safe rewrite for PHI (unlike
# promo words). Engagement templates only interpolate {name} (no live clinical
# value tokens), so this is a SAFETY-NET against a hand-typed bad template, not a
# full PHI detector. Diagnosis terms are deliberately NOT matched (false-positive
# risk: "کلینیکِ دیابت"/"ویزیتِ فشارخون" are legitimate).
import re

# Persian/Arabic-Indic → Latin digits. The \d patterns below need Latin digits
# (a body like «۱۶۰/۹۵» is stored with Persian digits).
_DIGIT_TRANS = {}
for _i, _p in enumerate("۰۱۲۳۴۵۶۷۸۹"):
    _DIGIT_TRANS[ord(_p)] = str(_i)
for _i, _a in enumerate("٠١٢٣٤٥٦٧٨٩"):
    _DIGIT_TRANS[ord(_a)] = str(_i)


def _to_latin_digits(text: str) -> str:
    return text.translate(_DIGIT_TRANS)


# Benign numeric contexts stripped BEFORE value detection so an appointment
# date/time or phone number can never anchor a false-positive.
_RE_JALALI_DATE = re.compile(r"\d{3,4}\s*/\s*\d{1,2}\s*/\s*\d{1,2}")
_RE_CLOCK = re.compile(r"\d{1,2}\s*[:：]\s*\d{2}")
_RE_HOUR = re.compile(r"ساعتِ?\s*\d{1,2}")
_RE_PHONE = re.compile(r"\+?\d[\d\s-]{6,}\d")


def _strip_benign_numbers(t: str) -> str:
    for _rx in (_RE_JALALI_DATE, _RE_CLOCK, _RE_HOUR, _RE_PHONE):
        t = _rx.sub(" ", t)
    return t


# Dose: a number immediately followed by a dose unit (e.g. "۱۰۰۰mg", "۵ واحد").
_DOSE_UNITS = r"(?:mg|mcg|گرم|میلی[\s‌]?گرم|میلیگرم|میکروگرم|واحد|cc|سی[\s‌]?سی|قرص|کپسول|cap)"
_RE_DOSE = re.compile(r"\d+(?:[.,٫]\d+)?\s*" + _DOSE_UNITS + r"\b", re.IGNORECASE)

# Dose-change: a titration verb near a dose/medication noun ("دوز را زیاد کنید").
_RE_DOSE_CHANGE = re.compile(
    r"(?:افزایش|کاهش|زیاد|کم|دو\s*برابر|نصف)\s*\S{0,12}?\s*(?:دوز|قرص|واحد|دارو)"
)

# BP reading like 160/95 — two 2-3 digit groups NOT part of a longer digit/slash
# run (Jalali dates are stripped first, but this also guards bare cases).
_RE_BP = re.compile(r"(?<![\d/])\d{2,3}\s*/\s*\d{2,3}(?![\d/])")

# Lab/vital VALUE: a specific lab/vital ANCHOR within ~20 chars of a number.
# فشار/bp are intentionally OMITTED (too common in reminders) — BP readings are
# caught by _RE_BP instead. The bare anchor (no number) stays legitimate.
_LAB_ANCHORS = [
    "hba1c", "a1c", "fbs", "ldl", "hdl", "tsh", "egfr", "gfr",
    "قند", "کلسترول", "تری‌گلیسرید", "تریگلیسرید", "کراتینین", "هموگلوبین",
]
_RE_LAB_VALUE = re.compile(
    r"(?:" + "|".join(re.escape(a) for a in _LAB_ANCHORS) + r").{0,20}?\d",
    re.IGNORECASE | re.DOTALL,
)

# Chronic-drug names — only count as PHI when a number also appears (a bare
# "متفورمین را ادامه دهید" is legitimate). Small + editable; expand on demand.
_DRUG_NAMES = [
    "متفورمین", "metformin", "انسولین", "insulin", "گلیکلازید", "گلی‌بنکلامید",
    "گلیبنکلامید", "املودیپین", "amlodipine", "لوزارتان", "losartan",
    "آتورواستاتین", "atorvastatin", "روزوواستاتین", "rosuvastatin",
    "لیزینوپریل", "lisinopril", "انالاپریل", "enalapril",
    "هیدروکلروتیازید", "لووتیروکسین", "levothyroxine", "وارفارین", "warfarin",
]
_RE_DRUG = re.compile("|".join(re.escape(d) for d in _DRUG_NAMES), re.IGNORECASE)
_RE_ANY_NUMBER = re.compile(r"\d")


def find_phi(text: str) -> list[str]:
    """
    Return labels of clinical-specific (PHI) signals detected in `text`.

    Run on the FINAL outgoing body (after sanitize + {name} personalization).
    Empty list ⇒ no clinical specifics detected. Number-anchored heuristic; a
    safety-net, not a guarantee. Enforcement is BLOCK (see engagement_service).
    """
    if not text:
        return []
    t = _strip_benign_numbers(_to_latin_digits(text))
    found = []
    if _RE_DOSE.search(t):
        found.append("dose")
    if _RE_DOSE_CHANGE.search(t):
        found.append("dose_change")
    if _RE_BP.search(t):
        found.append("bp_reading")
    if _RE_LAB_VALUE.search(t):
        found.append("lab_value")
    if _RE_DRUG.search(t) and _RE_ANY_NUMBER.search(t):
        found.append("drug_with_number")
    return found


def is_phi_free(text: str) -> bool:
    """True if no clinical-specific (PHI) signal is detected in `text`."""
    return len(find_phi(text)) == 0

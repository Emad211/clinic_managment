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

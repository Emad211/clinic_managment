"""SMS content compliance for Iranian SMS panels.

Iranian operators/panels reject promotional words like «رایگان» and «تخفیف» on
many lines. We can't use them directly, so we:
  1) detect banned words and warn the operator,
  2) suggest compliant alternatives, and
  3) steer promotions toward the wallet-credit framing («اعتبار هدیه»), which is
     accepted because it describes a deposited credit, not a discount/free offer.
"""
import re

# Words commonly filtered by Iranian SMS panels (promotional)
BANNED_WORDS = [
    'رایگان', 'تخفیف', 'حراج', 'حراجی', 'جشنواره', 'قرعه', 'قرعه‌کشی', 'قرعه کشی',
    'جایزه', 'مسابقه', 'فروش ویژه', 'مجانی', 'بلیط', 'ارزان',
]
# Note: «آزاد» is deliberately NOT banned — it collides with the app's own «نسخهٔ آزاد»
# (free/non-insurance prescription) and would mangle legitimate messages. «هدیه» is also
# kept allowed because «اعتبار هدیه» is the lawful wallet-credit framing (see SUGGESTIONS).

# Compliant rewrites that keep the marketing intent without the banned trigger words
SUGGESTIONS = {
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
    """Return the list of banned words present in the text."""
    if not text:
        return []
    found = []
    for w in BANNED_WORDS:
        if w in text and w not in found:
            found.append(w)
    return found


def sanitize(text: str) -> str:
    """Auto-replace banned words with compliant alternatives."""
    if not text:
        return text
    out = text
    # Replace longer phrases first to avoid partial overlaps.
    for w in sorted(SUGGESTIONS.keys(), key=len, reverse=True):
        if w in out:
            out = out.replace(w, SUGGESTIONS[w])
    return out


def is_compliant(text: str) -> bool:
    return len(find_banned(text)) == 0

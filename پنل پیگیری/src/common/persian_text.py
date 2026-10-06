"""Persian text normalization (docs/03 §9). Pure functions, no dependencies."""
from __future__ import annotations

import re

_CHAR_MAP = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه",
    "أ": "ا", "إ": "ا", "ٱ": "ا",
    "‌": " ",   # ZWNJ (half-space) → space, then collapsed
    "‍": None,  # ZWJ
    "ـ": None,  # tatweel (kashida)
    **{chr(0x06F0 + d): str(d) for d in range(10)},   # Persian digits
    **{chr(0x0660 + d): str(d) for d in range(10)},   # Arabic-Indic digits
})
_SPACES = re.compile(r"\s+")

_TO_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def normalize(text: str | None) -> str:
    """Unify Arabic/Persian letter forms and digits, drop kashida, collapse spaces."""
    if not text:
        return ""
    return _SPACES.sub(" ", text.translate(_CHAR_MAP)).strip()


def compact(text: str | None) -> str:
    """normalize() without any spaces — tolerant of typos like «کشیدنبخیه»."""
    return normalize(text).replace(" ", "")


def digits_only(text: str | None) -> str:
    """Latin digits of ``text`` (Persian/Arabic digits converted), everything else dropped."""
    return "".join(ch for ch in normalize(text) if ch.isascii() and ch.isdigit())


def fa_digits(value: object) -> str:
    return str(value).translate(_TO_FA_DIGITS)

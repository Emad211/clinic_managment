"""Identity rules (docs/05 §9, ADR-0004). Pure functions."""
from __future__ import annotations

from ..common.persian_text import digits_only, normalize

PLACEHOLDER_FIRST_NAMES = frozenset(normalize(n) for n in (
    "خ", "ا", "آ", "آقا", "اقا", "آقای", "خانم", "خ.", "ا.", "بیمار", "ناشناس",
))


def clean_national_id(value: str | None) -> str:
    return digits_only(value)


def clean_mobile(value: str | None) -> str:
    return digits_only(value)


def is_valid_national_id(value: str | None) -> bool:
    """Iranian national-ID checksum; same algorithm as webapp's validators.py."""
    nid = clean_national_id(value)
    if len(nid) != 10 or len(set(nid)) == 1:
        return False
    check = int(nid[9])
    remainder = sum(int(nid[i]) * (10 - i) for i in range(9)) % 11
    return check == remainder if remainder < 2 else check == 11 - remainder


def is_valid_mobile(value: str | None) -> bool:
    m = clean_mobile(value)
    return len(m) == 11 and m.startswith("09")


def is_real_first_name(value: str | None) -> bool:
    n = normalize(value)
    return sum(ch.isalpha() for ch in n) >= 2 and n not in PLACEHOLDER_FIRST_NAMES


def is_real_last_name(value: str | None) -> bool:
    return sum(ch.isalpha() for ch in normalize(value)) >= 2


def identity_ok(first_name: str | None, last_name: str | None,
                national_id: str | None, mobile: str | None) -> bool:
    """All four must hold. ``is_foreign`` alone does not disqualify (05 §9 rule 4)."""
    return (is_real_first_name(first_name) and is_real_last_name(last_name)
            and is_valid_national_id(national_id) and is_valid_mobile(mobile))


def identity_problems(first_name: str | None, last_name: str | None,
                      national_id: str | None, mobile: str | None) -> list[str]:
    """Persian messages for each failing rule (docs/06 §5-1)."""
    out = []
    if not is_real_first_name(first_name):
        out.append("نام کوچک کامل وارد شود")
    if not is_real_last_name(last_name):
        out.append("نام خانوادگی کامل وارد شود")
    if not clean_national_id(national_id):
        out.append("کد ملی وارد نشده است")
    elif not is_valid_national_id(national_id):
        out.append("کد ملی نامعتبر است (رقم کنترل)")
    if not is_valid_mobile(mobile):
        out.append("موبایل باید ۱۱ رقم و با ۰۹ شروع شود")
    return out


def mask_national_id(value: str | None) -> str:
    nid = clean_national_id(value)
    return f"…{nid[-4:]}" if nid else ""

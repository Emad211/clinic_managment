"""Validation helpers ported from the production Flask accounting app."""
from __future__ import annotations


def validate_iranian_national_id(national_id: str) -> bool:
    """Validate a ten-digit Iranian national identifier."""
    if not national_id or len(national_id) != 10 or not national_id.isdigit():
        return False
    if len(set(national_id)) == 1:
        return False

    check = int(national_id[9])
    weighted = sum(int(national_id[i]) * (10 - i) for i in range(9))
    remainder = weighted % 11
    return check == (remainder if remainder < 2 else 11 - remainder)


def validate_iranian_phone(phone: str) -> bool:
    """Return ``True`` for an 11-digit Iranian mobile number starting with 09."""
    return bool(
        phone
        and len(phone) == 11
        and phone.isdigit()
        and phone.startswith("09")
    )

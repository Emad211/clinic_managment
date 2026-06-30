"""
test_compliance.py — clinical-content (PHI) detection for SMS (step 76 / R3).

find_phi/is_phi_free must CATCH this-patient clinical specifics (lab/vital values,
drug doses/changes, BP readings) while NOT false-positiving on legitimate PHI-free
reminders (appointment dates/times, phone numbers, bare clinical words). Pure unit
tests — no DB. These MUST-PASS / MUST-CATCH cases are the real validation of the
heuristic (designed with clinical-pharmacist-advisor).
"""
import pytest

from clinical.sms.compliance import find_phi, is_phi_free, sanitize


# Legitimate PHI-free reminders — MUST PASS (is_phi_free == True).
_MUST_PASS = [
    "سلام تست",
    "وقتِ آزمایشِ دوره‌ای شما رسیده، لطفاً برای نوبت تماس بگیرید",
    "یادآوریِ ویزیتِ کنترلِ فشار",
    "نوبتِ شما فردا ساعت ۱۰ است",
    "یادآوریِ نوبتِ شما فردا ساعت ۱۴:۳۰ — کلینیکِ دیابت",
    "برای تمدیدِ نسخه با شمارهٔ ۰۲۱۱۲۳۴۵۶۷۸ تماس بگیرید",
    "نوبتِ شما در تاریخِ ۱۴۰۵/۰۴/۱۰ ثبت شد",
    "داروهای خود را همراه بیاورید و نسخه را تمدید کنید",  # bare drug word, no number
]

# This-patient clinical specifics — MUST CATCH (is_phi_free == False).
_MUST_CATCH = [
    "HbA1c شما ۹ است",
    "متفورمین را به ۱۰۰۰mg افزایش دهید",
    "فشارِ شما ۱۶۰/۹۵ است",
    "قندِ خونِ شما ۲۸۰ است",
    "دوزِ انسولین را به ۲۰ واحد برسانید",
    "LDL شما ۱۹۰ است",
]


@pytest.mark.parametrize("text", _MUST_PASS)
def test_phi_free_passes_legitimate_reminders(text):
    assert is_phi_free(text), f"FALSE POSITIVE: {text!r} flagged {find_phi(text)}"


@pytest.mark.parametrize("text", _MUST_CATCH)
def test_phi_detected_in_clinical_specifics(text):
    assert not is_phi_free(text), f"MISSED PHI: {text!r}"
    assert find_phi(text), f"find_phi returned empty for {text!r}"


def test_find_phi_empty_text():
    assert find_phi("") == []
    assert is_phi_free("") is True


def test_persian_and_latin_digits_both_detected():
    # Persian digits must be normalized so \d patterns fire (160/95 in Persian).
    assert not is_phi_free("فشارِ شما ۱۶۰/۹۵")
    # Latin digits work too.
    assert not is_phi_free("hba1c شما 9 است")


def test_phi_check_independent_of_promo_sanitize():
    # sanitize() (promo rewrite) and find_phi() (PHI block) are orthogonal:
    # promo rewriting must not hide clinical content from the PHI check.
    body = "تخفیفِ ویژه: قندِ شما ۲۸۰"
    s = sanitize(body)
    assert "تخفیف" not in s, "sanitize should rewrite the promo word"
    assert not is_phi_free(s), "PHI must still be detected after promo-rewrite"

"""Pure domain rules: text normalization, identity (05 §9), categories (03 §9), sync indicator."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.common.jalali import gregorian_from_jalali, jalali_date
from src.common.persian_text import compact, digits_only, normalize
from src.domain import categories as cat
from src.domain.identity import (identity_ok, identity_problems, is_real_first_name, is_valid_mobile,
                                 is_valid_national_id, mask_national_id)
from src.domain.sync_status import indicator


# ------------------------------------------------------------------ text
def test_normalize():
    assert normalize("كشيدن‌بخيه  ") == "کشیدن بخیه"
    assert normalize("پانســـمان") == "پانسمان"            # kashida removed
    assert normalize("۰۹۱۲ ٣٤٥") == "0912 345"
    assert normalize("أإٱة ۀ") == "اااه ه"
    assert compact("کشیدن  بخیه") == "کشیدنبخیه"
    assert digits_only("۰۹۱۲-۱۲۳ ۴۵۶۷") == "09121234567"
    assert normalize(None) == ""


def test_jalali_round_trip():
    assert jalali_date("2026-10-06") == "۱۴۰۵/۰۷/۱۴"
    assert gregorian_from_jalali("۱۴۰۵/۰۷/۱۴") == "2026-10-06"
    assert gregorian_from_jalali("1405/7/14") == "2026-10-06"
    for bad in ("۱۴۰۵/۱۳/۰۱", "abc", "1405/07"):
        with pytest.raises(ValueError):
            gregorian_from_jalali(bad)


# ------------------------------------------------------------------ identity
@pytest.mark.parametrize("nid,ok", [
    ("0499370899", True), ("2170415981", True), ("2110530979", True), ("۰۴۹۹۳۷۰۸۹۹", True),
    ("1234567890", False), ("0000000000", False), ("1111111111", False), ("049937089", False),
    ("04993708990", False), ("", False), (None, False),
])
def test_national_id(nid, ok):
    assert is_valid_national_id(nid) is ok


@pytest.mark.parametrize("mobile,ok", [
    ("09121234567", True), ("۰۹۱۲۱۲۳۴۵۶۷", True), ("0912 123 4567", True),
    ("9121234567", False), ("08121234567", False), ("0912123456", False), (None, False),
])
def test_mobile(mobile, ok):
    assert is_valid_mobile(mobile) is ok


@pytest.mark.parametrize("name,ok", [
    ("مریم", True), ("علی", True), ("خ", False), ("ا", False), ("آقای", False), ("خانم", False),
    ("خ.", False), ("بیمار", False), ("ناشناس", False), ("ن", False), ("", False), ("آقا", False),
])
def test_first_name(name, ok):
    assert is_real_first_name(name) is ok


def test_identity_ok_and_messages():
    assert identity_ok("مریم", "احمدی", "0499370899", "09121234567")
    assert not identity_ok("خ", "حسینی", "0499370899", "09121234567")
    problems = identity_problems("خ", "ح", "1234567890", "0912")
    assert problems == ["نام کوچک کامل وارد شود", "نام خانوادگی کامل وارد شود",
                        "کد ملی نامعتبر است (رقم کنترل)", "موبایل باید ۱۱ رقم و با ۰۹ شروع شود"]
    assert identity_problems("مریم", "احمدی", "", "09121234567") == ["کد ملی وارد نشده است"]
    assert mask_national_id("0499370899") == "…0899" and mask_national_id(None) == ""


# ------------------------------------------------------------------ categories (03 §9)
@pytest.mark.parametrize("name", [
    "کشیدن بخیه", "کشسدن بخیه", "کشیدنبخیه", "کشیئن بخیه", "کشیدن بخینی بینی", "کشيدن بخيه دست",
    "بخیه کشی", "کشیدن  بخیه",
])
def test_suture_removal_typos(name):
    assert cat.procedure_keyword_categories(name) == {cat.SUTURE_REMOVAL}


@pytest.mark.parametrize("name,expected", [
    ("زدن بخیه", set()), ("بخیه زدن سر", set()), ("بخیه", set()),
    ("پانسمان", {cat.DRESSING}), ("پانسمان سوختگی", {cat.DRESSING}),
    ("شستشوی گوش", {cat.EAR_IRRIGATION}), ("شتشوی گوش", {cat.EAR_IRRIGATION}),
    ("ستشوی گوش راست", {cat.EAR_IRRIGATION}), ("شستوی گوش", {cat.EAR_IRRIGATION}),
    ("سوراخ کردن گوش", set()), ("شستشوی زخم", set()),
    ("کشیدن بخیه و پانسمان", {cat.SUTURE_REMOVAL, cat.DRESSING}),
])
def test_procedure_keywords(name, expected):
    assert cat.procedure_keyword_categories(name) == expected


def test_ambiguous_and_manual_map():
    assert cat.is_ambiguous_procedure("بخیه") and cat.is_ambiguous_procedure("بخیه زدن")
    assert not cat.is_ambiguous_procedure("کشیدن بخیه") and not cat.is_ambiguous_procedure("پانسمان")
    assert cat.procedure_categories("بخیه", {"بخیه": "suture_removal"}) == {cat.SUTURE_REMOVAL}
    assert cat.procedure_categories("پانسمان", {"پانسمان": None}) == set()      # «unrelated»


def test_injection_categories():
    ids = cat.resolve_service_ids([(22, "تست قند"), (31, "کنترل فشار"), (40, "نبولایزر بزرگسال"), (5, "سرم")])
    assert (ids.bs_test, ids.bp_check, ids.nebulizer) == ({22}, {31}, {40})
    assert cat.injection_categories(22, "هرچه", ids) == {cat.BS_TEST}
    assert cat.injection_categories(31, "", ids) == {cat.BP_CHECK}
    assert cat.injection_categories(None, "تست  قند", ids) == {cat.BS_TEST}       # fallback by name
    assert cat.injection_categories(40, "نبولایزر", ids) == {cat.NEBULIZER}
    assert cat.injection_categories(5, "سرم", ids) == set()


# ------------------------------------------------------------------ sync indicator
def test_indicator():
    now = datetime(2026, 10, 6, 10, 0, 0)
    assert indicator(now - timedelta(seconds=3), now, True) == ("green", 3)
    assert indicator(now - timedelta(seconds=15), now, True) == ("yellow", 15)
    assert indicator(now - timedelta(seconds=60), now, True) == ("red", 60)
    assert indicator(now - timedelta(seconds=3), now, False) == ("red", 3)
    assert indicator(None, now, True) == ("red", None)

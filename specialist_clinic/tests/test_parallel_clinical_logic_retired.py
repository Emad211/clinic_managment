"""Regression guards for clinical interpretation outside governed v2 output."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(relative: str) -> str:
    return (ROOT / "src" / relative).read_text(encoding="utf-8")


def test_patient_page_has_no_insulin_or_dose_recommendation_calculator():
    page = source("templates/patients/detail.html")
    route = source("api/patients.py")
    for token in (
        "insulinModal", "insBtn", "insTarget", "شروع انسولین پایه",
        "گام بعدی پیشنهادی", "بولوس پراندیال", "پیشنهاد دوزِ",
    ):
        assert token not in page
    assert "dosage_guidance" not in route
    assert "TARGETS" not in route


def test_patient_trends_show_values_and_deltas_without_targets_or_risk_labels():
    page = source("templates/patients/detail.html")
    assert "ریسک بالینی" not in page
    assert "کنترل کلی" not in page
    assert "ریسک: {{ d.risk_label }}" not in page
    assert "series[sel[0]].target" not in page
    assert "FPG در محدودهٔ هدف" not in page
    assert "تغییر عددی" in page

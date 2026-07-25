"""The public patient card is a descriptive channel, never a CDS surface."""
from __future__ import annotations

from pathlib import Path


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
SERVICE = SPECIALIST_ROOT / "src" / "services" / "card_projection_service.py"
TEMPLATE = SPECIALIST_ROOT / "src" / "templates" / "card" / "public_card.html"


def test_public_card_does_not_evaluate_or_emit_actionable_clinical_status():
    service = SERVICE.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "evaluate_reading" not in service
    assert "overall_level" not in service
    assert "status_text" not in service
    assert '"projection_policy": "DESCRIPTIVE_ONLY"' in service

    for phrase in (
        "لطفاً همین امروز با کلینیک تماس بگیرید",
        "نیاز به پیگیری",
        "در محدودهٔ هدف",
    ):
        assert phrase not in template


def test_public_card_keeps_plain_values_and_explicit_non_clinical_disclaimer():
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "{{ v.value|fa_num }}" in template
    assert "{{ v.measured_at|jalali_date }}" in template
    assert "هدف درمانی یا اقدام لازم قضاوت نمی‌کند" in template
    assert "جایگزین ارزیابی پزشک، تشخیص یا توصیهٔ درمانی نیست" in template

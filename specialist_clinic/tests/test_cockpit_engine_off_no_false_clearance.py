"""Absence of clinical analysis must never render as a clinical all-clear.

The analytical engine is separable and default-OFF. When it is OFF or its current
run is UNAVAILABLE, ``PatientCockpitService.next_action`` must NOT return the green
"کار اداری باز ثبت نشده" (ok / check) clearance for a patient with no pending
administrative work — that would let an unrun engine masquerade as a clinical
"all clear" (a false negative). It must instead surface a neutral, explicit
"بدون ارزیابی بالینی" frame. When the engine actually RAN and found nothing, the
clearance is legitimate and preserved. Non-analytical administrative priorities
(open follow-ups, refills, first-measurement, scheduled visits) must keep working
precisely regardless of engine state.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.services.patient_cockpit_service import PatientCockpitService  # noqa: E402


# One indicator with a latest reading = the patient HAS data, so the
# "ثبت اولین اندازه‌گیری" branch is not taken and we reach the terminal state.
_HAS_DATA = [{"latest": {"value": 120}}]


def _next(clinical_v2, **overrides):
    kwargs = dict(
        followups=[], refill_due=0, appointments=[], indicators=_HAS_DATA,
        clinical_v2=clinical_v2,
    )
    kwargs.update(overrides)
    return PatientCockpitService.next_action(**kwargs)


def test_engine_off_does_not_present_clinical_all_clear():
    # Facade returns None when the analytical engine mode is off.
    action = _next(clinical_v2=None)

    assert action["title"] == "بدون ارزیابی بالینی"
    assert action["tone"] == "info"  # neutral, not the green "ok" clearance
    assert action["icon"] != "check"
    assert "خاموش" in action["detail"]


def test_engine_unavailable_does_not_present_clinical_all_clear():
    # Facade returns a dict with current=False on stale/error (runtime unavailable).
    unavailable = {
        "current": False,
        "groups": [],
        "message_fa": "ارزیابی بالینی فعلی در دسترس نیست.",
    }
    action = _next(clinical_v2=unavailable)

    assert action["title"] == "بدون ارزیابی بالینی"
    assert action["tone"] == "info"
    assert action["icon"] != "check"
    assert action["detail"] == "ارزیابی بالینی فعلی در دسترس نیست."


def test_engine_ran_empty_keeps_legitimate_clearance():
    # Engine actually ran (current=True) and found nothing -> clearance is real.
    ran_empty = {"current": True, "groups": [], "empty": True}
    action = _next(clinical_v2=ran_empty)

    assert action["title"] == "کار اداری باز ثبت نشده"
    assert action["tone"] == "ok"
    assert action["icon"] == "check"


def test_admin_priorities_still_win_when_engine_off():
    # An open follow-up is administrative and must still be surfaced even
    # though the analytical engine is off (engine-off breaks nothing).
    action = _next(
        clinical_v2=None,
        followups=[{"status": "open", "reason": "refill", "due_date": "2026-08-20"}],
    )

    assert action["icon"] == "phone"
    assert action["target"] == "worklist"
    assert action["title"] != "بدون ارزیابی بالینی"


def test_refill_priority_still_win_when_engine_off():
    action = _next(clinical_v2=None, refill_due=2)

    assert action["icon"] == "pill"
    assert action["target"] == "meds"


def test_first_measurement_prompt_when_engine_off_and_no_data():
    # No data at all -> the neutral first-measurement prompt, not a clearance
    # and not the no-analysis note (there is a concrete administrative action).
    action = _next(clinical_v2=None, indicators=[{"latest": None}])

    assert action["title"] == "ثبت اولین اندازه‌گیری"
    assert action["tone"] == "info"

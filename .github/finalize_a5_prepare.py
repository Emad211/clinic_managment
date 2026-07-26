from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "specialist_clinic/src/services/engagement_service.py"
text = PATH.read_text(encoding="utf-8")

if "SmsGovernanceService" not in text:
    text = text.replace(
        "from src.services.sms.compliance import sanitize\n",
        """from src.services.sms.compliance import sanitize
from src.services.sms.governance_service import (
    SmsConsentDenied,
    SmsGovernanceService,
)
""",
        1,
    )

helper_anchor = '''    def collect_due_events(self, patient_link_id: int) -> tuple[list[dict], dict]:
'''
helper = '''    @staticmethod
    def _care_sms_allowed(patient_link_id: int) -> bool:
        try:
            SmsGovernanceService().require_allowed(
                patient_link_id=int(patient_link_id),
                purpose="CARE",
            )
            return True
        except SmsConsentDenied:
            return False

    def collect_due_events(self, patient_link_id: int) -> tuple[list[dict], dict]:
'''
if helper not in text:
    if helper_anchor not in text:
        raise AssertionError("EngagementService helper anchor missing")
    text = text.replace(helper_anchor, helper, 1)

text = text.replace(
    "SELECT id, full_name, phone_number, sms_opt_out",
    "SELECT id, full_name, phone_number",
)

old_dispatch = '''        opted_out = bool(patient["sms_opt_out"])
        has_phone = bool(patient["phone_number"])
'''
new_dispatch = '''        opted_out = not self._care_sms_allowed(patient_link_id)
        has_phone = bool(patient["phone_number"])
'''
if old_dispatch in text:
    text = text.replace(old_dispatch, new_dispatch, 1)

old_approve = '''        if (
            not patient
            or not patient["phone_number"]
            or patient["sms_opt_out"]
        ):
'''
new_approve = '''        if (
            not patient
            or not patient["phone_number"]
            or not self._care_sms_allowed(int(approval["patient_link_id"]))
        ):
'''
if old_approve in text:
    text = text.replace(old_approve, new_approve, 1)

# enqueue_event_for_patient, enqueue_invite and enqueue_control_room_invite share this
# shape; replace every remaining instance.
old_enqueue = '''        if (
            not patient
            or patient["sms_opt_out"]
            or not patient["phone_number"]
        ):
            return None
'''
new_enqueue = '''        if (
            not patient
            or not patient["phone_number"]
            or not self._care_sms_allowed(patient_link_id)
        ):
            return None
'''
text = text.replace(old_enqueue, new_enqueue)

old_send = '''                source_type="engagement",
                source_ref=str(approval_id),
            )
'''
new_send = '''                source_type="engagement",
                source_ref=str(approval_id),
                purpose="CARE",
                created_by=decided_by,
            )
'''
if old_send in text:
    text = text.replace(old_send, new_send, 1)

remaining = [
    token
    for token in (
        'patient["sms_opt_out"]',
        "patient['sms_opt_out']",
        "phone_number, sms_opt_out",
    )
    if token in text
]
if remaining:
    raise AssertionError(
        "legacy SMS opt-out reads remain in EngagementService: " + ",".join(remaining)
    )

PATH.write_text(text, encoding="utf-8")
Path(__file__).unlink()

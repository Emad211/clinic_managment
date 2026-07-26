from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A5 test anchor missing in {relative}: {old[:180]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Missing/legacy status is unknown, not an in-flight provider-confirmed state.
replace_once(
    "specialist_clinic/tests/test_sms_delivery_lifecycle.py",
    '''        "in_flight": 3,
        "failed": 1,
        "unknown": 1,
''',
    '''        "in_flight": 2,
        "failed": 1,
        "unknown": 2,
''',
)

# NullProvider proves no live panel ran, but acceptance still is not delivery.
replace_once(
    "specialist_clinic/tests/test_visit_invites.py",
    '''        row marked 'sent' with the SIMULATED msgid (proving no live provider ran),
''',
    '''        row marked 'accepted' with the SIMULATED msgid (proving no live provider ran),
''',
)
replace_once(
    "specialist_clinic/tests/test_visit_invites.py",
    '''        assert m["status"] == "sent", f"message status must be 'sent' (simulated), got {m['status']}"
''',
    '''        assert m["status"] == "accepted", f"panel acceptance must remain distinct from delivery, got {m['status']}"
''',
)

# The legacy boolean is now a compatibility mirror. A real opt-out is an immutable CARE
# consent event, which is what every send path reads.
replace_once(
    "specialist_clinic/tests/test_visit_invites.py",
    '''        db.execute("UPDATE patient_links SET sms_opt_out=1 WHERE id=?", (pid,))
        db.commit()

        _force_quiet_off()  # so opt-out — not quiet hours — is the rejection reason regardless of run time
''',
    '''        from src.services.sms.governance_service import SmsGovernanceService
        current = SmsGovernanceService().summary(pid)["CARE"]
        SmsGovernanceService().record(
            patient_link_id=pid,
            purpose="CARE",
            decision="REVOKED",
            actor_username="pytest-patient-request",
            actor_user_id=None,
            source_code="PATIENT_REQUEST",
            idempotency_key=f"pytest-care-revoke:{pid}",
            expected_current_event_id=int(current["id"]),
            reason_code="PATIENT_REQUEST",
        )

        _force_quiet_off()  # so consent — not quiet hours — is the rejection reason regardless of run time
''',
)

replace_once(
    "specialist_clinic/tests/test_approval_quiet_hours.py",
    '''        assert m["status"] == "sent" and m["provider_msgid"] == "SIMULATED", (
''',
    '''        assert m["status"] == "accepted" and m["provider_msgid"] == "SIMULATED", (
''',
)
replace_once(
    "specialist_clinic/tests/test_end_to_end_loops.py",
    '''    assert message["status"] == "sent"
''',
    '''    assert message["status"] == "accepted"
    assert message["delivery_status"] == "Accepted"
''',
)

# Health contract intentionally includes the SMS-governance storage/read-model check.
replace_once(
    "specialist_clinic/tests/test_operational_security_hardening.py",
    '''        "finance_projection",
    }
''',
    '''        "finance_projection",
        "sms_governance",
    }
''',
)

# This isolated assertion must use the fixture's exact accounting path even when another
# test module changed the process-global Config class before teardown.
replace_once(
    "specialist_clinic/tests/test_specialist_attendance_collection.py",
    '''def test_observation_cannot_be_recorded_before_encounter_completion(a4_app):
    from src.adapters import specialist_accounting_invoice_reader

    patient_id, appointment_id = _enroll_and_appointment()
''',
    '''def test_observation_cannot_be_recorded_before_encounter_completion(a4_app):
    from src.adapters import specialist_accounting_invoice_reader

    Config.ACCOUNTING_DB_PATH = str(a4_app[1])
    patient_id, appointment_id = _enroll_and_appointment()
''',
)

Path(__file__).unlink()

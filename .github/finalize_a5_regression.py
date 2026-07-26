from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_all(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if old not in text and new not in text:
        raise AssertionError(f"A5 regression anchor missing in {relative}: {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A5 regression anchor missing in {relative}: {old[:180]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# patient_links has enrolled_at/updated_at, not created_at.
replace_all(
    "specialist_clinic/src/adapters/sqlite/sms_governance_schema.py",
    "COALESCE(enrolled_at, created_at,",
    "COALESCE(enrolled_at, updated_at,",
)
replace_all(
    "specialist_clinic/src/adapters/sqlite/sms_governance_repo.py",
    "COALESCE(enrolled_at, created_at,",
    "COALESCE(enrolled_at, updated_at,",
)

# Delivery report receives immutable purpose/policy metadata.
replace_once(
    "specialist_clinic/src/adapters/sqlite/sms_repo.py",
    '''            "SELECT m.*, c.name campaign_name, p.full_name patient_name FROM sms_messages m "
            "LEFT JOIN sms_campaigns c ON c.id=m.campaign_id "
            "LEFT JOIN patient_links p ON p.id=m.patient_link_id" + where +
''',
    '''            "SELECT m.*, governance.purpose sms_purpose, governance.source_policy, "
            "c.name campaign_name, p.full_name patient_name FROM sms_messages m "
            "LEFT JOIN sms_message_governance governance ON governance.message_id=m.id "
            "LEFT JOIN sms_campaigns c ON c.id=m.campaign_id "
            "LEFT JOIN patient_links p ON p.id=m.patient_link_id" + where +
''',
)

# Use the production registration service so bcrypt hashing is part of the permission test.
replace_once(
    "specialist_clinic/tests/test_sms_governance_a5.py",
    '''    from src.adapters.sqlite.auth_repo import AuthRepository

    AuthRepository().create_user(
        "sms-staff",
        "password123",
        role="staff",
        full_name="SMS Staff",
    )
''',
    '''    from src.services.auth_service import AuthService

    assert AuthService().register_user(
        "sms-staff",
        "password123",
        role="staff",
        full_name="SMS Staff",
    )
''',
)

Path(__file__).unlink()

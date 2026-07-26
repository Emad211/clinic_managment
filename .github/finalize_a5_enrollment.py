from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A5 enrollment anchor missing in {relative}: {old[:180]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# PatientRepository can participate in caller-owned transactions.
replace_once(
    "specialist_clinic/src/adapters/sqlite/patients_repo.py",
    '''        address,
        enrolled_by,
    ) -> int:
''',
    '''        address,
        enrolled_by,
        commit: bool = True,
    ) -> int:
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/patients_repo.py",
    '''        db.commit()
        return int(cursor.lastrowid)
''',
    '''        if commit:
            db.commit()
        return int(cursor.lastrowid)
''',
)

# Accounting enrollment creates consent defaults in the same transaction as cutover.
replace_once(
    "specialist_clinic/src/services/specialist_enrollment_service.py",
    '''            self.repository.create_once(
                patient_link_id=patient_link_id,
                accounting_patient_id=accounting_id,
                effective_at=effective_at,
                accounting_snapshot_at=effective_at,
                accounting_invoice_cutoff_id=cutoff,
                created_by=actor,
                commit=False,
            )
            db.commit()
''',
    '''            self.repository.create_once(
                patient_link_id=patient_link_id,
                accounting_patient_id=accounting_id,
                effective_at=effective_at,
                accounting_snapshot_at=effective_at,
                accounting_invoice_cutoff_id=cutoff,
                created_by=actor,
                commit=False,
            )
            from src.adapters.sqlite.sms_governance_repo import SmsGovernanceRepository
            SmsGovernanceRepository(db).ensure_patient_defaults(
                patient_link_id,
                actor_username=actor,
                commit=False,
            )
            db.commit()
''',
)

# Manual enrollment is one local transaction: patient identity + consent defaults.
replace_once(
    "specialist_clinic/src/services/patient_service.py",
    '''        return self.repo.create(
            national_id=national_id or None,
            accounting_patient_id=None,
            full_name=full_name,
            phone_number=phone_number,
            gender=gender,
            birthdate=birthdate,
            address=address,
            enrolled_by=enrolled_by,
        )
''',
    '''        from src.adapters.sqlite.core import get_db
        from src.adapters.sqlite.sms_governance_repo import SmsGovernanceRepository

        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        try:
            patient_id = self.repo.create(
                national_id=national_id or None,
                accounting_patient_id=None,
                full_name=full_name,
                phone_number=phone_number,
                gender=gender,
                birthdate=birthdate,
                address=address,
                enrolled_by=enrolled_by,
                commit=False,
            )
            SmsGovernanceRepository(db).ensure_patient_defaults(
                patient_id,
                actor_username=str(enrolled_by or "manual-enrollment"),
                commit=False,
            )
            db.commit()
            return patient_id
        except Exception:
            db.rollback()
            raise
''',
)

# Patient detail is read-only. Missing rows are represented as virtual conservative state;
# send/consent mutations materialize the event stream.
replace_once(
    "specialist_clinic/src/services/sms/governance_service.py",
    '''    def summary(self, patient_link_id: int) -> dict[str, dict]:
        rows = self.repository.consent_summary(patient_link_id)
        return {
            purpose: {
                **row,
                "allowed": row["decision"] == "GRANTED",
                "label": self.PURPOSE_LABELS[purpose],
            }
            for purpose, row in rows.items()
        }
''',
    '''    def summary(self, patient_link_id: int) -> dict[str, dict]:
        output: dict[str, dict] = {}
        for purpose in ("CARE", "MARKETING"):
            row = self.repository.current_consent(patient_link_id, purpose)
            if row is None:
                decision = "GRANTED" if purpose == "CARE" else "REVOKED"
                row = {
                    "id": None,
                    "patient_link_id": int(patient_link_id),
                    "purpose": purpose,
                    "decision": decision,
                    "source_code": "NOT_RECORDED_CONSERVATIVE_DEFAULT",
                    "recorded_at": None,
                    "reason_code": None,
                }
            output[purpose] = {
                **row,
                "allowed": row["decision"] == "GRANTED",
                "label": self.PURPOSE_LABELS[purpose],
            }
        return output
''',
)

# Direct-SQL test fixtures explicitly materialize the same defaults enrollment would.
for relative in (
    "specialist_clinic/tests/test_sms_delivery_lifecycle.py",
    "specialist_clinic/tests/test_sms_governance_a5.py",
):
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if relative.endswith("test_sms_delivery_lifecycle.py"):
        old = '''    db.commit()
    return int(patient_id)
'''
        new = '''    db.commit()
    from src.adapters.sqlite.sms_governance_repo import SmsGovernanceRepository
    SmsGovernanceRepository(db).ensure_patient_defaults(int(patient_id))
    return int(patient_id)
'''
    else:
        old = '''    db.commit()
    return int(cursor.lastrowid)
'''
        new = '''    db.commit()
    patient_id = int(cursor.lastrowid)
    from src.adapters.sqlite.sms_governance_repo import SmsGovernanceRepository
    SmsGovernanceRepository(db).ensure_patient_defaults(patient_id)
    return patient_id
'''
    if new not in text:
        if old not in text:
            raise AssertionError(f"A5 test fixture anchor missing: {relative}")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

Path(__file__).unlink()

"""
Step 9 — encounter_service.py tests.

Coverage matrix (all against the REAL Postgres schema via django_db):

  1.  create_encounter → status='open', encounter_at defaults to now if None.
  2.  add_vital_to_encounter → VitalReading created with correct patient_link_id.
  3.  add_lab_to_encounter → LabResult created with encounter_id + patient_link_id derived.
  4.  complete_encounter (open→completed) → status='completed', completed_at set.
  5.  reject double-complete (completed→completed) → InvalidEncounterTransition.
  6.  reject add_vital after completion → EncounterSealed.
  7.  reject add_lab after completion → EncounterSealed.
  8.  cancel_encounter (open→cancelled).
  9.  reject cancel-after-complete → InvalidEncounterTransition.
  10. invalid encounter_type rejected by service guard → InvalidEncounterType
      (before hitting the DB).
  11. duplicate vital (same natural key) → DuplicateVitalReading (not raw IntegrityError).
  12. audit rows written for create + complete (clinical.activity_logs has the rows).
  13. tenant isolation — operating on encounter with wrong tenant_id → EncounterNotFound.

All tests use @pytest.mark.django_db(transaction=True) on the "default" DB
(least-privilege clinical_app role, which CAN write clinical.*).
Never writes to accounting.*; doctor_id left null throughout.
"""
import pytest
from django.utils import timezone

from clinical.encounter_service import (
    create_encounter,
    add_vital_to_encounter,
    add_lab_to_encounter,
    complete_encounter,
    cancel_encounter,
    # domain exceptions
    EncounterNotFound,
    InvalidEncounterTransition,
    EncounterSealed,
    InvalidEncounterType,
    DuplicateVitalReading,
)
from clinical.models import Encounter, VitalReading, LabResult, ActivityLog


# ─────────────────────────────────────────────────────────────────────────────
# 1. create_encounter → open, encounter_at defaults to now
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_create_encounter_defaults(seed_clinical_data):
    """create_encounter with no encounter_at → status=open, encounter_at is set."""
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(
        patient_link_id=link_id,
        tenant_id=1,
        encounter_type="visit",
        created_by="testuser",
    )

    assert enc.id is not None
    assert enc.status == "open"
    assert enc.encounter_type == "visit"
    assert enc.encounter_at is not None, "encounter_at must default to now()"
    assert enc.patient_link_id == link_id
    assert enc.tenant_id == 1
    assert enc.completed_at is None

    # Read back from DB
    enc_db = Encounter.objects.get(id=enc.id, tenant_id=1)
    assert enc_db.status == "open"
    assert enc_db.encounter_at is not None


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_create_encounter_explicit_encounter_at(seed_clinical_data):
    """create_encounter with explicit encounter_at stores it correctly."""
    link_id = seed_clinical_data["link_id"]
    ts = timezone.now().replace(microsecond=0)

    enc = create_encounter(
        patient_link_id=link_id,
        tenant_id=1,
        encounter_type="phone",
        encounter_at=ts,
    )

    enc_db = Encounter.objects.get(id=enc.id, tenant_id=1)
    # Compare at second resolution (Postgres TIMESTAMPTZ may differ in microseconds)
    assert abs((enc_db.encounter_at - ts).total_seconds()) < 2


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_create_encounter_all_types(seed_clinical_data):
    """All four valid encounter_type values are accepted by create_encounter."""
    link_id = seed_clinical_data["link_id"]

    for etype in ("visit", "follow_up", "phone", "remote"):
        enc = create_encounter(
            patient_link_id=link_id,
            tenant_id=1,
            encounter_type=etype,
        )
        assert enc.encounter_type == etype


# ─────────────────────────────────────────────────────────────────────────────
# 2. add_vital_to_encounter — VitalReading with correct patient_link_id
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_add_vital_to_encounter(seed_clinical_data):
    """add_vital_to_encounter creates a VitalReading with patient_link_id derived."""
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(patient_link_id=link_id, tenant_id=1)
    reading = add_vital_to_encounter(
        enc.id,
        1,
        type="bp_systolic",
        value=130.0,
        unit="mmHg",
        source="clinic",
    )

    assert reading.id is not None
    assert reading.patient_link_id == link_id, "patient_link_id must come from the encounter"
    assert reading.type == "bp_systolic"
    assert abs(reading.value - 130.0) < 0.01
    assert reading.unit == "mmHg"
    # The reading MUST be linked to its encounter (slice4b aggregate-root link).
    assert reading.encounter_id == enc.id, "vital must be linked to its encounter"

    # Read back
    r_db = VitalReading.objects.get(id=reading.id)
    assert r_db.patient_link_id == link_id
    assert r_db.encounter_id == enc.id


# ─────────────────────────────────────────────────────────────────────────────
# 3. add_lab_to_encounter — LabResult with encounter_id + derived patient_link_id
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_add_lab_to_encounter(seed_clinical_data):
    """add_lab_to_encounter creates a LabResult with encounter_id and patient_link_id."""
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(patient_link_id=link_id, tenant_id=1)
    lab = add_lab_to_encounter(
        enc.id,
        1,
        test_name="HbA1c",
        test_key=None,   # test_key FKs to lab_test_catalog which is empty in test DB
        value=7.8,
        unit="%",
    )

    assert lab.id is not None
    assert lab.encounter_id == enc.id, "encounter_id must be set from the encounter"
    assert lab.patient_link_id == link_id, "patient_link_id derived from encounter"
    assert lab.test_name == "HbA1c"
    assert abs(lab.value - 7.8) < 0.01

    # Read back
    lab_db = LabResult.objects.get(id=lab.id)
    assert lab_db.encounter_id == enc.id
    assert lab_db.patient_link_id == link_id


# ─────────────────────────────────────────────────────────────────────────────
# 4. complete_encounter (open → completed)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_complete_encounter(seed_clinical_data):
    """complete_encounter: open→completed, completed_at set, summary_note stored."""
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(patient_link_id=link_id, tenant_id=1)
    assert enc.status == "open"

    completed = complete_encounter(
        enc.id,
        1,
        summary_note="بررسی HbA1c — کنترل مطلوب",
        completed_by="dr_ali",
    )

    assert completed.status == "completed"
    assert completed.completed_at is not None
    assert completed.summary_note == "بررسی HbA1c — کنترل مطلوب"

    # Read back from DB
    enc_db = Encounter.objects.get(id=enc.id, tenant_id=1)
    assert enc_db.status == "completed"
    assert enc_db.completed_at is not None


# ─────────────────────────────────────────────────────────────────────────────
# 5. reject double-complete (completed → completed)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_double_complete_raises(seed_clinical_data):
    """Calling complete_encounter twice raises InvalidEncounterTransition."""
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(patient_link_id=link_id, tenant_id=1)
    complete_encounter(enc.id, 1)

    with pytest.raises(InvalidEncounterTransition):
        complete_encounter(enc.id, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 6. reject add_vital after completion → EncounterSealed
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_add_vital_after_complete_raises(seed_clinical_data):
    """Adding a vital to a completed encounter raises EncounterSealed."""
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(patient_link_id=link_id, tenant_id=1)
    complete_encounter(enc.id, 1)

    with pytest.raises(EncounterSealed):
        add_vital_to_encounter(enc.id, 1, type="weight", value=80.0)


# ─────────────────────────────────────────────────────────────────────────────
# 7. reject add_lab after completion → EncounterSealed
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_add_lab_after_complete_raises(seed_clinical_data):
    """Adding a lab to a completed encounter raises EncounterSealed."""
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(patient_link_id=link_id, tenant_id=1)
    complete_encounter(enc.id, 1)

    with pytest.raises(EncounterSealed):
        add_lab_to_encounter(enc.id, 1, test_name="LDL-C", value=100.0)


# ─────────────────────────────────────────────────────────────────────────────
# 8. cancel_encounter (open → cancelled)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_cancel_encounter(seed_clinical_data):
    """cancel_encounter: open→cancelled, reason stored in summary_note."""
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(patient_link_id=link_id, tenant_id=1)
    cancelled = cancel_encounter(enc.id, 1, reason="بیمار مراجعه نکرد")

    assert cancelled.status == "cancelled"
    assert cancelled.summary_note == "بیمار مراجعه نکرد"

    # Read back
    enc_db = Encounter.objects.get(id=enc.id, tenant_id=1)
    assert enc_db.status == "cancelled"


# ─────────────────────────────────────────────────────────────────────────────
# 9. reject cancel-after-complete → InvalidEncounterTransition
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_cancel_after_complete_raises(seed_clinical_data):
    """Calling cancel_encounter on a completed encounter raises InvalidEncounterTransition."""
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(patient_link_id=link_id, tenant_id=1)
    complete_encounter(enc.id, 1)

    with pytest.raises(InvalidEncounterTransition):
        cancel_encounter(enc.id, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 10. invalid encounter_type rejected by service guard (before hitting DB)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_invalid_encounter_type_raises(seed_clinical_data):
    """create_encounter with an invalid type raises InvalidEncounterType (service guard)."""
    link_id = seed_clinical_data["link_id"]

    with pytest.raises(InvalidEncounterType) as exc_info:
        create_encounter(
            patient_link_id=link_id,
            tenant_id=1,
            encounter_type="bogus_type",
        )

    assert "bogus_type" in str(exc_info.value)


# ─────────────────────────────────────────────────────────────────────────────
# 11. duplicate vital → DuplicateVitalReading (not raw IntegrityError)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_duplicate_vital_raises_domain_error(seed_clinical_data):
    """
    Adding two vitals with identical (tenant_id, patient_link_id, type, measured_at, source)
    raises DuplicateVitalReading — not a raw IntegrityError.
    """
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(patient_link_id=link_id, tenant_id=1)
    # Use a fixed measured_at so the natural key is guaranteed identical
    fixed_ts = timezone.now().replace(microsecond=0)

    add_vital_to_encounter(
        enc.id,
        1,
        type="weight",
        value=80.0,
        unit="kg",
        source="clinic",
        measured_at=fixed_ts,
    )

    with pytest.raises(DuplicateVitalReading) as exc_info:
        add_vital_to_encounter(
            enc.id,
            1,
            type="weight",
            value=81.0,         # different value, same natural key
            unit="kg",
            source="clinic",
            measured_at=fixed_ts,
        )

    assert "weight" in str(exc_info.value)


# ─────────────────────────────────────────────────────────────────────────────
# 12. audit rows written for create + complete
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_audit_rows_written(seed_clinical_data):
    """
    create_encounter and complete_encounter each write a row to
    clinical.activity_logs with the correct action_type and target_id.
    """
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(
        patient_link_id=link_id,
        tenant_id=1,
        created_by="dr_test_audit",
    )
    complete_encounter(
        enc.id,
        1,
        completed_by="dr_test_audit",
    )

    # Assert 'encounter_created' audit row
    create_log = ActivityLog.objects.filter(
        tenant_id=1,
        action_type="encounter_created",
        target_table="clinical.encounters",
        target_id=enc.id,
    ).first()
    assert create_log is not None, (
        "audit row for encounter_created must exist in activity_logs"
    )
    assert create_log.patient_link_id == link_id

    # Assert 'encounter_completed' audit row
    complete_log = ActivityLog.objects.filter(
        tenant_id=1,
        action_type="encounter_completed",
        target_table="clinical.encounters",
        target_id=enc.id,
    ).first()
    assert complete_log is not None, (
        "audit row for encounter_completed must exist in activity_logs"
    )
    assert complete_log.patient_link_id == link_id


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_audit_row_for_vital(seed_clinical_data):
    """add_vital_to_encounter writes a 'vital_added' row to activity_logs."""
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(patient_link_id=link_id, tenant_id=1)
    reading = add_vital_to_encounter(
        enc.id, 1, type="bp_diastolic", value=85.0, unit="mmHg"
    )

    audit_row = ActivityLog.objects.filter(
        tenant_id=1,
        action_type="vital_added",
        target_table="clinical.vital_readings",
        target_id=reading.id,
    ).first()
    assert audit_row is not None, "audit row for vital_added must exist"
    assert audit_row.patient_link_id == link_id


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_audit_row_for_lab(seed_clinical_data):
    """add_lab_to_encounter writes a 'lab_added' row to activity_logs."""
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(patient_link_id=link_id, tenant_id=1)
    lab = add_lab_to_encounter(
        enc.id, 1, test_name="eGFR", value=65.0, unit="mL/min"
    )

    audit_row = ActivityLog.objects.filter(
        tenant_id=1,
        action_type="lab_added",
        target_table="clinical.lab_results",
        target_id=lab.id,
    ).first()
    assert audit_row is not None, "audit row for lab_added must exist"
    assert audit_row.patient_link_id == link_id


# ─────────────────────────────────────────────────────────────────────────────
# 13. tenant isolation — wrong tenant_id → EncounterNotFound
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_tenant_isolation_complete(seed_clinical_data):
    """
    Operating on an encounter from a different tenant via complete_encounter
    raises EncounterNotFound (same message as 'not found').
    """
    link_id = seed_clinical_data["link_id"]

    # Create encounter under tenant 1
    enc = create_encounter(patient_link_id=link_id, tenant_id=1)

    # Try to complete it as tenant 2 — must not be visible
    with pytest.raises(EncounterNotFound):
        complete_encounter(enc.id, tenant_id=2)


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_tenant_isolation_add_vital(seed_clinical_data):
    """
    add_vital_to_encounter with the wrong tenant_id raises EncounterNotFound.
    """
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(patient_link_id=link_id, tenant_id=1)

    with pytest.raises(EncounterNotFound):
        add_vital_to_encounter(enc.id, tenant_id=2, type="weight", value=80.0)


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_tenant_isolation_cancel(seed_clinical_data):
    """
    cancel_encounter with the wrong tenant_id raises EncounterNotFound.
    """
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(patient_link_id=link_id, tenant_id=1)

    with pytest.raises(EncounterNotFound):
        cancel_encounter(enc.id, tenant_id=2)


# ─────────────────────────────────────────────────────────────────────────────
# 14. cancel from open (after adding vitals/labs)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_cancel_with_vitals_and_labs(seed_clinical_data):
    """
    An encounter with vitals and labs added can still be cancelled (all immutable after).
    After cancel, add_vital raises EncounterSealed.
    """
    link_id = seed_clinical_data["link_id"]

    enc = create_encounter(patient_link_id=link_id, tenant_id=1)
    add_vital_to_encounter(enc.id, 1, type="heart_rate", value=72.0)
    add_lab_to_encounter(enc.id, 1, test_name="Creatinine", value=1.1, unit="mg/dL")

    cancelled = cancel_encounter(enc.id, 1, reason="داده‌های ناقص")
    assert cancelled.status == "cancelled"

    with pytest.raises(EncounterSealed):
        add_vital_to_encounter(enc.id, 1, type="weight", value=80.0)

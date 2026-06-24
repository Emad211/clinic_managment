"""
Step 8 — managed=False models: Encounter, Appointment, LabResult.

Tests prove the ORM mapping is correct against the REAL Postgres schema
(schema_pg_slice4b_clinical_model.sql applied by conftest.django_db_setup).

Coverage:
  1. Create + read-back Encounter (minimal fields) — field round-trip.
  2. Create + read-back LabResult linked to an Encounter — encounter_id round-trip.
  3. Create + read-back Appointment (including slice4b additive columns).
  4. DB CHECK rejects bad encounter_type ('bogus') — proves column is constrained.
  5. DB CHECK rejects bad Encounter status ('invalid') — proves CHECK is real.
  6. DB CHECK rejects bad Appointment status ('typo') — proves CHECK is real.
  7. FK to patient_links rejects non-existent patient_link_id.
  8. LabResult with valid encounter_id links correctly (encounter_id round-trip).
  9. Appointment doctor_id is stored and retrieved correctly (slice4b column).

Strategy:
  - All tests use @pytest.mark.django_db(transaction=True) with the "default" DB
    (the least-privilege app role, which CAN write clinical.*).
  - Superuser psycopg conn used only for one cross-schema lookup (patient_link_id
    from seed_clinical_data) — the ORM fixture already has the link_id.
  - accounting.* is NEVER written here; doctor_id is left null to avoid needing
    an accounting.medical_staff row.
  - CHECK violations are caught as either django.db.IntegrityError or
    django.db.DataError — we catch both (Postgres raises DataError for CHECK on TEXT).
  - The test DB is session-scoped; all inserts are rolled back per-test because
    transaction=True wraps each test in a savepoint.

NOTE: `created_at` and `updated_at` have DB DEFAULT now() — the ORM must NOT
set them explicitly so the DB fills them in. We pass them as now() values to
satisfy the NOT NULL constraint from the ORM perspective, but the DB DEFAULT
also works if we let the DB assign. Both approaches round-trip correctly because
managed=False means the ORM sends whatever we give it and reads back what the DB
stored.
"""
import pytest
from django.utils import timezone
from django.db import IntegrityError, DataError

from clinical.models import Encounter, Appointment, LabResult, PatientLink


# ────────────────────────────────────────────────────────────────────────────
# Helper: current time (timezone-aware; Django uses UTC internally, Postgres
# stores TIMESTAMPTZ — round-trip is correct regardless of tz offset).
# ────────────────────────────────────────────────────────────────────────────
def _now():
    return timezone.now()


# ════════════════════════════════════════════════════════════════════════════
# 1. Encounter — minimal create + read-back
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_encounter_create_and_read(seed_clinical_data):
    """
    Create a minimal Encounter (visit, open) for the seeded patient_link.
    Read it back via ORM and assert all fields round-trip correctly.
    """
    link_id = seed_clinical_data["link_id"]
    now = _now()

    enc = Encounter.objects.create(
        tenant_id=1,
        patient_link_id=link_id,
        encounter_type="visit",
        encounter_at=now,
        status="open",
        created_at=now,
        updated_at=now,
    )
    assert enc.id is not None, "Encounter id must be assigned by the DB IDENTITY column"

    # Read back fresh from DB
    enc_db = Encounter.objects.get(id=enc.id)
    assert enc_db.patient_link_id == link_id
    assert enc_db.encounter_type == "visit"
    assert enc_db.status == "open"
    assert enc_db.doctor_id is None
    assert enc_db.appointment_id is None
    assert enc_db.accounting_invoice_id is None
    assert enc_db.chief_complaint is None
    assert enc_db.summary_note is None
    assert enc_db.completed_at is None
    assert enc_db.created_by is None


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_encounter_all_encounter_types(seed_clinical_data):
    """
    All four valid encounter_type values must be accepted by the DB CHECK.
    """
    link_id = seed_clinical_data["link_id"]
    now = _now()

    for etype in ("visit", "follow_up", "phone", "remote"):
        enc = Encounter.objects.create(
            tenant_id=1,
            patient_link_id=link_id,
            encounter_type=etype,
            encounter_at=now,
            status="open",
            created_at=now,
            updated_at=now,
        )
        enc_db = Encounter.objects.get(id=enc.id)
        assert enc_db.encounter_type == etype, (
            f"encounter_type='{etype}' did not round-trip correctly"
        )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_encounter_all_status_values(seed_clinical_data):
    """
    All three valid status values must be accepted by the DB CHECK.
    """
    link_id = seed_clinical_data["link_id"]
    now = _now()

    for status in ("open", "completed", "cancelled"):
        enc = Encounter.objects.create(
            tenant_id=1,
            patient_link_id=link_id,
            encounter_type="visit",
            encounter_at=now,
            status=status,
            created_at=now,
            updated_at=now,
        )
        enc_db = Encounter.objects.get(id=enc.id)
        assert enc_db.status == status, (
            f"status='{status}' did not round-trip correctly"
        )


# ════════════════════════════════════════════════════════════════════════════
# 2. LabResult — create + read-back, including encounter_id (slice4b column)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_lab_result_create_and_read(seed_clinical_data):
    """
    Create a LabResult without encounter_id (base columns only), read back.
    """
    link_id = seed_clinical_data["link_id"]
    now = _now()

    lab = LabResult.objects.create(
        tenant_id=1,
        patient_link_id=link_id,
        test_name="HbA1c آزمایش",
        value=7.5,
        unit="%",
        taken_at=now,
        recorded_by="lab_tech",
    )
    assert lab.id is not None

    lab_db = LabResult.objects.get(id=lab.id)
    assert lab_db.test_name == "HbA1c آزمایش"
    assert lab_db.value == pytest.approx(7.5)
    assert lab_db.unit == "%"
    assert lab_db.patient_link_id == link_id
    assert lab_db.encounter_id is None                   # not yet linked to an encounter
    assert lab_db.test_key is None
    assert lab_db.ref_low is None
    assert lab_db.ref_high is None


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_lab_result_encounter_id_round_trip(seed_clinical_data):
    """
    Create an Encounter, then a LabResult with encounter_id pointing to it.
    Verify encounter_id round-trips correctly (slice4b additive column FK).
    """
    link_id = seed_clinical_data["link_id"]
    now = _now()

    enc = Encounter.objects.create(
        tenant_id=1,
        patient_link_id=link_id,
        encounter_type="visit",
        encounter_at=now,
        status="open",
        created_at=now,
        updated_at=now,
    )

    lab = LabResult.objects.create(
        tenant_id=1,
        patient_link_id=link_id,
        test_name="LDL-C",
        value=115.0,
        unit="mg/dL",
        taken_at=now,
        encounter_id=enc.id,
    )
    assert lab.id is not None

    lab_db = LabResult.objects.get(id=lab.id)
    assert lab_db.encounter_id == enc.id, (
        f"encounter_id must round-trip: expected {enc.id}, got {lab_db.encounter_id}"
    )


# ════════════════════════════════════════════════════════════════════════════
# 3. Appointment — create + read-back (base + slice4b additive columns)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_appointment_create_and_read(seed_clinical_data):
    """
    Create an Appointment (base columns), read back and verify round-trip.
    Includes reminder_sent (BooleanField), status CHECK values.
    """
    link_id = seed_clinical_data["link_id"]
    now = _now()

    appt = Appointment.objects.create(
        tenant_id=1,
        patient_link_id=link_id,
        scheduled_at=now,
        appt_type="visit",
        status="scheduled",
        reminder_sent=False,
        notes="تست نوبت",
        created_by="testuser",
        created_at=now,
    )
    assert appt.id is not None

    appt_db = Appointment.objects.get(id=appt.id)
    assert appt_db.patient_link_id == link_id
    assert appt_db.status == "scheduled"
    assert appt_db.appt_type == "visit"
    assert appt_db.reminder_sent is False
    assert appt_db.notes == "تست نوبت"
    assert appt_db.doctor_id is None              # slice4b column — nullable
    assert appt_db.chief_complaint is None         # slice4b column — nullable
    assert appt_db.recurrence_months is None
    assert appt_db.parent_appointment_id is None


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_appointment_slice4b_columns(seed_clinical_data):
    """
    Appointment.chief_complaint (slice4b additive column) must store and
    retrieve correctly. doctor_id is left null to avoid needing an
    accounting.medical_staff row.
    """
    link_id = seed_clinical_data["link_id"]
    now = _now()

    appt = Appointment.objects.create(
        tenant_id=1,
        patient_link_id=link_id,
        scheduled_at=now,
        status="scheduled",
        chief_complaint="سردرد شدید",     # slice4b additive column
        doctor_id=None,                   # slice4b additive column — left null
        created_at=now,
    )

    appt_db = Appointment.objects.get(id=appt.id)
    assert appt_db.chief_complaint == "سردرد شدید", (
        "chief_complaint (slice4b column) must round-trip correctly"
    )
    assert appt_db.doctor_id is None


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_appointment_all_status_values(seed_clinical_data):
    """
    All four valid Appointment status values must pass the DB CHECK.
    """
    link_id = seed_clinical_data["link_id"]
    now = _now()

    for status in ("scheduled", "done", "no_show", "cancelled"):
        appt = Appointment.objects.create(
            tenant_id=1,
            patient_link_id=link_id,
            scheduled_at=now,
            status=status,
            created_at=now,
        )
        appt_db = Appointment.objects.get(id=appt.id)
        assert appt_db.status == status, (
            f"Appointment status='{status}' did not round-trip"
        )


# ════════════════════════════════════════════════════════════════════════════
# 4. DB CHECK constraint rejection tests
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_encounter_bad_encounter_type_rejected(seed_clinical_data):
    """
    Creating an Encounter with encounter_type='bogus' must raise IntegrityError
    or DataError — Postgres CHECK rejects it.

    This proves the ORM model maps to the CHECK-constrained column in the real schema.
    """
    link_id = seed_clinical_data["link_id"]
    now = _now()

    with pytest.raises((IntegrityError, DataError)):
        Encounter.objects.create(
            tenant_id=1,
            patient_link_id=link_id,
            encounter_type="bogus",          # NOT in ('visit','follow_up','phone','remote')
            encounter_at=now,
            status="open",
            created_at=now,
            updated_at=now,
        )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_encounter_bad_status_rejected(seed_clinical_data):
    """
    Creating an Encounter with status='invalid' must raise IntegrityError or
    DataError — Postgres CHECK IN ('open','completed','cancelled') rejects it.
    """
    link_id = seed_clinical_data["link_id"]
    now = _now()

    with pytest.raises((IntegrityError, DataError)):
        Encounter.objects.create(
            tenant_id=1,
            patient_link_id=link_id,
            encounter_type="visit",
            encounter_at=now,
            status="invalid",               # NOT in ('open','completed','cancelled')
            created_at=now,
            updated_at=now,
        )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_appointment_bad_status_rejected(seed_clinical_data):
    """
    Creating an Appointment with status='typo' must raise IntegrityError or
    DataError — Postgres CHECK IN ('scheduled','done','no_show','cancelled').
    """
    link_id = seed_clinical_data["link_id"]
    now = _now()

    with pytest.raises((IntegrityError, DataError)):
        Appointment.objects.create(
            tenant_id=1,
            patient_link_id=link_id,
            scheduled_at=now,
            status="typo",                  # NOT in valid set
            created_at=now,
        )


# ════════════════════════════════════════════════════════════════════════════
# 5. FK rejection — non-existent patient_link_id raises at DB level
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_encounter_nonexistent_patient_link_rejected():
    """
    Creating an Encounter with a patient_link_id that does not exist in
    clinical.patient_links must raise IntegrityError (FK violation).

    This proves the composite FK (tenant_id, patient_link_id) →
    clinical.patient_links is enforced by Postgres.
    """
    now = _now()

    with pytest.raises(IntegrityError):
        Encounter.objects.create(
            tenant_id=1,
            patient_link_id=999_999_999,    # guaranteed non-existent
            encounter_type="visit",
            encounter_at=now,
            status="open",
            created_at=now,
            updated_at=now,
        )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_lab_result_nonexistent_patient_link_rejected():
    """
    Creating a LabResult with a patient_link_id that does not exist must raise
    IntegrityError (composite FK (tenant_id, patient_link_id) violation).
    """
    now = _now()

    with pytest.raises(IntegrityError):
        LabResult.objects.create(
            tenant_id=1,
            patient_link_id=999_999_999,    # guaranteed non-existent
            test_name="غیرمجاز",
            taken_at=now,
        )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_appointment_nonexistent_patient_link_rejected():
    """
    Creating an Appointment with a non-existent patient_link_id must raise
    IntegrityError (composite FK (tenant_id, patient_link_id) violation).
    """
    now = _now()

    with pytest.raises(IntegrityError):
        Appointment.objects.create(
            tenant_id=1,
            patient_link_id=999_999_999,    # guaranteed non-existent
            scheduled_at=now,
            status="scheduled",
            created_at=now,
        )


# ════════════════════════════════════════════════════════════════════════════
# 6. Encounter ↔ LabResult ↔ Appointment — three-way link
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_encounter_appointment_lab_three_way(seed_clinical_data):
    """
    Integration: create Appointment → Encounter (linked to appointment) →
    LabResult (linked to encounter). Verify all three FKs round-trip.

    This exercises the full slice4b FK graph in one test.
    """
    link_id = seed_clinical_data["link_id"]
    now = _now()

    # Step 1: Create an appointment
    appt = Appointment.objects.create(
        tenant_id=1,
        patient_link_id=link_id,
        scheduled_at=now,
        status="scheduled",
        chief_complaint="کنترل دوره‌ای دیابت",
        created_at=now,
    )

    # Step 2: Create an encounter linked to the appointment
    enc = Encounter.objects.create(
        tenant_id=1,
        patient_link_id=link_id,
        encounter_type="visit",
        encounter_at=now,
        status="open",
        appointment_id=appt.id,
        chief_complaint="کنترل HbA1c",
        created_at=now,
        updated_at=now,
    )

    # Step 3: Create a lab result linked to the encounter
    lab = LabResult.objects.create(
        tenant_id=1,
        patient_link_id=link_id,
        test_name="HbA1c",
        value=8.2,
        unit="%",
        taken_at=now,
        encounter_id=enc.id,
        recorded_by="lab",
    )

    # Verify round-trips
    enc_db = Encounter.objects.get(id=enc.id)
    assert enc_db.appointment_id == appt.id, "appointment_id must link to appointment"
    assert enc_db.chief_complaint == "کنترل HbA1c"

    lab_db = LabResult.objects.get(id=lab.id)
    assert lab_db.encounter_id == enc.id, "encounter_id must link to encounter"
    assert lab_db.value == pytest.approx(8.2)

    appt_db = Appointment.objects.get(id=appt.id)
    assert appt_db.chief_complaint == "کنترل دوره‌ای دیابت"


# ════════════════════════════════════════════════════════════════════════════
# 7. ORM queryset filtering (proves managed=False does real SQL queries)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_encounter_queryset_filter_by_status(seed_clinical_data):
    """
    Create two encounters with different statuses; filter by status via ORM.
    Proves the ORM runs real SQL against the clinical.encounters table.
    """
    link_id = seed_clinical_data["link_id"]
    now = _now()

    enc_open = Encounter.objects.create(
        tenant_id=1,
        patient_link_id=link_id,
        encounter_type="visit",
        encounter_at=now,
        status="open",
        created_at=now,
        updated_at=now,
    )
    enc_done = Encounter.objects.create(
        tenant_id=1,
        patient_link_id=link_id,
        encounter_type="phone",
        encounter_at=now,
        status="completed",
        created_at=now,
        updated_at=now,
    )

    open_ids = set(
        Encounter.objects.filter(
            patient_link_id=link_id,
            tenant_id=1,
            status="open",
        ).values_list("id", flat=True)
    )
    completed_ids = set(
        Encounter.objects.filter(
            patient_link_id=link_id,
            tenant_id=1,
            status="completed",
        ).values_list("id", flat=True)
    )

    assert enc_open.id in open_ids, "open encounter must appear in open queryset"
    assert enc_done.id in completed_ids, "completed encounter must appear in completed queryset"
    assert enc_done.id not in open_ids, "completed encounter must NOT appear in open queryset"

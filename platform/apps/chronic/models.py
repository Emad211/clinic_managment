"""Chronic-disease module: the clinical core of the revenue wedge.

Holds the ADA decision-support engine's data (clinical_indicator,
clinical_rule, flag_catalog, drug_class — global catalogs seeded once and
per-clinic overridable) plus per-patient clinical records (vitals, meds,
labs, appointments, follow-ups, flags, wallet) — see docs/DATA_MODEL.md §4-5.

Decision support is advisory only: "پیشنهاد — تأیید با پزشک". Every suggestion
the engine emits is written append-only to ``SuggestionLog`` for accountability.
"""

from django.db import models

from apps.common.models import CatalogModel, TenantModel

# ──────────────────────────────────────────────────────────────────────────
# Global catalogs (clinic NULL = global default; clinic set = per-tenant override)
# ──────────────────────────────────────────────────────────────────────────


class DrugClass(CatalogModel):
    """19 seeded drug classes (metformin, sulfonylurea, ...)."""

    code = models.TextField()
    name_fa = models.TextField()
    name_en = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "drug_class"
        indexes = [models.Index(fields=["clinic", "code"])]


class Condition(CatalogModel):
    """Chronic condition catalog (diabetes T2, hypertension, ...)."""

    code = models.TextField()
    name_fa = models.TextField()
    name_en = models.TextField(blank=True, default="")

    class Meta:
        db_table = "condition"
        indexes = [models.Index(fields=["clinic", "code"])]


class ClinicalIndicator(CatalogModel):
    """ADA-based threshold catalog: e.g. hba1c warn=7 danger=8, fbs 130/180,
    bp_systolic 130/140. Keep in sync with vitals_service.THRESHOLDS and
    analytics_service.TARGETS when a threshold changes (CLAUDE.md rule)."""

    key = models.TextField()  # hba1c, fbs, bp_systolic, ...
    name_fa = models.TextField()
    unit = models.TextField(blank=True, default="")
    warn_low = models.FloatField(null=True, blank=True)
    warn_high = models.FloatField(null=True, blank=True)
    danger_low = models.FloatField(null=True, blank=True)
    danger_high = models.FloatField(null=True, blank=True)
    target_text = models.TextField(blank=True, default="")

    class Meta:
        db_table = "clinical_indicator"
        indexes = [models.Index(fields=["clinic", "key"])]


class ClinicalRule(CatalogModel):
    """The ~57 ADA rules. ``trigger_json`` is the all/any/not + leaf DSL the
    rule_engine evaluates against patient facts. Stored as JSON(B on Postgres)."""

    SEVERITY = [
        ("info", "info"),
        ("suggestion", "suggestion"),
        ("warning", "warning"),
        ("red_flag", "red_flag"),
    ]

    code = models.TextField()
    title = models.TextField()
    category = models.TextField(blank=True, default="")
    severity = models.CharField(max_length=16, choices=SEVERITY, default="suggestion")
    trigger_json = models.JSONField(default=dict)
    message_fa = models.TextField(blank=True, default="")
    source_ref = models.TextField(blank=True, default="", help_text="ADA citation")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "clinical_rule"
        indexes = [models.Index(fields=["clinic", "code"])]


class FlagCatalog(CatalogModel):
    """18 seeded patient flags (red-flag/risk markers)."""

    code = models.TextField()
    label_fa = models.TextField()
    severity = models.TextField(blank=True, default="")
    color = models.TextField(blank=True, default="")

    class Meta:
        db_table = "flag_catalog"
        indexes = [models.Index(fields=["clinic", "code"])]


# ──────────────────────────────────────────────────────────────────────────
# Per-patient clinical records (tenant-owned)
# ──────────────────────────────────────────────────────────────────────────


class PatientCondition(TenantModel):
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="conditions"
    )
    condition = models.ForeignKey(Condition, on_delete=models.PROTECT, related_name="+")
    onset_date = models.DateField(null=True, blank=True)
    status = models.TextField(blank=True, default="active")
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "patient_condition"
        indexes = [models.Index(fields=["clinic", "patient"])]


class PatientMedication(TenantModel):
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="medications"
    )
    drug_class = models.ForeignKey(
        DrugClass, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    name = models.TextField()
    dose = models.TextField(blank=True, default="")
    frequency = models.TextField(blank=True, default="")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "patient_medication"
        indexes = [models.Index(fields=["clinic", "patient", "is_active"])]


class MedicationEvent(TenantModel):
    """Timeline of medication changes (start/stop/dose-change)."""

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="medication_events"
    )
    medication = models.ForeignKey(
        PatientMedication, on_delete=models.CASCADE, related_name="events",
        null=True, blank=True,
    )
    event_type = models.TextField()  # started|stopped|dose_changed|...
    detail = models.TextField(blank=True, default="")
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = "medication_event"
        indexes = [models.Index(fields=["clinic", "patient", "occurred_at"])]


class Allergy(TenantModel):
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="allergies"
    )
    substance = models.TextField()
    reaction = models.TextField(blank=True, default="")
    severity = models.TextField(blank=True, default="")

    class Meta:
        db_table = "allergy"
        indexes = [models.Index(fields=["clinic", "patient"])]


class VitalReading(TenantModel):
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="vitals"
    )
    indicator = models.ForeignKey(
        ClinicalIndicator, on_delete=models.PROTECT, related_name="+",
        null=True, blank=True,
    )
    indicator_key = models.TextField()  # denormalised for fast filtering
    value = models.DecimalField(max_digits=10, decimal_places=2)
    measured_at = models.DateTimeField()
    source = models.TextField(blank=True, default="")  # clinic|home|lab

    class Meta:
        db_table = "vital_reading"
        indexes = [
            models.Index(fields=["clinic", "patient", "indicator_key", "-measured_at"])
        ]


class LabResult(TenantModel):
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="labs"
    )
    test_name = models.TextField()
    value = models.TextField()
    unit = models.TextField(blank=True, default="")
    reference_range = models.TextField(blank=True, default="")
    taken_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "lab_result"
        indexes = [models.Index(fields=["clinic", "patient", "-taken_at"])]


class Appointment(TenantModel):
    STATUS = [
        ("scheduled", "scheduled"),
        ("done", "done"),
        ("cancelled", "cancelled"),
        ("no_show", "no_show"),
    ]
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="appointments"
    )
    doctor = models.ForeignKey(
        "identity.AppUser", on_delete=models.SET_NULL, related_name="+",
        null=True, blank=True,
    )
    scheduled_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=STATUS, default="scheduled")
    reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "appointment"
        indexes = [models.Index(fields=["clinic", "scheduled_at", "status"])]


class CareProtocol(TenantModel):
    """Recall/follow-up protocol (Epic 3) — physician-definable per clinic."""

    name = models.TextField()
    description = models.TextField(blank=True, default="")
    item_key = models.TextField()  # a1c|renal|lipid|eye|foot|...
    interval_months = models.IntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "care_protocol"
        indexes = [models.Index(fields=["clinic", "item_key"])]


class FollowupTask(TenantModel):
    """Due monitoring/screening tasks produced by followup_engine. Created only
    when due (interval elapsed / never done); deduped against recent handling."""

    STATUS = [
        ("open", "open"),
        ("done", "done"),
        ("snoozed", "snoozed"),
        ("dismissed", "dismissed"),
    ]
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="followups"
    )
    item_key = models.TextField()
    title = models.TextField()
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS, default="open")
    source_rule = models.TextField(blank=True, default="")
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "followup_task"
        indexes = [models.Index(fields=["clinic", "status", "due_date"])]


class PatientFlag(TenantModel):
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="flags"
    )
    flag = models.ForeignKey(FlagCatalog, on_delete=models.PROTECT, related_name="+")
    is_active = models.BooleanField(default=True)
    raised_at = models.DateTimeField()
    cleared_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "patient_flag"
        indexes = [models.Index(fields=["clinic", "patient", "is_active"])]


class SuggestionLog(TenantModel):
    """Append-only record of every decision-support suggestion shown to a
    physician (accountability; "suggests, does not decide")."""

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="suggestions"
    )
    rule_code = models.TextField(blank=True, default="")
    severity = models.TextField(blank=True, default="")
    message_fa = models.TextField()
    acknowledged_by = models.ForeignKey(
        "identity.AppUser", on_delete=models.SET_NULL, related_name="+",
        null=True, blank=True,
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "suggestion_log"
        indexes = [models.Index(fields=["clinic", "patient", "-created_at"])]


class WalletTransaction(TenantModel):
    """Append-only wallet ledger (lawful replacement for discount/free)."""

    KIND = [("credit", "credit"), ("debit", "debit")]
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="wallet_transactions"
    )
    kind = models.CharField(max_length=8, choices=KIND)
    amount = models.BigIntegerField()  # Rial, positive
    balance_after = models.BigIntegerField()
    reason = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        "identity.AppUser", on_delete=models.SET_NULL, related_name="+",
        null=True, blank=True,
    )

    class Meta:
        db_table = "wallet_transaction"
        indexes = [models.Index(fields=["clinic", "patient", "-created_at"])]

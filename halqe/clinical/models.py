"""
clinical models — managed=False (schema owned by SQL slices).

All clinical tables FK to clinical.patient_links(id) via patient_link_id.
Cross-schema FK to accounting.patients is expressed as BigIntegerField
(db_constraint=False) — the real composite FK lives in the SQL.

PatientLink: thin enrollment record (ADR-0007 §2.1 — no demographic mirror).
VitalReading: the vitals half of the canonical Observation (ADR-0005).
"""
from django.db import models


class PatientLink(models.Model):
    """
    clinical.patient_links — enrollment record linking to accounting.patients.

    patient_id is a BigIntegerField (no ORM FK) because the real constraint
    is a composite FK across schemas, which Django cannot represent.
    """

    tenant_id = models.BigIntegerField(default=1)
    # Cross-schema FK expressed as plain int — DB enforces it
    patient_id = models.BigIntegerField()
    wallet_balance = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    sms_opt_out = models.BooleanField(default=False)
    sms_consent = models.BooleanField(default=False)
    sms_consent_at = models.DateTimeField(null=True, blank=True)
    sms_consent_source = models.TextField(null=True, blank=True)
    sms_opt_out_at = models.DateTimeField(null=True, blank=True)
    data_retention_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    enrolled_by = models.TextField(null=True, blank=True)
    enrolled_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        app_label = "clinical"
        db_table = '"clinical"."patient_links"'
        ordering = ["id"]

    def __str__(self):
        return f"PatientLink(id={self.id}, patient_id={self.patient_id})"


class VitalReading(models.Model):
    """
    clinical.vital_readings — vitals half of Observation canonical (ADR-0005).

    Columns from slice2:
      patient_link_id, type, value, unit, measured_at, source, notes, recorded_by
    """

    tenant_id = models.BigIntegerField(default=1)
    patient_link_id = models.BigIntegerField()
    type = models.TextField()
    value = models.FloatField()
    unit = models.TextField(null=True, blank=True)
    measured_at = models.DateTimeField()
    source = models.TextField(default="clinic", null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    recorded_by = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        app_label = "clinical"
        db_table = '"clinical"."vital_readings"'
        ordering = ["-measured_at"]

    def __str__(self):
        return (
            f"VitalReading(type={self.type}, value={self.value}, "
            f"patient_link_id={self.patient_link_id})"
        )

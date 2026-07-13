"""Managed=False models for the structured patient-record aggregate.

The PostgreSQL tables already exist in ``schema_pg_slice2_clinical.sql`` and are
owned by SQL slices. They live in this module to keep ``clinical.models`` from
growing into another god file; ``ClinicalConfig.import_models`` imports this
module during Django's model-loading phase.
"""
from __future__ import annotations

from django.db import models
from django.db.models.functions import Now


class FlagCatalog(models.Model):
    """Metadata for typed patient flags used by the clinical rule engine."""

    tenant_id = models.BigIntegerField(default=1)
    flag_key = models.TextField()
    label = models.TextField()
    flag_type = models.TextField(default="bool")
    options = models.TextField(null=True, blank=True)
    category = models.TextField(default="other")
    record_section = models.TextField(null=True, blank=True)
    display_order = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        app_label = "clinical"
        db_table = '"clinical"."flag_catalog"'
        ordering = ["record_section", "display_order", "id"]


class DrugClass(models.Model):
    tenant_id = models.BigIntegerField(default=1)
    class_key = models.TextField()
    label = models.TextField()
    glucose_lowering = models.BooleanField(default=False)
    display_order = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        app_label = "clinical"
        db_table = '"clinical"."drug_classes"'
        ordering = ["display_order", "id"]


class DrugCatalog(models.Model):
    tenant_id = models.BigIntegerField(default=1)
    generic_fa = models.TextField()
    drug_class_key = models.TextField(null=True, blank=True)
    standard_doses = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        app_label = "clinical"
        db_table = '"clinical"."drug_catalog"'
        ordering = ["generic_fa", "id"]


class LabTestCatalog(models.Model):
    tenant_id = models.BigIntegerField(default=1)
    test_key = models.TextField()
    name_fa = models.TextField()
    unit = models.TextField(null=True, blank=True)
    ref_low = models.FloatField(null=True, blank=True)
    ref_high = models.FloatField(null=True, blank=True)
    category = models.TextField(null=True, blank=True)
    display_order = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        app_label = "clinical"
        db_table = '"clinical"."lab_test_catalog"'
        ordering = ["display_order", "id"]


class MedicationEvent(models.Model):
    """Append-style medication timeline: start, stop and dose_change."""

    tenant_id = models.BigIntegerField(default=1)
    patient_link_id = models.BigIntegerField()
    medication_id = models.BigIntegerField(null=True, blank=True)
    drug_name = models.TextField()
    event_type = models.TextField()
    dose = models.TextField(null=True, blank=True)
    event_date = models.DateField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    created_by = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        managed = False
        app_label = "clinical"
        db_table = '"clinical"."medication_events"'
        ordering = ["event_date", "id"]


class SurgeryHistory(models.Model):
    tenant_id = models.BigIntegerField(default=1)
    patient_link_id = models.BigIntegerField()
    title = models.TextField()
    performed_on = models.DateField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        managed = False
        app_label = "clinical"
        db_table = '"clinical"."surgery_history"'
        ordering = [models.F("performed_on").desc(nulls_last=True), "-id"]


class MedicalHistory(models.Model):
    tenant_id = models.BigIntegerField(default=1)
    patient_link_id = models.BigIntegerField()
    title = models.TextField()
    note = models.TextField(null=True, blank=True)
    since = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        managed = False
        app_label = "clinical"
        db_table = '"clinical"."medical_history"'
        ordering = [models.F("since").desc(nulls_last=True), "-id"]


class ClinicalNote(models.Model):
    KIND_SYMPTOM = "symptom"
    KIND_EXAM = "exam"
    KIND_LIFESTYLE = "lifestyle"
    KIND_GENERAL = "general"
    ALLOWED_KINDS = frozenset(
        {KIND_SYMPTOM, KIND_EXAM, KIND_LIFESTYLE, KIND_GENERAL}
    )

    tenant_id = models.BigIntegerField(default=1)
    patient_link_id = models.BigIntegerField()
    kind = models.TextField()
    body = models.TextField(null=True, blank=True)
    recorded_at = models.DateTimeField(db_default=Now())
    recorded_by = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        app_label = "clinical"
        db_table = '"clinical"."clinical_notes"'
        ordering = ["-recorded_at", "-id"]

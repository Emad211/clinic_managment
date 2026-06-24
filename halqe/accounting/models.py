"""
accounting models — managed=False (schema owned by SQL slices).

The accounting schema is WRITE-FORBIDDEN from the clinical side.
The ClinicalRouter raises PermissionError on any db_for_write call for
app_label='accounting'. At DB level, clinical_app has only SELECT on the
6 accounting tables (granted in slice0/slice3).

Only accounting.Patient is defined here — it is the canonical owner of
patient identity/demographics (ADR-0007 §2.1).

Cross-schema FK from clinical.PatientLink → accounting.Patient is expressed
as a plain BigIntegerField (db_constraint=False) because Django cannot
represent cross-schema FK constraints; the real FK lives in the SQL.
"""
import uuid as uuid_module
from django.db import models


class Patient(models.Model):
    """
    accounting.patients — canonical patient identity registry.

    full_name is a GENERATED ALWAYS STORED column (name || ' ' || family_name).
    It must be declared editable=False so Django never tries to INSERT/UPDATE it.
    We use models.GeneratedField is Django 5+; for compatibility with the
    managed=False approach we simply declare it as a non-editable TextField.
    """

    # tenant_id — FK to platform.tenants; cross-app FK expressed as BigIntegerField.
    tenant_id = models.BigIntegerField(default=1)

    uuid = models.UUIDField(unique=True)
    name = models.TextField()
    family_name = models.TextField()
    # GENERATED ALWAYS STORED — read only; never written by ORM
    full_name = models.TextField(editable=False)
    national_id = models.TextField(null=True, blank=True)
    phone_number = models.TextField(null=True, blank=True)
    birthdate = models.DateField(null=True, blank=True)
    gender = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        app_label = "accounting"
        db_table = '"accounting"."patients"'
        ordering = ["id"]

    def __str__(self):
        return f"{self.full_name} ({self.uuid})"

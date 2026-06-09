"""Patients module: the unified patient.

Merges webapp.patients + specialist.patient_links into ONE entity
(docs/DATA_MODEL.md §4-5). This retires the read-only accounting_bridge: a
patient is a single row owned by a clinic, not two rows joined by national_id
across two databases.
"""

from django.db import models

from apps.common.models import TenantModel


class Patient(TenantModel):
    GENDER = [("male", "male"), ("female", "female"), ("other", "other")]

    national_id = models.TextField(null=True, blank=True)
    first_name = models.TextField(blank=True, default="")
    last_name = models.TextField(blank=True, default="")
    # full_name is a Postgres GENERATED column in DATA_MODEL; kept as a plain
    # editable field in the scaffold and computed in the app layer. The
    # GENERATED-column form is applied via RunSQL when we target Postgres.
    phone_number = models.TextField(blank=True, default="")
    gender = models.CharField(max_length=10, choices=GENDER, blank=True, default="")
    birthdate = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True, default="")
    insurance_type = models.TextField(blank=True, default="")
    insurance_expiry = models.DateField(null=True, blank=True)
    is_foreign = models.BooleanField(default=False)
    # wallet balance lives on the patient (from specialist.patient_links);
    # mutations are append-only via chronic.WalletTransaction.
    wallet_balance = models.BigIntegerField(default=0)  # Rial
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "patient"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "national_id"], name="uq_patient_clinic_national_id"
            )
        ]
        indexes = [
            models.Index(fields=["clinic", "national_id"]),
            models.Index(fields=["clinic", "last_name", "first_name"]),
        ]

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        return self.full_name or (self.national_id or str(self.id))

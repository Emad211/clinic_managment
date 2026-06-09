"""E-prescription module (Epic 1, docs/EPRESCRIPTION.md).

Channel evolves A->B: WebView bridge now (`channel='webview'`), native insurer
API later once the صلاحیت/افتا certificate lands (`channel='api'`). Drug is a
PLATFORM-level generic reference dataset (no clinic_id); Prescription/items and
the insurer connection log are tenant-owned.
"""

from django.db import models

from apps.common.models import TenantModel, TimeStampedModel, UUIDModel


class Drug(UUIDModel, TimeStampedModel):
    """Generic drug reference (IRC/ATC). Dataset source is an open decision —
    دارویاب/تیتک/official list (docs/DATA_MODEL.md §8). NOT tenant-scoped."""

    generic_name = models.TextField()
    irc_code = models.TextField(blank=True, default="")
    atc_code = models.TextField(blank=True, default="")
    form = models.TextField(blank=True, default="")
    strength = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "drug"
        indexes = [
            models.Index(fields=["generic_name"]),
            models.Index(fields=["irc_code"]),
        ]

    def __str__(self):
        return f"{self.generic_name} {self.strength}".strip()


class Prescription(TenantModel):
    INSURERS = [("tamin", "tamin"), ("ihio", "ihio"), ("armed", "armed")]
    STATUS = [
        ("draft", "draft"),
        ("submitted", "submitted"),
        ("registered", "registered"),
        ("failed", "failed"),
    ]
    CHANNELS = [("webview", "webview"), ("api", "api")]

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="prescriptions"
    )
    doctor = models.ForeignKey(
        "identity.AppUser", on_delete=models.PROTECT, related_name="+"
    )
    insurer = models.CharField(max_length=10, choices=INSURERS)
    status = models.CharField(max_length=12, choices=STATUS, default="draft")
    tracking_code = models.TextField(blank=True, default="")  # کدِ رهگیریِ بیمه
    channel = models.CharField(max_length=10, choices=CHANNELS, default="webview")
    issued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "prescription"
        indexes = [
            models.Index(fields=["clinic", "patient", "-created_at"]),
            models.Index(fields=["clinic", "status"]),
        ]


class PrescriptionItem(TenantModel):
    KINDS = [("drug", "drug"), ("paraclinical", "paraclinical"), ("service", "service")]

    prescription = models.ForeignKey(
        Prescription, on_delete=models.CASCADE, related_name="items"
    )
    kind = models.CharField(max_length=16, choices=KINDS, default="drug")
    drug = models.ForeignKey(
        Drug, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    item_name = models.TextField(blank=True, default="")
    dose = models.TextField(blank=True, default="")
    count = models.IntegerField(null=True, blank=True)
    instruction = models.TextField(blank=True, default="")

    class Meta:
        db_table = "prescription_item"
        indexes = [models.Index(fields=["clinic", "prescription"])]


class InsurerLog(TenantModel):
    """Append-only trace of every insurer interaction (WebView open / API call)."""

    prescription = models.ForeignKey(
        Prescription, on_delete=models.SET_NULL, related_name="logs",
        null=True, blank=True,
    )
    insurer = models.TextField(blank=True, default="")
    action = models.TextField(blank=True, default="")
    status = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "insurer_log"
        indexes = [models.Index(fields=["clinic", "-created_at"])]

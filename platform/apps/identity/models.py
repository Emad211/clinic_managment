"""Identity module: the tenant (Clinic), users, shifts.

Maps webapp.users + webapp.medical_staff + specialist.users -> a single
``AppUser`` (docs/DATA_MODEL.md §4-5). Auth integration (making AppUser the
Django AUTH_USER_MODEL vs. keeping it a plain model) is an open scaffold
decision -- see platform/README.md. For now AppUser is a plain model that
preserves the existing bcrypt + lockout semantics.
"""

import uuid

from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel


class Clinic(UUIDModel, TimeStampedModel):
    """The tenant. Every domain row points back here via ``clinic_id``."""

    STATUS = [
        ("trial", "trial"),
        ("active", "active"),
        ("suspended", "suspended"),
        ("cancelled", "cancelled"),
    ]

    name = models.TextField()
    slug = models.SlugField(unique=True, max_length=64)
    status = models.CharField(max_length=16, choices=STATUS, default="trial")
    province = models.TextField(blank=True, default="")
    city = models.TextField(blank=True, default="")

    class Meta:
        db_table = "clinic"

    def __str__(self):
        return f"{self.name} ({self.slug})"


class AppUser(UUIDModel, TimeStampedModel):
    """A clinic staff account. bcrypt password + 5-fail/15-min lockout preserved
    from the current Flask apps' auth_service."""

    ROLES = [
        ("clinic_manager", "clinic_manager"),
        ("doctor", "doctor"),
        ("reception", "reception"),
        ("nurse", "nurse"),
    ]

    clinic = models.ForeignKey(
        Clinic, on_delete=models.CASCADE, related_name="users", db_index=True
    )
    username = models.TextField()
    password_hash = models.BinaryField()  # bcrypt; legacy werkzeug migrated on login
    role = models.CharField(max_length=20, choices=ROLES)
    full_name = models.TextField(blank=True, default="")
    medical_license_no = models.TextField(
        blank=True, default="", help_text="شمارهٔ نظام‌پزشکی — gate for clinical modules"
    )
    is_active = models.BooleanField(default=True)
    failed_attempts = models.IntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_login = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "app_user"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "username"], name="uq_app_user_clinic_username"
            )
        ]
        indexes = [models.Index(fields=["clinic", "username"])]

    def __str__(self):
        return f"{self.username}@{self.clinic_id}"


class UserShift(UUIDModel, TimeStampedModel):
    """Manual shift switch (no automatic time boundaries) — preserved from
    webapp.user_active_shift. A night shift can cross midnight, so activity is
    attributed by explicit work_date/shift, not the calendar date."""

    SHIFTS = [("morning", "morning"), ("evening", "evening"), ("night", "night")]

    clinic = models.ForeignKey(
        Clinic, on_delete=models.CASCADE, related_name="shifts", db_index=True
    )
    user = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="shifts")
    shift = models.CharField(max_length=10, choices=SHIFTS)
    work_date = models.DateField()
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "user_shift"
        indexes = [models.Index(fields=["clinic", "work_date", "shift"])]

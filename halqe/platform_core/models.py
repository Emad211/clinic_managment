"""
platform_core models — managed=False (schema owned by SQL slices).

Only Tenant is defined here to satisfy ForeignKey references from
accounting.Patient and clinical.PatientLink.
"""
from django.db import models


class Tenant(models.Model):
    """
    platform.tenants — top-level multi-tenancy unit.
    Default tenant id=1 seeded by slice0.
    """

    name = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        app_label = "platform_core"
        db_table = '"platform"."tenants"'
        ordering = ["id"]

    def __str__(self):
        return self.name

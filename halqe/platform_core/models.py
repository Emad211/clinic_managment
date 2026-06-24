"""
platform_core models — managed=False (schema owned by SQL slices).

Tables: platform.tenants, platform.users.
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


class User(models.Model):
    """
    platform.users — unified user table for all apps.

    password_hash: bcrypt hash stored as BYTEA (BinaryField).
    api_token_hash / api_token_prefix: PAT-style token (SECU-05).
    locked_until: None = not locked; set to future time after 5 bad attempts.

    This model is managed=False — the SQL slices own the DDL.
    Auth is handled by AuthService (platform_core.auth_service), not
    Django's contrib.auth machinery (which is not installed).
    """

    tenant_id = models.BigIntegerField(default=1)
    username = models.TextField()
    # bcrypt hash — BinaryField maps to BYTEA; do NOT decode to str
    password_hash = models.BinaryField()
    role = models.TextField(default="staff")
    app = models.TextField(default="platform")
    full_name = models.TextField(null=True, blank=True)
    staff_id = models.BigIntegerField(null=True, blank=True)
    api_token_hash = models.BinaryField(null=True, blank=True)
    api_token_prefix = models.TextField(null=True, blank=True)
    api_token_expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    failed_attempts = models.IntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        app_label = "platform_core"
        db_table = '"platform"."users"'
        # unique_together would need migration; constraint is in SQL slice
        ordering = ["id"]

    def __str__(self):
        return f"User({self.username}, role={self.role})"

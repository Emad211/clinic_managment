"""Base abstract models shared across all modules.

Design rules (see docs/DATA_MODEL.md §1):
- UUID primary keys everywhere (multi-tenant safe, no cross-tenant enumeration).
- ``clinic`` FK + RLS on every domain table; ``clinic`` is the leading column in
  composite indexes.
- ``timestamptz`` (USE_TZ=True, stored UTC); Jalali/Tehran rendering in the app layer.
- Money is BIGINT (Rial), never float.
"""

import uuid

from django.db import models


class UUIDModel(models.Model):
    """Primary key as UUID v4 instead of auto-increment integer."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantModel(UUIDModel, TimeStampedModel):
    """A tenant-owned row. Every operational table inherits this.

    ``clinic`` is NOT NULL and is enforced at the row level by PostgreSQL RLS
    (see apps/common/migrations RunSQL + apps/common/middleware.TenantMiddleware).
    """

    clinic = models.ForeignKey(
        "identity.Clinic",
        on_delete=models.CASCADE,
        related_name="+",
        db_index=True,
    )

    class Meta:
        abstract = True


class ActivityLog(UUIDModel, TimeStampedModel):
    """Append-only, per-tenant audit trail of state-changing actions (REGULATORY
    §6 — accountability / ممیزی). Mirrors the Flask apps' ``activity_logs`` table.

    Concrete (not abstract) and tenant-owned, but it does NOT inherit TenantModel
    because the actor FK + denormalised snapshot are specific to auditing. RLS is
    applied to ``activity_log`` in apps/common/migrations. Rows are never updated
    or deleted in normal operation — the audit value is its immutability.
    """

    clinic = models.ForeignKey(
        "identity.Clinic", on_delete=models.CASCADE, related_name="+", db_index=True
    )
    actor = models.ForeignKey(
        "identity.AppUser", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    # denormalised so the trail survives the actor account being removed/renamed
    actor_username = models.TextField(blank=True, default="")
    action = models.TextField(help_text="stable machine key, e.g. 'suggestion.acknowledge'")
    summary = models.TextField(blank=True, default="")
    entity_type = models.TextField(blank=True, default="")
    entity_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "activity_log"
        indexes = [
            models.Index(fields=["clinic", "-created_at"]),
            models.Index(fields=["clinic", "action"]),
        ]

    def __str__(self):
        return f"{self.action} by {self.actor_username or '?'}"


class CatalogModel(UUIDModel, TimeStampedModel):
    """A global-with-override catalog row (clinical_indicator, clinical_rule,
    flag_catalog, drug_class, condition ...).

    ``clinic`` NULL  -> global default (seeded on startup, like clinical_rules_seed).
    ``clinic`` set    -> a single clinic's override/customisation.
    RLS policy on these tables allows ``clinic_id IS NULL OR clinic_id = <tenant>``.
    """

    clinic = models.ForeignKey(
        "identity.Clinic",
        on_delete=models.CASCADE,
        related_name="+",
        null=True,
        blank=True,
        db_index=True,
    )

    class Meta:
        abstract = True

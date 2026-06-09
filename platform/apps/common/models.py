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

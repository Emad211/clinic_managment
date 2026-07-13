"""Seed the tenant-owned patient-record catalogs from specialist_clinic defaults."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from clinical.record_catalog_defaults import (
    CONDITION_LAB_TESTS,
    DRUG_CATALOG,
    DRUG_CLASSES,
    FLAG_CATALOG,
    LAB_TESTS,
)
from clinical.record_models import DrugCatalog, DrugClass, FlagCatalog, LabTestCatalog
from platform_core.tenant_context import set_tenant_guc


class Command(BaseCommand):
    help = (
        "Idempotently seed flag, drug, and lab catalogs for one tenant. "
        "Existing manager-edited rows are never overwritten."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, default=1)

    @transaction.atomic
    def handle(self, *args, **options):
        tenant_id = int(options["tenant_id"])
        if tenant_id <= 0:
            raise CommandError("--tenant-id must be a positive integer")

        set_tenant_guc(tenant_id)
        created = {"flags": 0, "classes": 0, "labs": 0, "drugs": 0, "mappings": 0}

        for (
            flag_key,
            label,
            flag_type,
            option_text,
            category,
            record_section,
            display_order,
        ) in FLAG_CATALOG:
            row, was_created = FlagCatalog.objects.get_or_create(
                tenant_id=tenant_id,
                flag_key=flag_key,
                defaults={
                    "label": label,
                    "flag_type": flag_type,
                    "options": option_text,
                    "category": category,
                    "record_section": record_section,
                    "display_order": display_order,
                    "is_active": True,
                },
            )
            if was_created:
                created["flags"] += 1
            elif row.record_section is None:
                row.record_section = record_section
                row.save(update_fields=["record_section"])

        for class_key, label, glucose_lowering, display_order in DRUG_CLASSES:
            _row, was_created = DrugClass.objects.get_or_create(
                tenant_id=tenant_id,
                class_key=class_key,
                defaults={
                    "label": label,
                    "glucose_lowering": glucose_lowering,
                    "display_order": display_order,
                    "is_active": True,
                },
            )
            created["classes"] += int(was_created)

        for test_key, name_fa, unit, ref_low, ref_high, category, display_order in LAB_TESTS:
            _row, was_created = LabTestCatalog.objects.get_or_create(
                tenant_id=tenant_id,
                test_key=test_key,
                defaults={
                    "name_fa": name_fa,
                    "unit": unit,
                    "ref_low": ref_low,
                    "ref_high": ref_high,
                    "category": category,
                    "display_order": display_order,
                    "is_active": True,
                },
            )
            created["labs"] += int(was_created)

        with connection.cursor() as cursor:
            for condition_code, test_keys in CONDITION_LAB_TESTS.items():
                for position, test_key in enumerate(test_keys, start=1):
                    cursor.execute(
                        """
                        INSERT INTO clinical.condition_lab_tests
                            (tenant_id, condition_code, lab_test_key, display_order)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (tenant_id, condition_code, lab_test_key)
                        DO NOTHING
                        """,
                        [tenant_id, condition_code, test_key, position * 10],
                    )
                    created["mappings"] += int(cursor.rowcount == 1)

        for generic_fa, class_key, doses in DRUG_CATALOG:
            _row, was_created = DrugCatalog.objects.get_or_create(
                tenant_id=tenant_id,
                generic_fa=generic_fa,
                defaults={
                    "drug_class_key": class_key,
                    "standard_doses": json.dumps(doses, ensure_ascii=False),
                    "is_active": True,
                },
            )
            created["drugs"] += int(was_created)

        self.stdout.write(
            self.style.SUCCESS(
                "record catalogs ready for tenant "
                f"{tenant_id}: "
                + ", ".join(f"{key}={value}" for key, value in created.items())
            )
        )

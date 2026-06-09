"""Enable PostgreSQL Row-Level Security on every tenant-owned table.

This is the enforcement half of docs/DATA_MODEL.md §3. The middleware sets the
``app.current_clinic`` GUC per request; these policies make the database itself
reject any row that doesn't match — deny-by-default when the GUC is unset.

No-op on non-PostgreSQL backends (the SQL is Postgres-specific). The DB role the
app connects with MUST NOT have BYPASSRLS.
"""

from django.db import migrations

# clinic_id NOT NULL — a tenant sees/writes only its own rows.
TENANT_TABLES = [
    "app_user",
    "user_shift",
    "patient",
    "patient_condition",
    "patient_medication",
    "medication_event",
    "allergy",
    "vital_reading",
    "lab_result",
    "appointment",
    "care_protocol",
    "followup_task",
    "patient_flag",
    "suggestion_log",
    "wallet_transaction",
]

# clinic_id NULLABLE — global catalog rows (clinic_id NULL) are readable by all
# tenants; a tenant may only write its OWN overrides (never global rows).
CATALOG_TABLES = [
    "drug_class",
    "condition",
    "clinical_indicator",
    "clinical_rule",
    "flag_catalog",
]

_TENANT_PRED = "clinic_id = current_setting('app.current_clinic', true)::uuid"
_CATALOG_USING = (
    "clinic_id IS NULL OR clinic_id = current_setting('app.current_clinic', true)::uuid"
)


def _policy_statements(table, using_pred, check_pred):
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
        f"DROP POLICY IF EXISTS tenant_isolation ON {table};",
        (
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({using_pred}) WITH CHECK ({check_pred});"
        ),
    ]


def apply_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        for table in TENANT_TABLES:
            for stmt in _policy_statements(table, _TENANT_PRED, _TENANT_PRED):
                cur.execute(stmt)
        for table in CATALOG_TABLES:
            # read globals + own; write only own (non-null clinic_id)
            for stmt in _policy_statements(table, _CATALOG_USING, _TENANT_PRED):
                cur.execute(stmt)


def drop_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        for table in TENANT_TABLES + CATALOG_TABLES:
            cur.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
            cur.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0001_initial"),
        ("patients", "0001_initial"),
        ("chronic", "0001_initial"),
    ]

    operations = [migrations.RunPython(apply_rls, drop_rls)]

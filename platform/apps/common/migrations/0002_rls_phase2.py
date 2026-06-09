"""Extend Row-Level Security to the billing / rx / accounting / messaging tenant
tables (docs/DATA_MODEL.md §3). Same deny-by-default policy as 0001_rls.

``plan`` and ``drug`` are intentionally excluded: they are platform-level global
reference tables (no clinic_id), readable by every tenant and written only by
platform admins. No-op on non-PostgreSQL backends.
"""

from django.db import migrations

NEW_TENANT_TABLES = [
    # billing
    "subscription",
    "payment",
    # rx
    "prescription",
    "prescription_item",
    "insurer_log",
    # accounting
    "tariff",
    "invoice",
    "visit",
    "visit_item",
    "injection",
    "procedure",
    "consumable_ledger",
    "invoice_item_payment",
    "payroll_setting",
    # messaging
    "sms_template",
    "sms_campaign",
    "sms_message",
]

_PRED = "clinic_id = current_setting('app.current_clinic', true)::uuid"


def _policy_statements(table):
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
        f"DROP POLICY IF EXISTS tenant_isolation ON {table};",
        (
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_PRED}) WITH CHECK ({_PRED});"
        ),
    ]


def apply_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        for table in NEW_TENANT_TABLES:
            for stmt in _policy_statements(table):
                cur.execute(stmt)


def drop_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        for table in NEW_TENANT_TABLES:
            cur.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
            cur.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0001_rls"),
        ("billing", "0001_initial"),
        ("rx", "0001_initial"),
        ("accounting", "0001_initial"),
        ("messaging", "0001_initial"),
    ]

    operations = [migrations.RunPython(apply_rls, drop_rls)]

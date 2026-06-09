"""Apply Row-Level Security to the ``activity_log`` audit table (same deny-by-
default tenant policy as 0001/0002). The audit trail is per-tenant: a clinic may
read and append only its own activity. No-op on non-PostgreSQL backends.
"""

from django.db import migrations

_PRED = "clinic_id = nullif(current_setting('app.current_clinic', true), '')::uuid"


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
        for stmt in _policy_statements("activity_log"):
            cur.execute(stmt)


def drop_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute("DROP POLICY IF EXISTS tenant_isolation ON activity_log;")
        cur.execute("ALTER TABLE activity_log DISABLE ROW LEVEL SECURITY;")


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0003_activitylog"),
    ]

    operations = [migrations.RunPython(apply_rls, drop_rls)]

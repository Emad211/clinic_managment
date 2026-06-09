"""Apply Row-Level Security to the new ``insurance_plan`` tenant table (same
deny-by-default policy as the other tenant tables). No-op off PostgreSQL."""

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
        for stmt in _policy_statements("insurance_plan"):
            cur.execute(stmt)


def drop_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute("DROP POLICY IF EXISTS tenant_isolation ON insurance_plan;")
        cur.execute("ALTER TABLE insurance_plan DISABLE ROW LEVEL SECURITY;")


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0004_activitylog_rls"),
        ("accounting", "0002_tariff_category_insuranceplan"),
    ]

    operations = [migrations.RunPython(apply_rls, drop_rls)]

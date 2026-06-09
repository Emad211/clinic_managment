"""Prove PostgreSQL Row-Level Security actually isolates tenants.

    python manage.py verify_rls

This is the CI-grade check for the multi-tenancy backbone (docs/DATA_MODEL.md §3).
It is a NO-OP (skipped) on non-PostgreSQL backends. On PostgreSQL it:
  1. creates a NON-superuser, NON-BYPASSRLS role `rls_app` (RLS only truly applies
     to such a role — superusers always bypass it),
  2. seeds two throwaway clinics A and B each with a patient (as the migration
     superuser, which bypasses RLS for setup),
  3. under SET ROLE rls_app, asserts:
       - deny-by-default: no tenant GUC  -> 0 rows
       - isolation: GUC=A -> only A's rows ; GUC=B -> only B's rows
       - cross-tenant write is rejected by the WITH CHECK policy
  4. cleans up the throwaway rows.

Run this against the real production Postgres before launch. Exit code is non-zero
if any assertion fails.
"""

import sys

from django.core.management.base import BaseCommand
from django.db import connection

from apps.identity.models import Clinic
from apps.patients.models import Patient


class Command(BaseCommand):
    help = "Prove PostgreSQL RLS isolates tenants (deny-by-default + cross-tenant)."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write(self.style.WARNING(
                f"verify_rls skipped: backend is '{connection.vendor}', not postgresql. "
                "RLS only exists on PostgreSQL."
            ))
            return

        failures = []

        def check(label, cond):
            mark = "PASS" if cond else "FAIL"
            self.stdout.write(f"{mark} {label}")
            if not cond:
                failures.append(label)

        # --- setup as superuser (bypasses RLS) ---
        clinic_a = Clinic.objects.create(name="RLS-A", slug="rls-test-a", status="active")
        clinic_b = Clinic.objects.create(name="RLS-B", slug="rls-test-b", status="active")
        Patient.objects.create(clinic=clinic_a, national_id="RLSA1", last_name="A1")
        Patient.objects.create(clinic=clinic_a, national_id="RLSA2", last_name="A2")
        Patient.objects.create(clinic=clinic_b, national_id="RLSB1", last_name="B1")

        try:
            with connection.cursor() as cur:
                cur.execute(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='rls_app') "
                    "THEN CREATE ROLE rls_app NOSUPERUSER NOBYPASSRLS; END IF; END $$;"
                )
                cur.execute("GRANT USAGE ON SCHEMA public TO rls_app;")
                cur.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO rls_app;")

            def set_ctx(val):
                with connection.cursor() as cur:
                    cur.execute("SELECT set_config('app.current_clinic', %s, false);", [val])

            def count_as_app():
                with connection.cursor() as cur:
                    cur.execute("SET ROLE rls_app;")
                    cur.execute("SELECT count(*) FROM patient;")
                    n = cur.fetchone()[0]
                    cur.execute("RESET ROLE;")
                    return n

            # deny-by-default: unset GUC -> 0 rows
            set_ctx(None)
            check("deny-by-default, GUC unset -> 0 rows", count_as_app() == 0)
            # and empty-string GUC must also be safe (regression: '' must not crash)
            set_ctx("")
            check("deny-by-default, GUC empty '' -> 0 rows", count_as_app() == 0)

            # isolation: A sees only A's 2, B sees only B's 1
            set_ctx(str(clinic_a.id))
            check("tenant A sees only A's rows (2)", count_as_app() == 2)
            set_ctx(str(clinic_b.id))
            check("tenant B sees only B's rows (1)", count_as_app() == 1)

            # cross-tenant write blocked: as A, insert a row tagged clinic B
            set_ctx(str(clinic_a.id))
            blocked = False
            with connection.cursor() as cur:
                cur.execute("SET ROLE rls_app;")
                try:
                    cur.execute(
                        "INSERT INTO patient (id, clinic_id, first_name, last_name, "
                        "phone_number, gender, address, insurance_type, "
                        "is_foreign, wallet_balance, is_active, notes, created_at, updated_at) "
                        "VALUES (gen_random_uuid(), %s, '', 'X', '', '', '', '', "
                        "false, 0, true, '', now(), now());",
                        [str(clinic_b.id)],
                    )
                except Exception:
                    blocked = True
                finally:
                    try:
                        cur.execute("RESET ROLE;")
                    except Exception:
                        connection.rollback()
                        with connection.cursor() as c2:
                            c2.execute("RESET ROLE;")
            check("cross-tenant write rejected (WITH CHECK)", blocked)

        finally:
            # cleanup (as superuser)
            with connection.cursor() as cur:
                cur.execute("RESET ROLE;")
            Patient.objects.filter(clinic__in=[clinic_a, clinic_b]).delete()
            Clinic.objects.filter(id__in=[clinic_a.id, clinic_b.id]).delete()

        if failures:
            self.stdout.write(self.style.ERROR(f"verify_rls FAILED: {failures}"))
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS("verify_rls: RLS isolation holds (all checks passed)."))

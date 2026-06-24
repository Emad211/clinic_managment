"""
Management command: apply_schema

Applies the 7 SQL slice files in sorted order to the configured database.
Reads slices from settings.SCHEMA_SLICE_DIR (defaults to
../specialist_clinic/docs/migration_tools/).

Usage:
  python manage.py apply_schema                  # apply to default db
  python manage.py apply_schema --database mydb  # apply to named connection

Each slice is executed inside its own transaction so a failure is isolated.
The slices themselves are idempotent (CREATE IF NOT EXISTS / ON CONFLICT DO
NOTHING), so re-running is safe.

Optionally create a login role for tests:
  python manage.py apply_schema --create-login-role clinical_login --role-password secret
"""
import os
from pathlib import Path

import psycopg
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Apply schema SQL slices (in sorted order) to the configured Postgres DB."

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default="default",
            help="Django database alias to connect to (default: 'default').",
        )
        parser.add_argument(
            "--create-login-role",
            dest="login_role",
            default=None,
            help=(
                "If set, create a login role with this name (inherits clinical_app). "
                "Useful for tests that need a real login role."
            ),
        )
        parser.add_argument(
            "--role-password",
            dest="role_password",
            default="test_password",
            help="Password for the --create-login-role role.",
        )

    def handle(self, *args, **options):
        db_alias = options["database"]
        db_conf = settings.DATABASES.get(db_alias)
        if db_conf is None:
            raise CommandError(f"Unknown database alias: '{db_alias}'")

        slice_dir = Path(settings.SCHEMA_SLICE_DIR)
        if not slice_dir.is_dir():
            raise CommandError(
                f"SCHEMA_SLICE_DIR does not exist: {slice_dir}\n"
                "Set settings.SCHEMA_SLICE_DIR or the SCHEMA_SLICE_DIR env var."
            )

        # Collect slice files — sorted alphabetically (slice0, slice2, slice2b, …)
        slice_files = sorted(slice_dir.glob("schema_pg_slice*.sql"))
        if not slice_files:
            raise CommandError(f"No schema_pg_slice*.sql files found in {slice_dir}")

        self.stdout.write(
            self.style.NOTICE(
                f"Applying {len(slice_files)} slice(s) from {slice_dir} "
                f"to database '{db_alias}' ({db_conf['NAME']})…"
            )
        )

        # Build psycopg connection string from Django DB config
        conninfo = _build_conninfo(db_conf)

        with psycopg.connect(conninfo, autocommit=True) as conn:
            for slice_path in slice_files:
                self.stdout.write(f"  → {slice_path.name}")
                sql = slice_path.read_text(encoding="utf-8")
                try:
                    # Execute entire file; autocommit=True so DO blocks work.
                    conn.execute(sql)
                except Exception as exc:
                    raise CommandError(
                        f"Error applying {slice_path.name}: {exc}"
                    ) from exc
                self.stdout.write(self.style.SUCCESS(f"     OK"))

            # Optionally create a login role for test use
            login_role = options.get("login_role")
            if login_role:
                password = options["role_password"]
                self.stdout.write(
                    f"  → creating login role '{login_role}' (inherits clinical_app)…"
                )
                try:
                    conn.execute(
                        f"""
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM pg_roles WHERE rolname = '{login_role}'
                            ) THEN
                                CREATE ROLE {login_role} LOGIN PASSWORD '{password}'
                                    IN ROLE clinical_app;
                            END IF;
                        END$$;
                        """
                    )
                    self.stdout.write(self.style.SUCCESS(f"     OK"))
                except Exception as exc:
                    raise CommandError(
                        f"Failed to create login role '{login_role}': {exc}"
                    ) from exc

        self.stdout.write(self.style.SUCCESS("Schema applied successfully."))


def _build_conninfo(db_conf: dict) -> str:
    """Convert a Django DATABASES entry to a psycopg conninfo string."""
    parts = []
    mapping = {
        "NAME": "dbname",
        "USER": "user",
        "PASSWORD": "password",
        "HOST": "host",
        "PORT": "port",
    }
    for django_key, pg_key in mapping.items():
        value = db_conf.get(django_key)
        if value:
            # Escape single quotes in values
            escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
            parts.append(f"{pg_key}='{escaped}'")
    return " ".join(parts)

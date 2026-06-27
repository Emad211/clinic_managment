"""
Management command: apply_schema

Applies all `schema_pg_slice*.sql` files (in numeric-sorted order) to the
configured database. Reads slices from settings.SCHEMA_SLICE_DIR (defaults to
halqe/db/schema/).

After applying every slice it records each applied file (filename + sha256
checksum) into a small bookkeeping table `platform.schema_version` — the
command's OWN ledger (created/populated here, not by any slice). The table is
created after the slice loop because the `platform` schema only exists once
slice0 has run. Re-running is idempotent: the ledger is UPSERTed (checksum +
applied_at refreshed), never duplicated.

Usage:
  python manage.py apply_schema                  # apply to default db
  python manage.py apply_schema --database mydb  # apply to named connection

Each slice is executed inside its own transaction so a failure is isolated.
The slices themselves are idempotent (CREATE IF NOT EXISTS / ON CONFLICT DO
NOTHING), so re-running is safe.

Optionally create a login role for tests:
  python manage.py apply_schema --create-login-role clinical_login --role-password secret
"""
import hashlib
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

        # Collect slice files in NUMERIC-aware order (slice2 before slice10).
        # Plain string sort would put "slice10" before "slice2" ('1' < '2'),
        # which breaks ordering-dependent grants/revokes. Key = (major, suffix).
        def _slice_order(p):
            import re
            m = re.search(r"schema_pg_slice(\d+)([a-z]*)", p.name)
            return (int(m.group(1)), m.group(2)) if m else (9999, p.name)

        slice_files = sorted(slice_dir.glob("schema_pg_slice*.sql"), key=_slice_order)
        if not slice_files:
            raise CommandError(f"No schema_pg_slice*.sql files found in {slice_dir}")

        self.stdout.write(
            self.style.NOTICE(
                f"Applying {len(slice_files)} slice(s) from {slice_dir} "
                f"to database '{db_alias}' ({db_conf['NAME']})…"
            )
        )

        # apply_schema needs SUPERUSER (DDL, GRANT, CREATE ROLE).
        # Django's DATABASES entries now use the least-privilege app role, so we
        # override USER/PASSWORD with PG_USER/PG_PASSWORD (superuser env vars).
        su_conf = dict(db_conf)
        su_user = os.environ.get("PG_USER")
        su_pw   = os.environ.get("PG_PASSWORD")
        if su_user:
            su_conf["USER"] = su_user
        if su_pw:
            su_conf["PASSWORD"] = su_pw
        conninfo = _build_conninfo(su_conf)

        self.stdout.write(
            self.style.NOTICE(
                f"  Connecting as user '{su_conf.get('USER', '?')}' "
                f"(set PG_USER/PG_PASSWORD for superuser access)"
            )
        )

        # (filename, sha256-checksum) for each slice applied this run → ledger.
        applied_slices: list[tuple[str, str]] = []

        with psycopg.connect(conninfo, autocommit=True) as conn:
            for slice_path in slice_files:
                self.stdout.write(f"  → {slice_path.name}")
                sql_bytes = slice_path.read_bytes()
                sql = sql_bytes.decode("utf-8")
                try:
                    # Execute entire file; autocommit=True so DO blocks work.
                    conn.execute(sql)
                except Exception as exc:
                    raise CommandError(
                        f"Error applying {slice_path.name}: {exc}"
                    ) from exc
                checksum = hashlib.sha256(sql_bytes).hexdigest()
                applied_slices.append((slice_path.name, checksum))
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
                                    IN ROLE platform_app;
                            END IF;
                        END$$;
                        """
                    )
                    conn.execute(f"ALTER ROLE {login_role} PASSWORD '{password}'")
                    conn.execute(f"GRANT platform_app TO {login_role}")
                    self.stdout.write(self.style.SUCCESS(f"     OK"))
                except Exception as exc:
                    raise CommandError(
                        f"Failed to create login role '{login_role}': {exc}"
                    ) from exc

            # ────────────────────────────────────────────────────────────────
            # Schema-version LEDGER (apply_schema's OWN bookkeeping).
            #
            # Created HERE, after the slice loop, because the `platform` schema
            # only exists once slice0 has been applied (a fresh DB has none).
            # This is NOT a slice — it is the command's record of which slice
            # files were applied this run, with a sha256 of each file's bytes.
            # Idempotent: UPSERT keyed on filename refreshes checksum+applied_at,
            # so re-running never errors or duplicates rows.
            #
            # Only the superuser (this command) writes it; app roles get SELECT
            # so a future /readyz or version endpoint can read it under the app
            # role. clinical_app may or may not exist → guard like other slices.
            # ────────────────────────────────────────────────────────────────
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS platform.schema_version (
                        filename   TEXT PRIMARY KEY,
                        checksum   TEXT NOT NULL,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                conn.execute(
                    "GRANT SELECT ON platform.schema_version TO platform_app"
                )
                # clinical_app may not exist — grant only if the role is present.
                conn.execute(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM pg_roles WHERE rolname = 'clinical_app'
                        ) THEN
                            GRANT SELECT ON platform.schema_version TO clinical_app;
                        END IF;
                    END$$;
                    """
                )
                for filename, checksum in applied_slices:
                    conn.execute(
                        """
                        INSERT INTO platform.schema_version (filename, checksum)
                        VALUES (%s, %s)
                        ON CONFLICT (filename) DO UPDATE
                            SET checksum   = EXCLUDED.checksum,
                                applied_at = now()
                        """,
                        (filename, checksum),
                    )
            except Exception as exc:
                raise CommandError(
                    f"Failed to update platform.schema_version ledger: {exc}"
                ) from exc

            self.stdout.write(
                self.style.SUCCESS(
                    f"  ledger: recorded {len(applied_slices)} slice(s) "
                    f"in platform.schema_version"
                )
            )

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

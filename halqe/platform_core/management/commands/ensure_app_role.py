"""
Management command: ensure_app_role

Creates the least-privilege app LOGIN role idempotently.
The role is a MEMBER of platform_app (inherits all platform_app GRANTs):
  - WRITE on platform.* + clinical.*
  - SELECT-only on accounting.*  (the physical DB-level read-only boundary)

Must be run as a Postgres superuser (uses PG_USER/PG_PASSWORD from settings
for the psycopg connection — the Django app connection is the least-privilege
role itself, so we cannot create roles through it).

Usage:
  # Using env vars (recommended):
  PG_USER=postgres PG_PASSWORD=... \\
  PG_APP_USER=platform_app_login PG_APP_PASSWORD=<strong-pw> \\
      python manage.py ensure_app_role

  # Or with explicit args:
  python manage.py ensure_app_role \\
      --login-role platform_app_login \\
      --login-password <strong-pw>

Re-running is always safe (idempotent).  This command does NOT modify the
platform_app NOLOGIN role itself — only creates/updates the LOGIN role that
inherits from it.
"""
import os

import psycopg
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Create (or update) the least-privilege app LOGIN role for halqe. "
        "The role inherits from platform_app (WRITE clinical+platform, "
        "SELECT-only accounting). Idempotent — safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--login-role",
            dest="login_role",
            default=None,
            help=(
                "Name for the LOGIN role. "
                "Defaults to PG_APP_USER env var, or 'platform_app_login'."
            ),
        )
        parser.add_argument(
            "--login-password",
            dest="login_password",
            default=None,
            help=(
                "Password for the LOGIN role. "
                "Defaults to PG_APP_PASSWORD env var."
            ),
        )
        parser.add_argument(
            "--database",
            default="default",
            help="Django database alias used to extract host/port/dbname (default: 'default').",
        )

    def handle(self, *args, **options):
        db_alias   = options["database"]
        login_role = (
            options["login_role"]
            or os.environ.get("PG_APP_USER", "platform_app_login")
        )
        login_pw = (
            options["login_password"]
            or os.environ.get("PG_APP_PASSWORD")
        )
        if not login_pw:
            raise CommandError(
                "No login password supplied. "
                "Pass --login-password or set PG_APP_PASSWORD env var."
            )

        db_conf = settings.DATABASES.get(db_alias)
        if db_conf is None:
            raise CommandError(f"Unknown database alias: '{db_alias}'")

        # Build superuser conninfo from PG_USER/PG_PASSWORD (env).
        # The Django app connections already use the least-privilege role, so
        # we MUST connect as superuser to CREATE/ALTER roles.
        su_user = os.environ.get("PG_USER", "postgres")
        su_pw   = os.environ.get("PG_PASSWORD", "")
        host    = db_conf.get("HOST", "localhost")
        port    = db_conf.get("PORT", "5432")
        dbname  = db_conf.get("NAME", "halqe")

        # Escape single quotes (defensive)
        def _esc(s):
            return str(s).replace("'", "\\'")

        su_conninfo = (
            f"host='{_esc(host)}' port='{_esc(port)}' "
            f"user='{_esc(su_user)}' password='{_esc(su_pw)}' "
            f"dbname='{_esc(dbname)}'"
        )

        self.stdout.write(
            self.style.NOTICE(
                f"Connecting as superuser ({su_user}) to create/update "
                f"app LOGIN role '{login_role}' …"
            )
        )

        try:
            with psycopg.connect(su_conninfo, autocommit=True) as conn:
                # Idempotent: create only if not exists
                conn.execute(f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_roles WHERE rolname = '{_esc(login_role)}'
                        ) THEN
                            CREATE ROLE {login_role} LOGIN
                                PASSWORD '{_esc(login_pw)}'
                                IN ROLE platform_app;
                            RAISE NOTICE 'Role % created.', '{login_role}';
                        ELSE
                            RAISE NOTICE 'Role % already exists — updating password.', '{login_role}';
                        END IF;
                    END$$;
                """)

                # Always refresh the password and ensure platform_app membership.
                # ALTER ROLE is idempotent for password reset.
                conn.execute(
                    f"ALTER ROLE {login_role} PASSWORD '{_esc(login_pw)}'"
                )
                conn.execute(
                    f"GRANT platform_app TO {login_role}"
                )

                # Grant CONNECT on the current DB (object-level privilege).
                conn.execute(
                    f"GRANT CONNECT ON DATABASE {dbname} TO {login_role}"
                )

                # Verify membership
                row = conn.execute(f"""
                    SELECT r.rolname, m.member::regrole
                    FROM pg_roles r
                    JOIN pg_auth_members m ON r.oid = m.roleid
                    WHERE r.rolname = 'platform_app'
                      AND m.member::regrole::text = '{login_role}'
                """).fetchone()

                if row:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Role '{login_role}' is a LOGIN member of platform_app."
                        )
                    )
                else:
                    raise CommandError(
                        f"Role '{login_role}' was not granted platform_app — "
                        "check Postgres logs."
                    )

        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"Failed to create/update role: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. App role '{login_role}' is ready.\n"
                f"Set env vars:\n"
                f"  PG_APP_USER={login_role}\n"
                f"  PG_APP_PASSWORD=<your-password>\n"
                f"Django will use this role for all ORM connections."
            )
        )

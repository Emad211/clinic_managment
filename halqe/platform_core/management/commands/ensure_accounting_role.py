"""Create/update the dedicated accounting LOGIN role.

The schema slices create ``accounting_app`` as a NOLOGIN role with write access
only to ``accounting.*``. This command creates the runtime LOGIN identity that
inherits exactly that role and strips any stale privilege/membership left by an
older local setup.
"""
from __future__ import annotations

import os

import psycopg
from psycopg import sql
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


_DEFAULT_ACCOUNTING_PASSWORD = "accounting_change_me"


class Command(BaseCommand):
    help = (
        "Create or hard-reset the dedicated accounting LOGIN role. "
        "The role inherits only accounting_app."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--login-role",
            default=None,
            help=(
                "LOGIN role name. Defaults to PG_ACCOUNTING_USER or "
                "'accounting_app_login'."
            ),
        )
        parser.add_argument(
            "--login-password",
            default=None,
            help=(
                "Role password. Defaults to PG_ACCOUNTING_PASSWORD, then "
                "PG_APP_PASSWORD for backwards-compatible dev rollout."
            ),
        )
        parser.add_argument(
            "--database",
            default="default",
            help="Django database alias used for host/port/dbname.",
        )

    def handle(self, *args, **options):
        role = (
            options["login_role"]
            or os.environ.get("PG_ACCOUNTING_USER")
            or "accounting_app_login"
        ).strip()
        explicit_password = (
            options["login_password"]
            or os.environ.get("PG_ACCOUNTING_PASSWORD")
            or ""
        ).strip()
        password = (
            explicit_password
            if settings.PRODUCTION
            else explicit_password or os.environ.get("PG_APP_PASSWORD") or ""
        )
        if not role:
            raise CommandError("Accounting LOGIN role name must not be empty.")
        if not password:
            raise CommandError(
                "Set PG_ACCOUNTING_PASSWORD (preferred) or PG_APP_PASSWORD."
            )
        if settings.PRODUCTION and (
            not os.environ.get("PG_ACCOUNTING_PASSWORD")
            or password == _DEFAULT_ACCOUNTING_PASSWORD
        ):
            raise CommandError(
                "PRODUCTION requires a strong, explicit PG_ACCOUNTING_PASSWORD "
                "different from the documented placeholder."
            )

        db_alias = options["database"]
        db = settings.DATABASES.get(db_alias)
        if db is None:
            raise CommandError(f"Unknown database alias: {db_alias!r}")

        su_user = os.environ.get("PG_USER", "postgres")
        su_password = os.environ.get("PG_PASSWORD", "")
        conninfo = psycopg.conninfo.make_conninfo(
            host=db.get("HOST") or "localhost",
            port=int(db.get("PORT") or 5432),
            dbname=db.get("NAME"),
            user=su_user,
            password=su_password,
            connect_timeout=5,
        )

        try:
            with psycopg.connect(conninfo, autocommit=True) as conn:
                exists = conn.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = %s",
                    (role,),
                ).fetchone()
                if not exists:
                    conn.execute(
                        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                            sql.Identifier(role), sql.Literal(password)
                        )
                    )

                # Reset dangerous cluster flags even when the role pre-existed.
                conn.execute(
                    sql.SQL(
                        "ALTER ROLE {} WITH LOGIN INHERIT NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(password))
                )

                # Exact-membership contract: remove every inherited role except
                # accounting_app, then grant the one intended parent.
                memberships = conn.execute(
                    """
                    SELECT parent.rolname
                    FROM pg_auth_members m
                    JOIN pg_roles parent ON parent.oid = m.roleid
                    JOIN pg_roles child  ON child.oid  = m.member
                    WHERE child.rolname = %s
                    """,
                    (role,),
                ).fetchall()
                for (parent_role,) in memberships:
                    if parent_role != "accounting_app":
                        conn.execute(
                            sql.SQL("REVOKE {} FROM {}").format(
                                sql.Identifier(parent_role),
                                sql.Identifier(role),
                            )
                        )
                conn.execute(
                    sql.SQL("GRANT accounting_app TO {}").format(
                        sql.Identifier(role)
                    )
                )

                # Remove any direct grants accidentally left on this LOGIN role.
                # Intended access is inherited from accounting_app only.
                for schema_name in ("clinical", "platform"):
                    conn.execute(
                        sql.SQL("REVOKE ALL PRIVILEGES ON SCHEMA {} FROM {}").format(
                            sql.Identifier(schema_name), sql.Identifier(role)
                        )
                    )
                    conn.execute(
                        sql.SQL(
                            "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA {} FROM {}"
                        ).format(sql.Identifier(schema_name), sql.Identifier(role))
                    )
                    conn.execute(
                        sql.SQL(
                            "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA {} FROM {}"
                        ).format(sql.Identifier(schema_name), sql.Identifier(role))
                    )

                conn.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(str(db.get("NAME"))),
                        sql.Identifier(role),
                    )
                )

                role_state = conn.execute(
                    """
                    SELECT rolsuper, rolcreatedb, rolcreaterole,
                           rolreplication, rolbypassrls
                    FROM pg_roles WHERE rolname = %s
                    """,
                    (role,),
                ).fetchone()
                if role_state != (False, False, False, False, False):
                    raise CommandError(
                        f"Role {role!r} retained a dangerous cluster privilege."
                    )

                final_memberships = conn.execute(
                    """
                    SELECT parent.rolname
                    FROM pg_auth_members m
                    JOIN pg_roles parent ON parent.oid = m.roleid
                    JOIN pg_roles child  ON child.oid  = m.member
                    WHERE child.rolname = %s
                    ORDER BY parent.rolname
                    """,
                    (role,),
                ).fetchall()
                if [row[0] for row in final_memberships] != ["accounting_app"]:
                    raise CommandError(
                        f"Role {role!r} does not have the exact accounting membership."
                    )
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(
                f"Failed to create/update accounting LOGIN role: {exc}"
            ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Accounting LOGIN role {role!r} is ready "
                "(least-privilege member of accounting_app)."
            )
        )

"""Dedicated write connection for the accounting bounded context.

The normal Django connections run as ``platform_app`` and are intentionally
SELECT-only on ``accounting.*``. Accounting commands therefore use a distinct
LOGIN role that inherits PostgreSQL's ``accounting_app`` NOLOGIN role.

Keeping this connection in one module gives the repository an auditable choke
point: clinical code continues to use :mod:`accounting_port` and cannot gain
write privileges merely because the accounting UI lives in the same process.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from typing import Iterator

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


_DEFAULT_ACCOUNTING_PASSWORD = "accounting_change_me"


def _accounting_credentials() -> tuple[str, str]:
    """Resolve the dedicated accounting LOGIN credentials lazily.

    ``PG_ACCOUNTING_PASSWORD`` temporarily falls back to ``PG_APP_PASSWORD`` in
    development so an existing deployment can introduce the new role without a
    flag-day secret rotation. Production requires a separate explicit secret.
    """
    user = (os.environ.get("PG_ACCOUNTING_USER") or "accounting_app_login").strip()
    explicit_password = (os.environ.get("PG_ACCOUNTING_PASSWORD") or "").strip()
    if settings.PRODUCTION:
        if not explicit_password or explicit_password == _DEFAULT_ACCOUNTING_PASSWORD:
            raise ImproperlyConfigured(
                "PRODUCTION requires a strong, explicit PG_ACCOUNTING_PASSWORD "
                "different from the documented placeholder."
            )
        password = explicit_password
    else:
        password = explicit_password or os.environ.get("PG_APP_PASSWORD") or ""

    if not user:
        raise ImproperlyConfigured("PG_ACCOUNTING_USER must not be empty.")
    if not password:
        raise ImproperlyConfigured(
            "Set PG_ACCOUNTING_PASSWORD (preferred) or PG_APP_PASSWORD before "
            "using accounting write endpoints."
        )
    return user, password


def _connection_kwargs() -> dict:
    """Build psycopg kwargs from the resolved Django database coordinates."""
    db = settings.DATABASES["default"]
    user, password = _accounting_credentials()
    return {
        "host": db.get("HOST") or "localhost",
        "port": int(db.get("PORT") or 5432),
        "dbname": db.get("NAME"),
        "user": user,
        "password": password,
        "connect_timeout": 5,
        "application_name": "halqe-accounting-writer",
        "options": "-c search_path=accounting,platform,public",
        "row_factory": dict_row,
    }


@contextmanager
def accounting_transaction(*, tenant_id: int) -> Iterator[Connection]:
    """Yield a tenant-bound accounting connection in one atomic transaction.

    A fresh connection is deliberately opened per command. This keeps accounting
    privileges out of Django's clinical connection. The tenant GUC is set with
    transaction scope as future-proofing for accounting RLS; every SQL statement
    still carries an explicit ``tenant_id`` predicate today.
    """
    if not isinstance(tenant_id, int) or tenant_id <= 0:
        raise ValueError("tenant_id must be a positive integer")

    conn = psycopg.connect(**_connection_kwargs())
    try:
        conn.execute(
            "SELECT set_config('app.current_tenant', %s, true)",
            (str(tenant_id),),
        )
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

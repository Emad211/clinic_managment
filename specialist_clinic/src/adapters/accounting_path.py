"""Resolve the read-only accounting database path per Flask application instance.

Tests and multi-instance desktop processes must not share a mutable process-global Config
value. The application config is snapshotted at create_app time; command-line usage outside
an app context falls back to Config.
"""
from __future__ import annotations

import os

from flask import current_app, has_app_context

from src.config.settings import Config


def accounting_db_path() -> str:
    environment = str(os.environ.get("ACCOUNTING_DB_PATH") or "").strip()
    if environment:
        return environment
    if has_app_context():
        try:
            from src.adapters.sqlite.system_settings_repo import (
                SystemSettingsRepository,
            )

            saved = str(
                SystemSettingsRepository().get("accounting_db_path", "") or ""
            ).strip()
            if saved:
                return saved
        except Exception:
            # Bootstrap/readiness still has the app-config fallback while the
            # specialist database is unavailable or has not been initialized.
            pass
        value = current_app.config.get("ACCOUNTING_DB_PATH")
        if value:
            return str(value)
    return str(Config.ACCOUNTING_DB_PATH or "")


__all__ = ["accounting_db_path"]

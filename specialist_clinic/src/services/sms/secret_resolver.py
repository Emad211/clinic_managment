"""Resolve SMS credentials without exposing raw keys to templates or logs."""
from __future__ import annotations

import logging
import os
import sqlite3

from flask import current_app, has_app_context

from src.adapters.sqlite.core import get_db


logger = logging.getLogger(__name__)


_SECRET_KEYS = {
    "kavenegar": ("CLINIC_KAVENEGAR_API_KEY", "kavenegar_api_key"),
    "mediana": ("CLINIC_MEDIANA_API_KEY", "mediana_api_key"),
}


def _production() -> bool:
    return bool(
        has_app_context()
        and current_app.config.get("PRODUCTION")
        and not current_app.config.get("TESTING", False)
    )


def get_sms_secret(provider_name: str) -> str:
    normalized = str(provider_name or "").strip().lower()
    if normalized not in _SECRET_KEYS:
        return ""
    env_key, db_key = _SECRET_KEYS[normalized]
    from_env = str(os.getenv(env_key) or "").strip()
    if from_env:
        return from_env
    if _production():
        # Production never falls back to a plaintext SQLite key.
        return ""
    try:
        row = get_db().execute(
            "SELECT value FROM settings WHERE key=?",
            (db_key,),
        ).fetchone()
        return str(row["value"] if row else "").strip()
    except sqlite3.Error:
        # Fail-closed (no key) but surface the real DB fault instead of hiding it.
        logger.exception("SMS secret DB read failed provider=%s", normalized)
        return ""


def configured_sms_providers() -> tuple[str, ...]:
    return tuple(
        provider for provider in ("kavenegar", "mediana")
        if get_sms_secret(provider)
    )


def masked_secret(provider_name: str) -> str:
    value = get_sms_secret(provider_name)
    if not value:
        return ""
    visible = value[-4:] if len(value) >= 4 else value[-1:]
    return "••••••••" + visible


__all__ = [
    "configured_sms_providers",
    "get_sms_secret",
    "masked_secret",
]

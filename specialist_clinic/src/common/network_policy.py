"""Fail-closed network exposure checks for the desktop web server."""
from __future__ import annotations

import ipaddress

from src.common.install_secret import is_strong_secret


def is_loopback_host(host: str) -> bool:
    normalized = (host or "").strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def is_loopback_remote(remote_addr: str | None) -> bool:
    try:
        return ipaddress.ip_address((remote_addr or "").strip()).is_loopback
    except ValueError:
        return False


def validate_server_exposure(
    *,
    host: str,
    secret_key: object,
    setup_complete: bool,
) -> None:
    if not is_strong_secret(secret_key):
        raise RuntimeError("A strong session secret is required before serving.")
    if not is_loopback_host(host) and not setup_complete:
        raise RuntimeError(
            "First-run manager setup must be completed on loopback before "
            "the application can bind to a LAN interface."
        )


__all__ = [
    "is_loopback_host",
    "is_loopback_remote",
    "validate_server_exposure",
]

"""Persistent per-installation session secret for desktop deployments."""
from __future__ import annotations

import os
import secrets
from pathlib import Path


MIN_SECRET_LENGTH = 43


def is_strong_secret(value: object) -> bool:
    return isinstance(value, str) and len(value.strip()) >= MIN_SECRET_LENGTH


def default_secret_path(database_path: str, project_root: str) -> Path:
    if database_path and database_path != ":memory:":
        return Path(database_path).resolve().with_name(
            ".specialist-session-secret"
        )
    return Path(project_root).resolve() / ".specialist-session-secret"


def load_or_create_install_secret(
    *,
    database_path: str,
    project_root: str,
    explicit_path: str | None = None,
) -> str:
    """Load or atomically create a private random secret beside the application DB."""
    path = (
        Path(explicit_path).resolve()
        if explicit_path
        else default_secret_path(database_path, project_root)
    )
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        value = ""
    if value:
        if not is_strong_secret(value):
            raise RuntimeError(
                f"Install secret is invalid or too short: {path}"
            )
        return value

    generated = secrets.token_urlsafe(48)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(str(path), flags, 0o600)
    except FileExistsError:
        value = path.read_text(encoding="utf-8").strip()
        if not is_strong_secret(value):
            raise RuntimeError(
                f"Install secret is invalid or too short: {path}"
            )
        return value

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(generated)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(path, 0o600)
        except OSError:
            # Windows ACLs are inherited from the containing user directory.
            pass
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return generated


__all__ = [
    "MIN_SECRET_LENGTH",
    "default_secret_path",
    "is_strong_secret",
    "load_or_create_install_secret",
]

"""Per-request access to the panel DB and the clock (shared by api/ modules)."""
from __future__ import annotations

from datetime import datetime

from flask import current_app, g

from .adapters.sqlite import core


def runtime():
    return current_app.extensions["peygiri"]


def get_db():
    """Per-request panel DB connection, closed at teardown."""
    if "db" not in g:
        g.db = core.connect(runtime().settings.panel_db_path)
    return g.db


def now() -> datetime:
    return runtime().clock()

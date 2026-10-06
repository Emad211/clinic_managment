"""Application factory: wires config, panel DB, bridge and background threads."""
from __future__ import annotations

import logging
import threading
from datetime import timedelta

from flask import Flask, g

from .adapters.accounting.bridge import AccountingBridge
from .adapters.sqlite import core
from .api.health import bp as health_bp
from .config.settings import Settings, resource_dir
from .services.bridge_monitor import BridgeMonitor
from .version import APP_NAME, APP_VERSION

log = logging.getLogger(__name__)


class Runtime:
    """Long-lived objects shared by requests and background threads."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bridge = AccountingBridge(
            settings.accounting_db_path,
            budget_ms=settings.read_budget_ms,
            busy_timeout_ms=settings.busy_timeout_ms,
        )
        self.monitor = BridgeMonitor(self.bridge)
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []

    def start_background(self) -> None:
        self._spawn("bridge-monitor", self.monitor.run)

    def _spawn(self, name: str, target) -> None:
        t = threading.Thread(target=target, args=(self.stop,), name=name, daemon=True)
        t.start()
        self.threads.append(t)

    def shutdown(self, timeout: float = 5.0) -> None:
        self.stop.set()
        for t in self.threads:
            t.join(timeout)


def create_app(settings: Settings, *, start_background: bool = True) -> Flask:
    res = resource_dir() / "src"
    app = Flask(__name__, template_folder=str(res / "templates"), static_folder=str(res / "static"))
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        JSON_AS_ASCII=False,
    )

    core.init_db(settings.panel_db_path, settings.backups_dir)

    runtime = Runtime(settings)
    app.extensions["peygiri"] = runtime

    @app.before_request
    def _bind_runtime() -> None:
        g.runtime = runtime

    @app.teardown_appcontext
    def _close_db(_exc) -> None:
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.context_processor
    def _globals() -> dict:
        return {"app_name": APP_NAME, "app_version": APP_VERSION}

    app.register_blueprint(health_bp)

    if start_background:
        runtime.start_background()
    return app


def get_db():
    """Per-request panel DB connection (closed at teardown)."""
    if "db" not in g:
        g.db = core.connect(g.runtime.settings.panel_db_path)
    return g.db

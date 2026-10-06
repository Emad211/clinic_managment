"""Application factory: wires config, panel DB, bridge, background threads and blueprints."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Callable

from flask import Flask, g

from .adapters.accounting.bridge import AccountingBridge
from .adapters.sqlite import core
from .api import auth as auth_api
from .api import clinical as clinical_api
from .api import health as health_api
from .api import identity as identity_api
from .api import manager as manager_api
from .api import pages as pages_api
from .api.security import check_client, check_csrf, csrf_token, principal
from .common import iran_time
from .common.jalali import jalali_date
from .common.persian_text import fa_digits
from .config.settings import Settings, resource_dir
from .services import journeys
from .services.bridge_monitor import BridgeMonitor
from .sync.poller import Poller
from .version import APP_NAME, APP_VERSION

log = logging.getLogger(__name__)

ENGINE_TICK_SECONDS = 60


class Runtime:
    """Long-lived objects shared by requests and background threads."""

    def __init__(self, settings: Settings, clock: Callable[[], datetime] = iran_time.now) -> None:
        self.settings = settings
        self.clock = clock
        self.bridge = AccountingBridge(
            settings.accounting_db_path,
            budget_ms=settings.read_budget_ms,
            busy_timeout_ms=settings.busy_timeout_ms,
        )
        self.monitor = BridgeMonitor(self.bridge)
        self.poller = Poller(self.bridge, settings.panel_db_path,
                             interval_seconds=settings.poll_seconds, clock=clock)
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []

    def start_background(self) -> None:
        self._spawn("bridge-monitor", self.monitor.run)
        self._spawn("poller", self._poll_when_ready)
        self._spawn("engine", self._engine_ticks)

    def _engine_ticks(self, stop: threading.Event) -> None:
        """Time-driven journey transitions every 60 s (docs/02 §2); also catches day changes."""
        while not stop.is_set():
            try:
                conn = core.connect(self.settings.panel_db_path)
                try:
                    journeys.tick_all(conn, self.clock())
                finally:
                    conn.close()
            except Exception:                      # never let the thread die
                log.exception("engine tick crashed")
            stop.wait(ENGINE_TICK_SECONDS)

    def _poll_when_ready(self, stop: threading.Event) -> None:
        # The first schema check must pass before the first poll.
        while not stop.is_set() and self.monitor.status.state == "unchecked":
            stop.wait(0.2)
        self.poller.run(stop)

    def _spawn(self, name: str, target) -> None:
        t = threading.Thread(target=target, args=(self.stop,), name=name, daemon=True)
        t.start()
        self.threads.append(t)

    def shutdown(self, timeout: float = 5.0) -> None:
        self.stop.set()
        for t in self.threads:
            t.join(timeout)


def create_app(settings: Settings, *, start_background: bool = True,
               clock: Callable[[], datetime] = iran_time.now) -> Flask:
    res = resource_dir() / "src"
    app = Flask(__name__, template_folder=str(res / "templates"), static_folder=str(res / "static"))
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_NAME="peygiri_session",     # distinct from accounting's cookie on the same host
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    app.json.ensure_ascii = False

    core.init_db(settings.panel_db_path, settings.backups_dir)
    conn = core.connect(settings.panel_db_path)
    try:
        journeys.ensure_templates(conn, clock().strftime(iran_time.TS_FORMAT))
    finally:
        conn.close()

    runtime = Runtime(settings, clock)
    app.extensions["peygiri"] = runtime

    app.before_request(check_client)
    app.before_request(check_csrf)

    @app.teardown_appcontext
    def _close_db(_exc) -> None:
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.context_processor
    def _globals() -> dict:
        return {"app_name": APP_NAME, "app_version": APP_VERSION,
                "principal": principal(), "csrf_token": csrf_token}

    app.add_template_filter(fa_digits, "fa")
    app.add_template_filter(jalali_date, "jalali")

    app.register_blueprint(health_api.bp)
    app.register_blueprint(auth_api.bp)
    app.register_blueprint(pages_api.bp)
    app.register_blueprint(pages_api.doctor_bp)
    app.register_blueprint(pages_api.reception_bp)
    app.register_blueprint(manager_api.bp)
    app.register_blueprint(identity_api.bp)
    app.register_blueprint(clinical_api.bp)

    if start_background:
        runtime.start_background()
    return app

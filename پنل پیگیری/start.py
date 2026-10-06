"""Entry point for source runs (``python start.py``) and PeygiriPanel.exe.

Startup order (docs/02 §7): config → logging → single instance → panel DB
(backup + migrate) → schema check & threads → web server → browser.
"""
from __future__ import annotations

import logging
import sys
import threading
import webbrowser
from logging.handlers import RotatingFileHandler

from src.config.settings import ConfigError, base_dir, is_frozen, load_settings


def _fatal(message: str) -> None:
    """Show an error even though the exe has no console."""
    logging.getLogger("start").error(message)
    if is_frozen() and sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "پنل پیگیری", 0x10)
    else:
        print(message, file=sys.stderr)
    sys.exit(1)


def _setup_logging(logs_dir) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(logs_dir / "peygiri_panel.log", maxBytes=1_000_000,
                                  backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if not is_frozen():
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")   # Persian paths on a cp1252 console
        root.addHandler(logging.StreamHandler())
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def _open_browser_later(url: str, delay: float = 1.5) -> None:
    threading.Timer(delay, lambda: webbrowser.open(url)).start()


def main() -> None:
    _setup_logging(base_dir() / "logs")
    log = logging.getLogger("start")
    try:
        settings = load_settings()
    except (ConfigError, OSError) as exc:
        _fatal(f"خطا در config.ini:\n{exc}")
        return

    url = f"http://127.0.0.1:{settings.port}/"

    from src.single_instance import InstanceLock, running_instance_alive
    lock = InstanceLock()
    if not lock.acquire():
        log.info("another instance is running; opening the browser")
        if settings.open_browser:
            webbrowser.open(url)
        return

    from werkzeug.serving import ThreadedWSGIServer

    from src.app import create_app

    # Fail on a taken port instead of sharing it (Windows SO_REUSEADDR semantics).
    ThreadedWSGIServer.allow_reuse_address = False
    try:
        server = ThreadedWSGIServer(settings.host, settings.port, None)
    except (OSError, SystemExit):   # werkzeug calls sys.exit(1) when the port is taken
        if running_instance_alive(settings.port):
            if settings.open_browser:
                webbrowser.open(url)
            return
        _fatal(f"پورت {settings.port} در اختیار برنامهٔ دیگری است. پورت را در config.ini عوض کنید.")
        return

    try:
        app = create_app(settings)
    except Exception as exc:  # noqa: BLE001 — must reach the user without a console
        server.server_close()
        log.exception("startup failed")
        _fatal(f"برنامه اجرا نشد:\n{exc}")
        return
    server.app = app
    app.extensions["peygiri"].stop_server = server.shutdown

    log.info("listening on %s:%d", settings.host, settings.port)
    if settings.open_browser:
        _open_browser_later(url)
    try:
        server.serve_forever()
    finally:
        app.extensions["peygiri"].shutdown()


if __name__ == "__main__":
    main()

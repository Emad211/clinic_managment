from __future__ import annotations

import socket
import threading

import pytest
from werkzeug.serving import ThreadedWSGIServer

from src.app import create_app
from src.config.settings import load_settings
from src.single_instance import running_instance_alive


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_detects_running_instance_and_port_is_exclusive(tmp_path, monkeypatch):
    monkeypatch.setattr(ThreadedWSGIServer, "allow_reuse_address", False)   # as start.py does
    port = free_port()
    assert not running_instance_alive(port, timeout=0.5)
    app = create_app(load_settings(tmp_path), start_background=False)
    server = ThreadedWSGIServer("127.0.0.1", port, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert running_instance_alive(port)
        # A second server cannot share the port; werkzeug reports it with sys.exit(1).
        with pytest.raises((OSError, SystemExit)):
            ThreadedWSGIServer("127.0.0.1", port, app)
    finally:
        server.shutdown()
        server.server_close()


def test_foreign_service_is_not_mistaken_for_us():
    port = free_port()
    with socket.socket() as s:                   # something listening that is not us
        s.bind(("127.0.0.1", port))
        s.listen()
        assert not running_instance_alive(port, timeout=0.5)

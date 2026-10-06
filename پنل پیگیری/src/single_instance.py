"""One process only (docs/02 §5).

A second launch must not start a second poller. It asks the running instance
whether it is alive and, if so, just opens the browser and exits.

Two layers:
* a named Windows mutex (atomic, survives races between two quick launches);
* the HTTP server binds without SO_REUSEADDR, so a port collision fails loudly
  instead of silently sharing the port (see ``start.py``).
"""
from __future__ import annotations

import json
import sys
import urllib.request

from .version import APP_ID

_MUTEX_NAME = "Local\\PeygiriPanel.SingleInstance"
_ERROR_ALREADY_EXISTS = 183


class InstanceLock:
    def __init__(self) -> None:
        self._handle = None

    def acquire(self) -> bool:
        """True if this is the only instance on this Windows session."""
        if sys.platform != "win32":
            return True
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if not handle:
            return True  # cannot tell; the port bind is the second guard
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            return False
        self._handle = handle  # held for the process lifetime
        return True


def running_instance_alive(port: int, timeout: float = 2.0) -> bool:
    """True if our app answers /healthz on this machine."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")).get("app") == APP_ID
    except (OSError, ValueError):
        return False

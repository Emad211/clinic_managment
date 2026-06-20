"""One-time application logging setup.

In the frozen .exe (PyInstaller, typically `--noconsole`) stdout/stderr go nowhere, so the
background scheduler's diagnostics would be lost — the owner would never know that
engagement / invoice-sync / backup is failing every tick. This routes WARNING+ to a
rotating file next to the DB (`specialist_errors.log`) and keeps full console output in
source/dev mode.

Privacy: log MESSAGES are kept PII-free (static strings), and Python's default traceback
does not serialize local variables, so patient data does not land in the file. The file is
gitignored and lives on the clinic PC beside the (already unencrypted) DB.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_FILENAME = "specialist_errors.log"


def setup_app_logging(log_dir: str) -> None:
    """Configure the root logger once (idempotent). WARNING+ to a rotating file
    (1 MB × 3); INFO+ also to the console in source/dev mode (not in the frozen exe)."""
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return  # already configured
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    try:
        fh = RotatingFileHandler(
            os.path.join(log_dir, LOG_FILENAME),
            maxBytes=1_000_000, backupCount=3, encoding="utf-8", delay=True)
        fh.setLevel(logging.WARNING)   # file: only warnings/errors
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception as e:  # never let logging setup break boot
        print(f"[logging] file handler not started: {e}")
    if not getattr(sys, "frozen", False):
        sh = logging.StreamHandler()
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)
        root.addHandler(sh)

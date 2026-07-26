from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


for relative in (
    "specialist_clinic/tests/test_invoice_outreach.py",
    "specialist_clinic/tests/test_invoice_outreach_retry.py",
    "specialist_clinic/tests/test_visit_invites.py",
):
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    old = '''def _set_acc_path(path: str):
    """Hot-swap Config.ACCOUNTING_DB_PATH so the next bridge call uses the new path."""
    os.environ["ACCOUNTING_DB_PATH"] = path
    import src.config.settings as cfg_mod
    cfg_mod.Config.ACCOUNTING_DB_PATH = path
'''
    new = '''def _set_acc_path(path: str):
    """Hot-swap the exact active test application's read-only accounting path."""
    os.environ["ACCOUNTING_DB_PATH"] = path
    import src.config.settings as cfg_mod
    cfg_mod.Config.ACCOUNTING_DB_PATH = path
    from flask import current_app
    current_app.config["ACCOUNTING_DB_PATH"] = path
'''
    if new not in text:
        if old not in text:
            raise AssertionError(f"accounting hot-swap helper missing: {relative}")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

# A4 fixture explicitly supplies its accounting database to the app instance. Module
# flushing elsewhere in the suite can no longer replace the Config class it imported.
path = ROOT / "specialist_clinic/tests/test_specialist_attendance_collection.py"
text = path.read_text(encoding="utf-8")
old = '''            "DATABASE_PATH": str(tmp_path / "specialist.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
'''
new = '''            "DATABASE_PATH": str(tmp_path / "specialist.db"),
            "ACCOUNTING_DB_PATH": str(accounting),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
'''
if new not in text:
    if old not in text:
        raise AssertionError("A4 per-app accounting fixture anchor missing")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

Path(__file__).unlink()

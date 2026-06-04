import os
import sys


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'specialist-clinic-secret-change-in-prod'

    # Determine project root in both source and frozen (PyInstaller) modes.
    if getattr(sys, 'frozen', False):
        # When bundled by PyInstaller the executable lives in sys.executable.
        # DB/backups are created next to the exe (writable on typical installs).
        PROJECT_ROOT = os.path.dirname(sys.executable)
        BASE_DIR = PROJECT_ROOT
    else:
        # Source layout: src/config -> src -> specialist_clinic
        BASE_DIR = os.path.abspath(os.path.dirname(__file__))
        PROJECT_ROOT = os.path.dirname(os.path.dirname(BASE_DIR))

    # This app's own database
    DATABASE_PATH = os.environ.get('SPECIALIST_DB_PATH') or os.path.join(PROJECT_ROOT, 'specialist.db')

    # Read-only bridge to the accounting app's database.
    # Default: ../webapp/clinic_new.db relative to the repo root (source mode).
    # Override with ACCOUNTING_DB_PATH env var (recommended for the .exe build).
    _repo_root = os.path.dirname(PROJECT_ROOT)
    ACCOUNTING_DB_PATH = os.environ.get('ACCOUNTING_DB_PATH') or os.path.join(_repo_root, 'webapp', 'clinic_new.db')

    # Backups folder
    BACKUP_FOLDER = os.path.join(PROJECT_ROOT, 'backups')

    # Network
    PORT = int(os.environ.get('PORT', 8090))

    DEBUG = True
    TESTING = False


class TestConfig(Config):
    TESTING = True
    DATABASE_PATH = ':memory:'

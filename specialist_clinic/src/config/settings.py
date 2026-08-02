import os
import sys


# The weak fallback secret used for local/.exe/LAN runs. In a real server deployment
# (PRODUCTION=1) create_app() refuses to start with this default — see src/app.py.
DEFAULT_SECRET_KEY = 'specialist-clinic-secret-change-in-prod'


# Follow-up Orchestration & UX v1 is registered in FO-0 only. These flags are
# intentionally declared here before any implementation consumes them. Every flag
# defaults to OFF and must be enabled explicitly in a later, separately reviewed
# tranche. See docs/FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md.
FOLLOWUP_ORCHESTRATION_FLAGS = (
    'FOLLOWUP_EPISODES_ENABLED',
    'FOLLOWUP_PROJECTION_SHADOW',
    'FOLLOWUP_UNIFIED_WORKLIST_READONLY',
    'FOLLOWUP_UNIFIED_WORKLIST_ACTIONS',
    'FOLLOWUP_AUTO_ROUTING',
    'FOLLOWUP_STRUCTURED_CONTACT',
    'FOLLOWUP_SMS_AUTO_GUARDED',
    'FOLLOWUP_APPOINTMENT_SYNC',
    'FOLLOWUP_EVIDENCE_ASSIST',
    'FOLLOWUP_AUTOMATION_HEALTH',
)


def _env_flag(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or DEFAULT_SECRET_KEY

    # True ONLY in a real (cloud/server) deployment. Gates the security hardening so the
    # local .exe / LAN / dev / test runs keep working exactly as before (0.0.0.0 bind for
    # the in-clinic card/tablet, default secret, http cookies). The cloud deploy sets PRODUCTION=1.
    PRODUCTION = _env_flag('PRODUCTION')

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

    DEBUG = _env_flag('DEBUG')
    TESTING = False

    # FOUX-V1 feature gates. FO-0 only registers these names. No runtime service,
    # route, template, schema installer or scheduler job may consume them until its
    # corresponding tranche is approved and implemented.
    FOLLOWUP_EPISODES_ENABLED = _env_flag('FOLLOWUP_EPISODES_ENABLED')
    FOLLOWUP_PROJECTION_SHADOW = _env_flag('FOLLOWUP_PROJECTION_SHADOW')
    FOLLOWUP_UNIFIED_WORKLIST_READONLY = _env_flag(
        'FOLLOWUP_UNIFIED_WORKLIST_READONLY'
    )
    FOLLOWUP_UNIFIED_WORKLIST_ACTIONS = _env_flag(
        'FOLLOWUP_UNIFIED_WORKLIST_ACTIONS'
    )
    FOLLOWUP_AUTO_ROUTING = _env_flag('FOLLOWUP_AUTO_ROUTING')
    FOLLOWUP_STRUCTURED_CONTACT = _env_flag('FOLLOWUP_STRUCTURED_CONTACT')
    FOLLOWUP_SMS_AUTO_GUARDED = _env_flag('FOLLOWUP_SMS_AUTO_GUARDED')
    FOLLOWUP_APPOINTMENT_SYNC = _env_flag('FOLLOWUP_APPOINTMENT_SYNC')
    FOLLOWUP_EVIDENCE_ASSIST = _env_flag('FOLLOWUP_EVIDENCE_ASSIST')
    FOLLOWUP_AUTOMATION_HEALTH = _env_flag('FOLLOWUP_AUTOMATION_HEALTH')


class TestConfig(Config):
    TESTING = True
    DATABASE_PATH = ':memory:'

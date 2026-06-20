import os
import sys
import sqlite3
import pkgutil

from flask import g

from src.config.settings import Config

_initialized = False


def _load_schema_text():
    """Load bundled schema.sql in both source and frozen (PyInstaller) modes."""
    try:
        data = pkgutil.get_data('src.adapters.sqlite', 'schema.sql')
        if data:
            return data.decode('utf-8')
    except Exception:
        pass

    # Fallback 1: next to this module
    here = os.path.join(os.path.dirname(__file__), 'schema.sql')
    if os.path.exists(here):
        with open(here, 'r', encoding='utf-8') as f:
            return f.read()

    # Fallback 2: PyInstaller onefile extraction dir
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        for cand in (
            os.path.join(meipass, 'src', 'adapters', 'sqlite', 'schema.sql'),
            os.path.join(meipass, 'schema.sql'),
        ):
            if os.path.exists(cand):
                with open(cand, 'r', encoding='utf-8') as f:
                    return f.read()

    raise FileNotFoundError('schema.sql not found')


def _ensure_column(db, table: str, column: str, decl: str):
    try:
        cols = db.execute(f"PRAGMA table_info({table})").fetchall()
        if not any(c["name"] == column for c in cols):
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            db.commit()
    except Exception:
        pass


def _seed_condition_meta(db):
    """Backfill disease-module metadata on existing `conditions` rows (idempotent;
    only fills blanks / the default order, so manager edits are preserved)."""
    meta = [
        ('diabetes', 10, 'i-activity', 'info',
         'پایش قند، اهداف فردی، انتخاب دارو، غربالگری عوارض و واکسیناسیون.'),
        ('hypertension', 20, 'i-heart', 'danger',
         'کنترل فشار خون، انتخاب داروی ضدفشار، پایش کلیه/پتاسیم و هشدار بحران فشار.'),
        ('hyperlipidemia', 30, 'i-sigma', 'warn',
         'اهداف LDL، استاتین‌درمانی و پایش لیپید.'),
        ('ckd', 40, 'i-clipboard', 'violet',
         'مرحله‌بندی eGFR/آلبومینوری، داروهای محافظ کلیه و پایش.'),
        ('thyroid', 50, 'i-stethoscope', 'ok',
         'پایش TSH و تنظیم درمان تیروئید.'),
    ]
    try:
        for code, order, icon, color, desc in meta:
            db.execute(
                """UPDATE conditions SET
                     display_order = CASE WHEN display_order IS NULL OR display_order=100 THEN ? ELSE display_order END,
                     icon        = COALESCE(icon, ?),
                     color       = COALESCE(color, ?),
                     description = COALESCE(description, ?)
                   WHERE code = ?""",
                (order, icon, color, desc, code))
        db.commit()
    except Exception:
        pass


def _seed_flag_sections(db):
    """Backfill `flag_catalog.record_section` from each flag's existing category
    (idempotent; only fills rows where record_section IS NULL, so manager edits
    are preserved). Section ∈ lifestyle|exam|disease|general — the buckets used by
    the redesigned patient record (docs/record_redesign_plan.md §2).

    Mapping from the seeded `category`:
      cardiac|renal|hepatic|risk|repro -> disease  (clinical condition attributes)
      lifestyle                        -> lifestyle (smoking/vape, ...)
      exam                             -> exam      (monofilament, eye/foot exam)
      functional|history|other|else    -> general

    Per-flag overrides (win over the category mapping): metabolic_surgery is a
    clinical comorbidity/decision-input, not a generic note, so it goes to disease.
    """
    category_to_section = {
        'cardiac': 'disease',
        'renal': 'disease',
        'hepatic': 'disease',
        'risk': 'disease',
        'repro': 'disease',
        'lifestyle': 'lifestyle',
        'exam': 'exam',
        'functional': 'general',
        'history': 'general',
        'other': 'general',
    }
    # Specific flags whose record_section differs from their category mapping.
    flag_overrides = {
        'metabolic_surgery': 'disease',
    }
    try:
        # Per-flag overrides FIRST so they win over the category mapping; still
        # guarded by IS NULL so manager edits are preserved.
        for flag_key, section in flag_overrides.items():
            db.execute(
                "UPDATE flag_catalog SET record_section = ? "
                "WHERE record_section IS NULL AND flag_key = ?",
                (section, flag_key))
        # Then map known categories; anything still unmapped falls back to 'general'.
        for category, section in category_to_section.items():
            db.execute(
                "UPDATE flag_catalog SET record_section = ? "
                "WHERE record_section IS NULL AND category = ?",
                (section, category))
        db.execute(
            "UPDATE flag_catalog SET record_section = 'general' "
            "WHERE record_section IS NULL")
        db.commit()
    except Exception:
        pass


def _run_migrations(db):
    """Additive migrations for existing DBs (new tables come from schema IF NOT EXISTS)."""
    _ensure_column(db, "patient_links", "wallet_balance", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "sms_campaigns", "campaign_type", "TEXT NOT NULL DEFAULT 'info'")
    _ensure_column(db, "sms_campaigns", "credit_amount", "INTEGER DEFAULT 0")
    _ensure_column(db, "sms_campaigns", "credit_expires_days", "INTEGER")
    _ensure_column(db, "sms_campaigns", "holdout_percent", "INTEGER NOT NULL DEFAULT 0")
    # Medication lifecycle: stop date for effect/timeline tracking
    _ensure_column(db, "patient_medications", "end_date", "TEXT")
    # Pharmacologic class (drives the treatment/risk engines)
    _ensure_column(db, "patient_medications", "drug_class", "TEXT")
    # Follow-up tasks generated by a clinical rule (for dedupe)
    _ensure_column(db, "followup_tasks", "source_rule", "TEXT")
    # Engagement engine: per-patient SMS opt-out + which event generated a worklist task
    _ensure_column(db, "patient_links", "sms_opt_out", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "followup_tasks", "source_event", "TEXT")
    # Per-disease modular engine: each rule belongs to a disease module ('all' = cross-disease)
    _ensure_column(db, "clinical_rules", "condition_code", "TEXT NOT NULL DEFAULT 'all'")
    # Disease-module registry metadata on the conditions table
    _ensure_column(db, "conditions", "is_chronic", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(db, "conditions", "display_order", "INTEGER NOT NULL DEFAULT 100")
    _ensure_column(db, "conditions", "description", "TEXT")
    _ensure_column(db, "conditions", "icon", "TEXT")
    _ensure_column(db, "conditions", "color", "TEXT")
    _seed_condition_meta(db)
    # Record redesign / care-loop foundation (Phase 1 — docs/record_redesign_plan.md §2):
    # additive columns on existing tables (new tables come from schema IF NOT EXISTS).
    _ensure_column(db, "flag_catalog", "record_section", "TEXT")
    _ensure_column(db, "followup_tasks", "appointment_id", "INTEGER")
    _ensure_column(db, "followup_tasks", "fulfillment", "TEXT DEFAULT 'in_person'")
    _ensure_column(db, "engagement_events", "event_type", "TEXT")
    _ensure_column(db, "engagement_events", "is_custom", "INTEGER DEFAULT 0")
    _ensure_column(db, "users", "api_token", "TEXT")
    _ensure_column(db, "processed_invoices", "outreach_done", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "lab_results", "test_key", "TEXT")
    _seed_flag_sections(db)
    # Seed the clinical decision-rule catalog (idempotent; manager edits preserved).
    # Also tags each rule's owning disease module (condition_code) on existing DBs.
    try:
        from src.adapters.sqlite.clinical_rules_seed import seed_clinical_rules
        seed_clinical_rules(db)
    except Exception:
        pass
    # Seed the lab-test and drug catalogs (idempotent; wrapped so a missing seed
    # module or any failure never breaks startup).
    try:
        from src.adapters.sqlite.lab_catalog_seed import seed_lab_catalog
        seed_lab_catalog(db)
    except Exception:
        pass
    try:
        from src.adapters.sqlite.drug_catalog_seed import seed_drug_catalog
        seed_drug_catalog(db)
    except Exception:
        pass


def _ensure_default_admin(db):
    """Create a default manager account (admin/admin) if no users exist."""
    try:
        row = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        if row and row['c'] == 0:
            import bcrypt
            pw = bcrypt.hashpw('admin'.encode('utf-8'), bcrypt.gensalt())
            db.execute(
                "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?, ?, ?, ?, 1)",
                ('admin', pw, 'manager', 'مدیر سیستم'),
            )
            db.commit()
    except Exception:
        pass


def get_db():
    """Return the per-request connection to the specialist DB (created on first use)."""
    global _initialized
    db = getattr(g, '_database', None)
    if db is None:
        db_path = Config.DATABASE_PATH
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            try:
                os.makedirs(db_dir, exist_ok=True)
            except Exception:
                pass

        db = g._database = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        # Tolerate brief write contention between the request thread and the background
        # scheduler (e.g. the read-only invoice-sync consumer writing its ledger).
        db.execute("PRAGMA busy_timeout = 3000")

        # Initialize schema once per process if users table is missing.
        try:
            cur = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if not cur.fetchone():
                db.executescript(_load_schema_text())
                _initialized = False
        except Exception:
            try:
                db.executescript(_load_schema_text())
            except Exception:
                pass

        if not _initialized:
            try:
                db.executescript(_load_schema_text())  # idempotent (IF NOT EXISTS / OR IGNORE)
            except Exception:
                pass
            _run_migrations(db)
            _ensure_default_admin(db)
            _initialized = True

    return db


def close_connection(exception=None):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db_command():
    """CLI helper: (re)apply schema."""
    db = get_db()
    db.executescript(_load_schema_text())
    _ensure_default_admin(db)
    print('Specialist DB initialized.')

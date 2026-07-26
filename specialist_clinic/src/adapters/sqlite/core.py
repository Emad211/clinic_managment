import os
import sys
import sqlite3
import pkgutil

from flask import g, current_app

from src.config.settings import Config

_initialized = False

_CLINICAL_ENGINE_V2_TABLES = frozenset({
    "clinical_rule_versions",
    "clinical_rulesets",
    "clinical_ruleset_members",
    "clinical_engine_runs",
    "clinical_rule_evaluations",
    "clinical_recommendation_events",
    "clinical_decision_events",
    "clinical_flag_events",
})
_CLINICAL_ENGINE_V2_TRIGGERS = frozenset({
    "trg_engine_runs_terminal_no_update",
    "trg_engine_runs_identity_immutable",
    "trg_engine_runs_no_delete",
    "trg_rule_evaluations_running_insert_only",
    "trg_rule_evaluations_no_update",
    "trg_rule_evaluations_no_delete",
    "trg_recommendation_events_running_insert_only",
    "trg_recommendation_events_terminal_presentation",
    "trg_recommendation_evaluation_same_run",
    "trg_recommendation_events_no_update",
    "trg_recommendation_events_no_delete",
    "trg_decision_events_terminal_run_only",
    "trg_decision_events_no_update",
    "trg_decision_events_no_delete",
    "trg_rule_version_content_immutable",
    "trg_rule_versions_no_delete",
    "trg_ruleset_identity_immutable",
    "trg_rulesets_no_delete",
    "trg_ruleset_members_draft_insert_only",
    "trg_ruleset_members_no_update",
    "trg_ruleset_members_no_delete",
})


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


def _ensure_clinical_engine_v2_storage(db):
    """Verify the additive v2 schema and install its safe-off feature flag.

    Unlike optional catalog seeds, missing audit tables must fail startup loudly:
    running a clinical engine without its immutable audit store is unsafe.
    """
    db.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        ("clinical_engine_v2_mode", "off"),
    )
    # PR-08: CREATED/SUPPRESSED belong to a running evaluation, whereas a
    # PRESENTED event can only truthfully be appended after the run is terminal.
    # Recreate these guards because CREATE TRIGGER IF NOT EXISTS cannot update
    # an older installed database's trigger body.
    db.executescript(
        """DROP TRIGGER IF EXISTS trg_recommendation_events_running_insert_only;
        DROP TRIGGER IF EXISTS trg_recommendation_events_terminal_presentation;
        CREATE TRIGGER trg_recommendation_events_running_insert_only
        BEFORE INSERT ON clinical_recommendation_events
        WHEN NEW.event_type IN ('CREATED', 'SUPPRESSED')
         AND (SELECT run_status FROM clinical_engine_runs WHERE run_id=NEW.run_id) <> 'RUNNING'
        BEGIN
            SELECT RAISE(ABORT, 'created/suppressed recommendations require a RUNNING clinical_engine_run');
        END;
        CREATE TRIGGER trg_recommendation_events_terminal_presentation
        BEFORE INSERT ON clinical_recommendation_events
        WHEN NEW.event_type IN ('PRESENTED', 'SUPERSEDED')
         AND (SELECT run_status FROM clinical_engine_runs WHERE run_id=NEW.run_id) = 'RUNNING'
        BEGIN
            SELECT RAISE(ABORT, 'presentation/supersession requires a terminal clinical_engine_run');
        END;"""
    )
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        f"AND name IN ({', '.join('?' for _ in _CLINICAL_ENGINE_V2_TABLES)})",
        tuple(sorted(_CLINICAL_ENGINE_V2_TABLES)),
    ).fetchall()
    present = {row["name"] for row in rows}
    missing = sorted(_CLINICAL_ENGINE_V2_TABLES - present)
    if missing:
        raise RuntimeError(
            "Clinical Engine v2 storage migration incomplete: " + ", ".join(missing)
        )
    trigger_rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' "
        f"AND name IN ({', '.join('?' for _ in _CLINICAL_ENGINE_V2_TRIGGERS)})",
        tuple(sorted(_CLINICAL_ENGINE_V2_TRIGGERS)),
    ).fetchall()
    present_triggers = {row["name"] for row in trigger_rows}
    missing_triggers = sorted(_CLINICAL_ENGINE_V2_TRIGGERS - present_triggers)
    if missing_triggers:
        raise RuntimeError(
            "Clinical Engine v2 audit guards incomplete: "
            + ", ".join(missing_triggers)
        )
    db.commit()


def _run_migrations(db):
    """Additive migrations for existing DBs (new tables come from schema IF NOT EXISTS)."""
    _ensure_column(db, "patient_links", "wallet_balance", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "sms_campaigns", "campaign_type", "TEXT NOT NULL DEFAULT 'info'")
    _ensure_column(db, "sms_campaigns", "credit_amount", "INTEGER DEFAULT 0")
    _ensure_column(db, "sms_campaigns", "credit_expires_days", "INTEGER")
    _ensure_column(db, "sms_campaigns", "holdout_percent", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "sms_campaigns", "delivered_count", "INTEGER DEFAULT 0")
    _ensure_column(db, "sms_campaigns", "pending_count", "INTEGER DEFAULT 0")
    _ensure_column(db, "sms_campaigns", "blacklist_count", "INTEGER DEFAULT 0")
    _ensure_column(db, "sms_campaigns", "claim_token", "TEXT")
    _ensure_column(db, "sms_campaigns", "claim_at", "TIMESTAMP")
    _ensure_column(db, "wallet_transactions", "idempotency_key", "TEXT")
    _ensure_column(db, "sms_messages", "provider", "TEXT")
    _ensure_column(db, "sms_messages", "provider_request_id", "TEXT")
    _ensure_column(db, "sms_messages", "idempotency_key", "TEXT")
    _ensure_column(db, "sms_messages", "delivery_status_int", "INTEGER")
    _ensure_column(db, "sms_messages", "delivery_checked_at", "TIMESTAMP")
    _ensure_column(db, "sms_messages", "next_status_check_at", "TIMESTAMP")
    _ensure_column(db, "sms_messages", "delivered_at", "TIMESTAMP")
    _ensure_column(db, "sms_messages", "send_attempts", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "sms_messages", "last_attempt_at", "TIMESTAMP")
    _ensure_column(db, "sms_messages", "retryable", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "sms_messages", "source_type", "TEXT")
    _ensure_column(db, "sms_messages", "source_ref", "TEXT")
    try:
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sms_messages_idempotency "
                   "ON sms_messages(idempotency_key) WHERE idempotency_key IS NOT NULL")
        db.execute("CREATE INDEX IF NOT EXISTS idx_sms_messages_delivery_due "
                   "ON sms_messages(provider, next_status_check_at, delivery_status)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_wallet_tx_idempotency "
                   "ON wallet_transactions(idempotency_key) WHERE idempotency_key IS NOT NULL")
        db.commit()
    except Exception:
        pass
    # Medication lifecycle: stop date for effect/timeline tracking
    _ensure_column(db, "patient_medications", "end_date", "TEXT")
    # Pharmacologic class (drives the treatment/risk engines)
    _ensure_column(db, "patient_medications", "drug_class", "TEXT")
    # Follow-up tasks generated by a clinical rule (for dedupe)
    _ensure_column(db, "followup_tasks", "source_rule", "TEXT")
    # Engagement engine: per-patient SMS opt-out + which event generated a worklist task
    _ensure_column(db, "patient_links", "sms_opt_out", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "followup_tasks", "source_event", "TEXT")
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
    # PR-09: provenance and two-level idempotency for Clinical Engine v2 tasks.
    _ensure_column(db, "followup_tasks", "source_engine", "TEXT")
    _ensure_column(db, "followup_tasks", "source_run_id", "TEXT")
    _ensure_column(db, "followup_tasks", "source_recommendation_event_id", "INTEGER")
    _ensure_column(db, "followup_tasks", "clinical_semantic_key", "TEXT")
    _ensure_column(db, "followup_tasks", "clinical_task_key", "TEXT")
    # These indexes are safety controls, not optional optimizations.  Failure
    # must abort startup instead of silently permitting duplicate clinical tasks.
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_followup_clinical_task_key "
        "ON followup_tasks(clinical_task_key) WHERE clinical_task_key IS NOT NULL"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_followup_open_clinical_semantic "
        "ON followup_tasks(patient_link_id, clinical_semantic_key) "
        "WHERE source_engine='clinical_v2' AND status='open' "
        "AND clinical_semantic_key IS NOT NULL"
    )
    db.commit()
    # Pre-v2 periodic-care heuristics and threshold-derived engagement are retired.
    # Data in this project is seed/demo; copied databases are cut over fail-closed.
    db.execute("DROP TABLE IF EXISTS care_protocols")
    db.execute(
        """UPDATE engagement_events
           SET is_active=0, channel='off'
           WHERE event_key IN (
               'uncontrolled','monitoring_due','screening_due','vaccine_due','red_flag'
           )"""
    )
    db.execute(
        """UPDATE engagement_events
           SET category='operational'
           WHERE event_key IN (
               'appointment_reminder','refill_due','lapsed','visit_invite',
               'thank_you','ear_wash_invite','wound_care_invite',
               'lab_consult_invite','bp_glucose_invite'
           )"""
    )
    db.execute(
        """UPDATE engagement_approvals
           SET status='rejected', decided_by='system:logic-consolidation',
               decided_at=datetime('now','+3 hours','+30 minutes'),
               last_error='Retired clinical interpretation event'
           WHERE status='pending' AND event_key IN (
               'uncontrolled','monitoring_due','screening_due','vaccine_due','red_flag'
           )"""
    )
    db.commit()
    _ensure_column(db, "engagement_events", "event_type", "TEXT")
    _ensure_column(db, "engagement_events", "is_custom", "INTEGER DEFAULT 0")
    _ensure_column(db, "engagement_approvals", "sms_message_id", "INTEGER")
    _ensure_column(db, "engagement_approvals", "send_attempts", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "engagement_approvals", "last_error", "TEXT")
    _ensure_column(db, "users", "api_token", "TEXT")
    _ensure_column(db, "users", "api_token_expires_at", "TEXT")  # SECU-05: extension token TTL
    _ensure_column(db, "processed_invoices", "outreach_done", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "lab_results", "test_key", "TEXT")
    _seed_flag_sections(db)
    # Installed pre-history revision triggers target the mutable table and treat
    # presentation-only catalog edits as clinical changes. Remove them before the
    # one-time migration; ensure_runtime_schema recreates the canonical bodies.
    db.executescript(
        """
        DROP TRIGGER IF EXISTS trg_clinical_revision_patient_flags_insert;
        DROP TRIGGER IF EXISTS trg_clinical_revision_patient_flags_update;
        DROP TRIGGER IF EXISTS trg_clinical_revision_patient_flags_delete;
        DROP TRIGGER IF EXISTS trg_clinical_revision_flag_catalog_insert;
        DROP TRIGGER IF EXISTS trg_clinical_revision_flag_catalog_update;
        DROP TRIGGER IF EXISTS trg_clinical_revision_flag_catalog_delete;
        DROP TRIGGER IF EXISTS trg_clinical_revision_flag_event_insert;
        """
    )
    from src.adapters.sqlite.clinical_flag_history_schema import (
        ensure_clinical_flag_history_storage,
    )
    ensure_clinical_flag_history_storage(db)
    from src.adapters.sqlite.clinical_reconciliation_schema import (
        ensure_clinical_reconciliation_storage,
    )
    from src.adapters.sqlite.clinical_data_conflict_schema import (
        ensure_clinical_data_conflict_storage,
    )
    ensure_clinical_reconciliation_storage(db)
    ensure_clinical_data_conflict_storage(db)
    from src.adapters.sqlite.clinical_care_loop_strict_guards import (
        ensure_strict_clinical_care_loop_guards,
    )
    from src.adapters.sqlite.security_permission_schema import (
        ensure_security_permission_storage,
    )
    from src.adapters.sqlite.operational_lease_schema import (
        ensure_operational_lease_storage,
    )
    from src.adapters.sqlite.specialist_revenue_boundary_schema import (
        ensure_specialist_revenue_boundary_storage,
    )
    from src.adapters.sqlite.followup_operations_schema import (
        ensure_followup_operations_storage,
    )
    from src.adapters.sqlite.clinical_task_contract_schema import (
        ensure_clinical_task_contract_storage,
    )
    from src.adapters.sqlite.clinical_alert_schema import (
        ensure_clinical_alert_storage,
    )
    from src.adapters.sqlite.specialist_financial_funnel_schema import (
        ensure_specialist_financial_funnel_storage,
    )
    from src.adapters.sqlite.sms_governance_schema import (
        ensure_sms_governance_storage,
    )
    from src.adapters.sqlite.campaign_economics_schema import (
        ensure_campaign_economics_storage,
    )
    from src.adapters.sqlite.specialist_payer_adjustment_schema import (
        ensure_specialist_payer_adjustment_storage,
    )
    from src.adapters.sqlite.specialist_service_lineage_schema import (
        ensure_specialist_service_lineage_storage,
    )
    from src.adapters.sqlite.encounter_documentation_schema import (
        ensure_encounter_documentation_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
        ensure_clinical_validation_storage,
    )
    from src.adapters.sqlite.clinical_audit_integrity_schema import (
        ensure_clinical_audit_integrity_storage,
    )
    ensure_strict_clinical_care_loop_guards(db)
    ensure_security_permission_storage(db)
    ensure_operational_lease_storage(db)
    ensure_specialist_revenue_boundary_storage(db)
    ensure_followup_operations_storage(db)
    ensure_clinical_task_contract_storage(db)
    ensure_clinical_alert_storage(db)
    ensure_specialist_financial_funnel_storage(db)
    ensure_sms_governance_storage(db)
    ensure_campaign_economics_storage(db)
    ensure_specialist_payer_adjustment_storage(db)
    ensure_specialist_service_lineage_storage(db)
    ensure_encounter_documentation_storage(db)
    ensure_clinical_validation_storage(db)
    ensure_clinical_audit_integrity_storage(db)
    _ensure_clinical_engine_v2_storage(db)
    from src.adapters.sqlite.descriptive_indicator_catalog_schema import (
        ensure_descriptive_indicator_catalog,
    )
    ensure_descriptive_indicator_catalog(db)
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

    # A copied pre-cutover database may still contain retired v1 objects. Remove
    # them on the same connection before `_initialized` is published. Fresh and
    # already-clean databases are a verified no-op.
    db.commit()
    from src.adapters.sqlite.clinical_engine_v1_cutover import (
        ensure_v1_schema_cutover,
    )

    ensure_v1_schema_cutover(db)


def _ensure_default_admin(db):
    """Create the first manager without permitting default credentials in production."""
    row = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    if not row or int(row["c"] or 0) != 0:
        return

    production = bool(current_app.config.get("PRODUCTION")) and not bool(
        current_app.config.get("TESTING", False)
    )
    username = str(
        current_app.config.get("BOOTSTRAP_ADMIN_USERNAME")
        or os.getenv("CLINIC_BOOTSTRAP_ADMIN_USERNAME")
        or "admin"
    ).strip()
    password = str(
        current_app.config.get("BOOTSTRAP_ADMIN_PASSWORD")
        or os.getenv("CLINIC_BOOTSTRAP_ADMIN_PASSWORD")
        or ""
    )
    if not username:
        raise RuntimeError("BOOTSTRAP_ADMIN_USERNAME cannot be empty")
    if production and (len(password) < 12 or password == "admin"):
        raise RuntimeError(
            "Production bootstrap requires CLINIC_BOOTSTRAP_ADMIN_PASSWORD "
            "with at least 12 characters; admin/admin is forbidden."
        )
    if not password:
        # Development/test compatibility only. Production is rejected above.
        password = "admin"

    import bcrypt

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    db.execute(
        "INSERT INTO users "
        "(username, password_hash, role, full_name, is_active) "
        "VALUES (?, ?, 'manager', ?, 1)",
        (username, password_hash, "مدیر سیستم"),
    )
    db.commit()


def get_db():
    """Return the per-request connection to the specialist DB (created on first use)."""
    global _initialized
    db = getattr(g, '_database', None)
    if db is None:
        # The application factory can point tests and packaged deployments at a
        # different database. Reading Config directly here silently ignored that
        # override and allowed tests to write into the real clinic database.
        db_path = current_app.config.get('DATABASE_PATH') or Config.DATABASE_PATH
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            try:
                os.makedirs(db_dir, exist_ok=True)
            except Exception:
                pass

        db = g._database = sqlite3.connect(db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        # Tolerate brief write contention between the request thread and the background
        # scheduler (e.g. the read-only invoice-sync consumer writing its ledger).
        db.execute("PRAGMA busy_timeout = 10000")
        if db_path != ":memory:":
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA synchronous = NORMAL")
            db.execute("PRAGMA wal_autocheckpoint = 1000")

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

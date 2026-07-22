-- Clinical Engine v2 — proposed additive SQLite DDL.
-- DESIGN ONLY. Existing clinical_rules and suggestion_log remain untouched during dual-run.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS clinical_rule_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_code TEXT NOT NULL,
    version TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '2.0',
    dsl_version TEXT NOT NULL DEFAULT '2.0',
    phase TEXT NOT NULL,
    action_type TEXT NOT NULL,
    rule_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_legacy_rule_id INTEGER,
    lifecycle_status TEXT NOT NULL DEFAULT 'DRAFT',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    supersedes_rule_version_id INTEGER,
    retired_at TEXT,
    change_note TEXT,
    UNIQUE(rule_code, version),
    UNIQUE(content_hash),
    FOREIGN KEY(source_legacy_rule_id) REFERENCES clinical_rules(id),
    FOREIGN KEY(supersedes_rule_version_id) REFERENCES clinical_rule_versions(id)
);
CREATE INDEX IF NOT EXISTS idx_rule_versions_code ON clinical_rule_versions(rule_code, id DESC);
CREATE INDEX IF NOT EXISTS idx_rule_versions_status ON clinical_rule_versions(lifecycle_status, phase);

CREATE TABLE IF NOT EXISTS clinical_rulesets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ruleset_code TEXT NOT NULL,
    version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    activated_by TEXT,
    activated_at TEXT,
    retired_at TEXT,
    note TEXT,
    UNIQUE(ruleset_code, version),
    UNIQUE(content_hash)
);
CREATE INDEX IF NOT EXISTS idx_rulesets_status ON clinical_rulesets(ruleset_code, status);

CREATE TABLE IF NOT EXISTS clinical_ruleset_members (
    ruleset_id INTEGER NOT NULL,
    rule_version_id INTEGER NOT NULL,
    phase TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 100,
    PRIMARY KEY(ruleset_id, rule_version_id),
    FOREIGN KEY(ruleset_id) REFERENCES clinical_rulesets(id),
    FOREIGN KEY(rule_version_id) REFERENCES clinical_rule_versions(id)
);
CREATE INDEX IF NOT EXISTS idx_ruleset_members_order
ON clinical_ruleset_members(ruleset_id, phase, sort_order, rule_version_id);

CREATE TABLE IF NOT EXISTS clinical_engine_runs (
    run_id TEXT PRIMARY KEY,
    patient_link_id INTEGER NOT NULL,
    encounter_key TEXT,
    as_of_at TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    run_status TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    ruleset_id INTEGER,
    fact_snapshot_json TEXT NOT NULL,
    fact_snapshot_hash TEXT NOT NULL,
    summary_json TEXT,
    error_json TEXT,
    legacy_compare_json TEXT,
    created_by TEXT,
    FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
    FOREIGN KEY(ruleset_id) REFERENCES clinical_rulesets(id)
);
CREATE INDEX IF NOT EXISTS idx_engine_runs_patient_time
ON clinical_engine_runs(patient_link_id, as_of_at DESC);
CREATE INDEX IF NOT EXISTS idx_engine_runs_status
ON clinical_engine_runs(run_status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_engine_runs_ruleset
ON clinical_engine_runs(ruleset_id, started_at DESC);

CREATE TABLE IF NOT EXISTS clinical_rule_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    rule_version_id INTEGER NOT NULL,
    predicate_state TEXT NOT NULL,
    outcome TEXT NOT NULL,
    trace_json TEXT NOT NULL,
    data_issues_json TEXT,
    recommendation_json TEXT,
    suppression_json TEXT,
    error_json TEXT,
    duration_ms REAL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, rule_version_id),
    FOREIGN KEY(run_id) REFERENCES clinical_engine_runs(run_id),
    FOREIGN KEY(rule_version_id) REFERENCES clinical_rule_versions(id)
);
CREATE INDEX IF NOT EXISTS idx_rule_eval_run_outcome
ON clinical_rule_evaluations(run_id, outcome);
CREATE INDEX IF NOT EXISTS idx_rule_eval_rule
ON clinical_rule_evaluations(rule_version_id, outcome, created_at DESC);

CREATE TABLE IF NOT EXISTS clinical_recommendation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    evaluation_id INTEGER,
    recommendation_key TEXT NOT NULL,
    action_type TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES clinical_engine_runs(run_id),
    FOREIGN KEY(evaluation_id) REFERENCES clinical_rule_evaluations(id)
);
CREATE INDEX IF NOT EXISTS idx_rec_events_run
ON clinical_recommendation_events(run_id, event_type, id);
CREATE INDEX IF NOT EXISTS idx_rec_events_key
ON clinical_recommendation_events(recommendation_key, created_at DESC);

CREATE TABLE IF NOT EXISTS clinical_decision_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_event_id INTEGER NOT NULL,
    patient_link_id INTEGER NOT NULL,
    decision TEXT NOT NULL,
    reason_code TEXT,
    reason_text TEXT,
    actor_user_id INTEGER,
    actor_username TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    supersedes_event_id INTEGER,
    legacy_source_suggestion_log_id INTEGER,
    FOREIGN KEY(recommendation_event_id) REFERENCES clinical_recommendation_events(id),
    FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
    FOREIGN KEY(actor_user_id) REFERENCES users(id),
    FOREIGN KEY(supersedes_event_id) REFERENCES clinical_decision_events(id),
    FOREIGN KEY(legacy_source_suggestion_log_id) REFERENCES suggestion_log(id)
);
CREATE INDEX IF NOT EXISTS idx_decision_events_recommendation
ON clinical_decision_events(recommendation_event_id, occurred_at, id);
CREATE INDEX IF NOT EXISTS idx_decision_events_patient
ON clinical_decision_events(patient_link_id, occurred_at DESC);


CREATE TRIGGER IF NOT EXISTS trg_engine_runs_terminal_no_update
BEFORE UPDATE ON clinical_engine_runs
WHEN OLD.run_status <> 'RUNNING'
BEGIN
    SELECT RAISE(ABORT, 'terminal clinical_engine_runs are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_engine_runs_no_delete
BEFORE DELETE ON clinical_engine_runs
BEGIN
    SELECT RAISE(ABORT, 'clinical_engine_runs cannot be deleted');
END;

-- Immutable child/event rows.
CREATE TRIGGER IF NOT EXISTS trg_rule_evaluations_no_update
BEFORE UPDATE ON clinical_rule_evaluations BEGIN
    SELECT RAISE(ABORT, 'clinical_rule_evaluations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_rule_evaluations_no_delete
BEFORE DELETE ON clinical_rule_evaluations BEGIN
    SELECT RAISE(ABORT, 'clinical_rule_evaluations cannot be deleted');
END;
CREATE TRIGGER IF NOT EXISTS trg_recommendation_events_no_update
BEFORE UPDATE ON clinical_recommendation_events BEGIN
    SELECT RAISE(ABORT, 'clinical_recommendation_events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_recommendation_events_no_delete
BEFORE DELETE ON clinical_recommendation_events BEGIN
    SELECT RAISE(ABORT, 'clinical_recommendation_events cannot be deleted');
END;
CREATE TRIGGER IF NOT EXISTS trg_decision_events_no_update
BEFORE UPDATE ON clinical_decision_events BEGIN
    SELECT RAISE(ABORT, 'clinical_decision_events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_decision_events_no_delete
BEFORE DELETE ON clinical_decision_events BEGIN
    SELECT RAISE(ABORT, 'clinical_decision_events cannot be deleted');
END;
CREATE TRIGGER IF NOT EXISTS trg_rule_version_content_immutable
BEFORE UPDATE OF rule_code, version, schema_version, dsl_version, phase,
                 action_type, rule_json, content_hash, source_legacy_rule_id
ON clinical_rule_versions BEGIN
    SELECT RAISE(ABORT, 'clinical rule version content is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_ruleset_members_no_update
BEFORE UPDATE ON clinical_ruleset_members BEGIN
    SELECT RAISE(ABORT, 'create a new ruleset version');
END;
CREATE TRIGGER IF NOT EXISTS trg_ruleset_members_no_delete
BEFORE DELETE ON clinical_ruleset_members BEGIN
    SELECT RAISE(ABORT, 'retire the ruleset instead');
END;

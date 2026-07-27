from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPECIALIST = ROOT / "specialist_clinic"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"A13 chain anchor missing in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


schema = SPECIALIST / "src/adapters/sqlite/schema.sql"
old_schema = '''CREATE TRIGGER IF NOT EXISTS trg_rule_review_events_role_separation
BEFORE INSERT ON clinical_rule_review_events
'''
new_schema = '''CREATE TRIGGER IF NOT EXISTS trg_rule_review_events_linear_history
BEFORE INSERT ON clinical_rule_review_events
WHEN (
    NEW.supersedes_event_id IS NULL
    AND EXISTS (
        SELECT 1 FROM clinical_rule_review_events prior
        WHERE prior.ruleset_id=NEW.ruleset_id
          AND prior.rule_version_id=NEW.rule_version_id
          AND prior.role=NEW.role
    )
) OR (
    NEW.supersedes_event_id IS NOT NULL
    AND EXISTS (
        SELECT 1 FROM clinical_rule_review_events newer
        WHERE newer.ruleset_id=NEW.ruleset_id
          AND newer.rule_version_id=NEW.rule_version_id
          AND newer.role=NEW.role
          AND newer.id>NEW.supersedes_event_id
    )
)
BEGIN
    SELECT RAISE(ABORT, 'review supersession must extend the latest event');
END;
CREATE TRIGGER IF NOT EXISTS trg_rule_review_events_role_separation
BEFORE INSERT ON clinical_rule_review_events
'''
replace_once(schema, old_schema, new_schema)

core = SPECIALIST / "src/adapters/sqlite/core.py"
replace_once(
    core,
    '    "trg_rule_review_events_supersedes_match",\n'
    '    "trg_rule_review_events_role_separation",\n',
    '    "trg_rule_review_events_supersedes_match",\n'
    '    "trg_rule_review_events_linear_history",\n'
    '    "trg_rule_review_events_role_separation",\n',
)

test_path = SPECIALIST / "tests/test_clinical_rule_review_governance_a13.py"
text = test_path.read_text(encoding="utf-8")
marker = "def test_review_history_is_a_single_linear_chain"
if marker not in text:
    text += r'''


def test_review_history_is_a_single_linear_chain(review_app):
    from src.adapters.sqlite.core import get_db

    service, ruleset, decisions = _prepared()
    service.review_rules(
        ruleset["id"], role="technical", decisions=decisions,
        actor_username="engineer-a", reviewer_display_name="Engineer A",
        note="initial technical review",
    )
    db = get_db()
    first = db.execute(
        """SELECT * FROM clinical_rule_review_events
           WHERE ruleset_id=? AND role='TECHNICAL'
           ORDER BY id LIMIT 1""",
        (ruleset["id"],),
    ).fetchone()
    service.review_rules(
        ruleset["id"], role="technical", decisions=decisions,
        actor_username="engineer-a", reviewer_display_name="Engineer A",
        note="corrected technical review note",
    )
    latest = db.execute(
        """SELECT * FROM clinical_rule_review_events
           WHERE ruleset_id=? AND rule_version_id=? AND role='TECHNICAL'
           ORDER BY id DESC LIMIT 1""",
        (ruleset["id"], first["rule_version_id"]),
    ).fetchone()
    assert int(latest["id"]) > int(first["id"])

    def insert_direct(supersedes_event_id, key):
        db.execute(
            """INSERT INTO clinical_rule_review_events
               (ruleset_id, rule_version_id, role, decision,
                ruleset_content_hash, rule_content_hash, package_hash,
                case_bundle_hash, reviewer_username, reviewer_display_name,
                note, supersedes_event_id, idempotency_key, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                latest["ruleset_id"], latest["rule_version_id"], latest["role"],
                latest["decision"], latest["ruleset_content_hash"],
                latest["rule_content_hash"], latest["package_hash"],
                latest["case_bundle_hash"], latest["reviewer_username"],
                latest["reviewer_display_name"], "direct fork attempt",
                supersedes_event_id, key, "2026-07-27 13:00:00",
            ),
        )

    with pytest.raises(sqlite3.IntegrityError, match="latest event"):
        insert_direct(first["id"], "stale-parent-attempt")
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="latest event"):
        insert_direct(None, "parallel-root-attempt")
    db.rollback()
'''
    test_path.write_text(text.rstrip() + "\n", encoding="utf-8")

print("A13 linear review history finalized")

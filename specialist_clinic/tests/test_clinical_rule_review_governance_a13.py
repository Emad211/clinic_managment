"""A13 dual-control and append-only rule review contract."""
from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture()
def review_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "review-a13.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "review-a13",
    })
    context = app.app_context()
    context.push()
    core.get_db()
    yield app
    context.pop()
    core._initialized = False


def _prepared():
    from src.services.clinical_engine.package_service import ClinicalRulePackageService

    service = ClinicalRulePackageService()
    ruleset = service.prepare(actor="package-preparer")
    decisions = {member["rule_code"]: "APPROVE" for member in ruleset["members"]}
    return service, ruleset, decisions


def test_dual_review_is_append_only_idempotent_and_separated(review_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.clinical_engine_rules_repo import ClinicalEngineRulesRepository

    service, ruleset, decisions = _prepared()
    service.review_rules(
        ruleset["id"], role="technical", decisions=decisions,
        actor_username="engineer-a", reviewer_display_name="Engineer A",
        note="facts, units, DSL and tasks reviewed",
    )
    service.review_rules(
        ruleset["id"], role="technical", decisions=decisions,
        actor_username="engineer-a", reviewer_display_name="Engineer A",
        note="facts, units, DSL and tasks reviewed",
    )
    db = get_db()
    assert db.execute(
        "SELECT COUNT(*) AS count FROM clinical_rule_review_events"
    ).fetchone()["count"] == len(decisions)

    service.review_rules(
        ruleset["id"], role="clinical", decisions=decisions,
        actor_username="engineer-a", reviewer_display_name="Engineer A",
        note="single-operator mode allows the same account for both roles",
    )
    summary = ClinicalEngineRulesRepository().rule_review_summary(ruleset["id"])
    assert summary["ready_to_freeze"] is True
    assert summary["distinct_reviewers"] is True
    assert summary["roles"]["clinical"]["reviewer_username"] == "engineer-a"
    assert summary["roles"]["technical"]["reviewer_username"] == "engineer-a"
    assert "بازبین بالینی و فنی باید دو حساب کاربری مستقل باشند" not in summary["blockers"]
    assert db.execute(
        "SELECT COUNT(*) AS count FROM clinical_rule_review_events"
    ).fetchone()["count"] == len(decisions) * 2

    frozen = service.freeze_reviewed_package(
        ruleset["id"], activated_by="release-manager", note="dual control complete",
    )
    assert frozen["status"] == "SILENT"
    with pytest.raises(ValueError, match="DRAFT"):
        service.review_rules(
            ruleset["id"], role="clinical", decisions=decisions,
            actor_username="engineer-a", reviewer_display_name="Engineer A",
            note="late mutation must fail",
        )


def test_review_storage_rejects_mutation_deletion_and_hash_mismatch(review_app):
    from src.adapters.sqlite.core import get_db

    service, ruleset, decisions = _prepared()
    service.review_rules(
        ruleset["id"], role="technical", decisions=decisions,
        actor_username="engineer-a", reviewer_display_name="Engineer A",
        note="technical review",
    )
    db = get_db()
    event = db.execute(
        "SELECT * FROM clinical_rule_review_events ORDER BY id LIMIT 1"
    ).fetchone()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE clinical_rule_review_events SET note='changed' WHERE id=?",
            (event["id"],),
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        db.execute("DELETE FROM clinical_rule_review_events WHERE id=?", (event["id"],))
    with pytest.raises(sqlite3.IntegrityError, match="hash mismatch"):
        db.execute(
            """INSERT INTO clinical_rule_review_events
               (ruleset_id, rule_version_id, role, decision,
                ruleset_content_hash, rule_content_hash, package_hash,
                case_bundle_hash, reviewer_username, reviewer_display_name,
                note, idempotency_key, created_at)
               VALUES (?, ?, 'CLINICAL', 'APPROVE', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ruleset["id"], event["rule_version_id"], "bad-ruleset-hash",
                event["rule_content_hash"], event["package_hash"],
                event["case_bundle_hash"], "physician-b", "Physician B",
                "bad identity", "bad-idempotency", "2026-07-27 12:00:00",
            ),
        )


def test_legacy_single_reviewer_freeze_is_retired(review_app):
    service, ruleset, decisions = _prepared()
    with pytest.raises(ValueError, match="تک‌نفره حذف شده"):
        service.approve_and_freeze(
            ruleset["id"], reviewer="one-person",
            attested_codes=list(decisions), note="unsafe",
        )



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

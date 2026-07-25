"""Startup and HTTP read-boundary tests for retired Clinical Engine v1 storage."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))
if str(SPECIALIST_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT / "tests"))

from test_clinical_engine_v2_compiler import valid_rule
from src.adapters.sqlite.clinical_engine_rules_repo import (
    ClinicalEngineRulesRepository,
)
from src.services.clinical_engine.compiler import RuleCompiler


@pytest.fixture()
def cutover_db_path(tmp_path):
    return tmp_path / "request-cutover.db"


def _create_app(db_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    return create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(db_path),
            "BACKUP_FOLDER": str(db_path.parent / "backups"),
            "SECRET_KEY": "request-cutover-test",
        }
    )


def _tables(db) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _columns(db, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _assert_clean_main_schema(db):
    tables = _tables(db)
    assert "clinical_rules" not in tables
    assert "suggestion_log" not in tables
    assert "source_legacy_rule_id" not in _columns(
        db, "clinical_rule_versions"
    )
    assert "legacy_source_suggestion_log_id" not in _columns(
        db, "clinical_decision_events"
    )
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def _insert_v2_rule() -> int:
    compiled = RuleCompiler().compile(valid_rule())
    return ClinicalEngineRulesRepository().create_rule_version(
        compiled,
        created_by="pytest-cutover",
    )


def _seed_pre_cutover_v2_rule(db_path: Path) -> int:
    """Create the exact old schema with one clean v2 row before app startup."""
    from src.adapters.sqlite import core

    raw = valid_rule()
    canonical = json.dumps(
        raw,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(core._load_schema_text())
        connection.executescript(
            """
            CREATE TABLE clinical_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_code TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL
            );
            CREATE TABLE suggestion_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_link_id INTEGER NOT NULL,
                rule_code TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                FOREIGN KEY(patient_link_id) REFERENCES patient_links(id)
            );
            ALTER TABLE clinical_rule_versions
              ADD COLUMN source_legacy_rule_id INTEGER
              REFERENCES clinical_rules(id);
            ALTER TABLE clinical_decision_events
              ADD COLUMN legacy_source_suggestion_log_id INTEGER
              REFERENCES suggestion_log(id);
            """
        )
        cursor = connection.execute(
            """INSERT INTO clinical_rule_versions
               (rule_code, version, schema_version, dsl_version, phase,
                action_type, rule_json, content_hash, lifecycle_status,
                created_by, created_at)
               VALUES (?, ?, '2.0', '2.0', 'ROUTINE', 'educate', ?, ?,
                       'DRAFT', 'pre-cutover-test', '2026-07-23 09:00:00')""",
            (
                raw["rule_code"],
                raw["version"],
                canonical,
                hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_application_construction_removes_v1_storage_and_preserves_v2_rows(
    cutover_db_path,
):
    from src.adapters.sqlite import core

    rule_id = _seed_pre_cutover_v2_rule(cutover_db_path)
    app = _create_app(cutover_db_path)
    try:
        with app.app_context():
            db = core.get_db()
            _assert_clean_main_schema(db)
            row = db.execute(
                "SELECT rule_code FROM clinical_rule_versions WHERE id=?",
                (rule_id,),
            ).fetchone()
            assert row["rule_code"] == valid_rule()["rule_code"]

        before = _file_hash(cutover_db_path)
        response = app.test_client().get("/auth/login")
        after = _file_hash(cutover_db_path)
        assert response.status_code == 200
        assert after == before
    finally:
        core._initialized = False


def test_restart_cutover_is_idempotent_and_preserves_clean_v2_rows(
    cutover_db_path,
):
    from src.adapters.sqlite import core

    first_app = _create_app(cutover_db_path)
    with first_app.app_context():
        rule_id = _insert_v2_rule()
        _assert_clean_main_schema(core.get_db())

    core._initialized = False
    second_app = _create_app(cutover_db_path)
    try:
        # The canonical schema never recreates v1 objects; restart remains a no-op.
        with second_app.app_context():
            db = core.get_db()
            _assert_clean_main_schema(db)
            assert db.execute(
                "SELECT COUNT(*) AS count FROM clinical_rule_versions "
                "WHERE id=?",
                (rule_id,),
            ).fetchone()["count"] == 1

        before = _file_hash(cutover_db_path)
        assert second_app.test_client().get("/auth/login").status_code == 200
        assert _file_hash(cutover_db_path) == before
    finally:
        core._initialized = False


def test_manager_disease_page_uses_request_local_read_only_projection(
    cutover_db_path,
):
    from src.adapters.sqlite import core

    app = _create_app(cutover_db_path)
    try:
        with app.app_context():
            _insert_v2_rule()

        client = app.test_client()
        login = client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        assert login.status_code == 302

        before = _file_hash(cutover_db_path)
        response = client.get("/manager/diseases")
        after = _file_hash(cutover_db_path)
        assert response.status_code == 200
        assert "پروتکل بیماری‌ها" in response.get_data(as_text=True)
        assert after == before

        with app.app_context():
            db = core.get_db()
            _assert_clean_main_schema(db)
            assert db.execute(
                "SELECT COUNT(*) AS count FROM sqlite_temp_master "
                "WHERE name='clinical_rules'"
            ).fetchone()["count"] == 0
    finally:
        core._initialized = False

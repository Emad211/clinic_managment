"""HTTP-bound cutover tests for the physically retired Clinical Engine v1 schema."""
from __future__ import annotations

from pathlib import Path
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


def test_first_request_removes_v1_storage_and_preserves_v2_rows(
    cutover_db_path,
):
    from src.adapters.sqlite import core

    app = _create_app(cutover_db_path)
    try:
        with app.app_context():
            db = core.get_db()
            assert {"clinical_rules", "suggestion_log"} <= _tables(db)
            rule_id = _insert_v2_rule()

        response = app.test_client().get("/auth/login")
        assert response.status_code == 200

        with app.app_context():
            db = core.get_db()
            _assert_clean_main_schema(db)
            row = db.execute(
                "SELECT rule_code FROM clinical_rule_versions WHERE id=?",
                (rule_id,),
            ).fetchone()
            assert row["rule_code"] == valid_rule()["rule_code"]
    finally:
        core._initialized = False


def test_restart_recreates_then_retires_only_v1_storage_idempotently(
    cutover_db_path,
):
    from src.adapters.sqlite import core

    first_app = _create_app(cutover_db_path)
    with first_app.app_context():
        rule_id = _insert_v2_rule()
    assert first_app.test_client().get("/auth/login").status_code == 200
    with first_app.app_context():
        _assert_clean_main_schema(core.get_db())

    core._initialized = False
    second_app = _create_app(cutover_db_path)
    try:
        # The old idempotent schema file temporarily recreates only the two inert
        # v1 tables during process bootstrap. The first request removes them again;
        # existing clean v2 tables are never rebuilt or rewritten.
        with second_app.app_context():
            assert {"clinical_rules", "suggestion_log"} <= _tables(
                core.get_db()
            )

        assert second_app.test_client().get("/auth/login").status_code == 200
        with second_app.app_context():
            db = core.get_db()
            _assert_clean_main_schema(db)
            assert db.execute(
                "SELECT COUNT(*) AS count FROM clinical_rule_versions "
                "WHERE id=?",
                (rule_id,),
            ).fetchone()["count"] == 1
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

        response = client.get("/manager/diseases")
        assert response.status_code == 200
        assert "پروتکل بیماری‌ها" in response.get_data(as_text=True)

        with app.app_context():
            db = core.get_db()
            _assert_clean_main_schema(db)
            assert db.execute(
                "SELECT COUNT(*) AS count FROM sqlite_temp_master "
                "WHERE name='clinical_rules'"
            ).fetchone()["count"] == 0
    finally:
        core._initialized = False

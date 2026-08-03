from __future__ import annotations

from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

from flask import Flask, g

from src.adapters.sqlite.followup_projection_schema import (
    PROJECTION_REQUIRED_COLUMNS,
    ensure_followup_projection_storage,
    projection_storage_status,
)
from src.api import unified_followups
from src.security import permissions as permission_module
from src.security.permissions import PermissionDecision
from src.services.followup_orchestration.projection_service import (
    FollowupProjectionService,
)
from src.services.followup_orchestration.read_model_service import (
    FollowupUnifiedReadModelService,
)
from src.services.followup_orchestration.timeline_service import (
    FollowupTimelineService,
)


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]


def _fo2_module():
    path = Path(__file__).with_name("test_followup_orchestration_fo2.py")
    spec = importlib.util.spec_from_file_location("fo2_fixture_module_for_fo3", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _upgrade_patient_identity_fixture(db: sqlite3.Connection) -> None:
    """Give the compact FO-1 fixture the patient identity columns FO-3 displays."""
    db.executescript(
        """
        ALTER TABLE patient_links ADD COLUMN full_name TEXT;
        ALTER TABLE patient_links ADD COLUMN national_id TEXT;
        ALTER TABLE patient_links ADD COLUMN phone_number TEXT;
        UPDATE patient_links
        SET full_name=CASE id
              WHEN 1 THEN 'بیمار آزمایشی یک'
              ELSE 'بیمار آزمایشی دو'
            END,
            national_id=CASE id
              WHEN 1 THEN '0012345678'
              ELSE '0098765432'
            END,
            phone_number=CASE id
              WHEN 1 THEN '09120000001'
              ELSE '09120000002'
            END;
        """
    )
    db.commit()


def _db() -> sqlite3.Connection:
    db = _fo2_module()._db()
    _upgrade_patient_identity_fixture(db)
    FollowupProjectionService(db).run(
        as_of_at="2026-08-03 12:00:00",
        apply=True,
    )
    return db


def _source_snapshot(db: sqlite3.Connection) -> str:
    return _fo2_module()._source_snapshot(db)


def _projection_snapshot(db: sqlite3.Connection) -> list[tuple[str, str]]:
    return [
        (str(row[0]), str(row[1]))
        for row in db.execute(
            """SELECT episode_id, projection_hash
               FROM followup_work_item_projection ORDER BY episode_id"""
        ).fetchall()
    ]


def _episode_snapshot(db: sqlite3.Connection) -> str:
    payload = {}
    for table in (
        "followup_episodes",
        "followup_episode_links",
        "followup_episode_events",
    ):
        payload[table] = [
            list(row)
            for row in db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _install_legacy_projection_cache(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        DROP TABLE followup_work_item_projection;
        CREATE TABLE followup_work_item_projection (
            episode_id TEXT PRIMARY KEY,
            patient_link_id INTEGER NOT NULL,
            state_class TEXT
        );
        INSERT INTO followup_work_item_projection
            (episode_id, patient_link_id, state_class)
        SELECT episode_id, patient_link_id, 'WAITING'
        FROM followup_episodes ORDER BY episode_id LIMIT 1;
        """
    )
    db.commit()


def test_read_model_discovers_all_projection_rows_with_pagination_and_filters():
    db = _db()
    service = FollowupUnifiedReadModelService(db)
    first = service.list_items(
        page=1,
        per_page=2,
        now=datetime(2026, 8, 3, 12, 30, 0),
    )
    second = service.list_items(
        page=2,
        per_page=2,
        now=datetime(2026, 8, 3, 12, 30, 0),
    )
    assert first["projection_ready"] is True
    assert first["readiness"]["code"] == "READY"
    assert first["total"] == 4
    assert first["pages"] == 2
    assert len(first["items"]) == 2
    assert len(second["items"]) == 2
    assert {
        item["episode_id"] for item in [*first["items"], *second["items"]]
    } == {
        row[0]
        for row in db.execute(
            "SELECT episode_id FROM followup_work_item_projection"
        ).fetchall()
    }

    actionable = service.list_items(
        state_class="ACTION_REQUIRED",
        role="NURSING",
        now=datetime(2026, 8, 3, 12, 30, 0),
    )
    assert actionable["total"] == 1
    assert actionable["items"][0]["reason_code"] == "CLINICAL_TASK"
    assert actionable["items"][0]["role_label"] == "صف پیشنهادی پرستاری"


def test_list_query_count_is_bounded_and_does_not_scale_per_item():
    db = _db()
    statements: list[str] = []
    db.set_trace_callback(
        lambda sql: statements.append(sql)
        if sql.lstrip().upper().startswith("SELECT")
        else None
    )
    FollowupUnifiedReadModelService(db).list_items(
        per_page=50,
        now=datetime(2026, 8, 3, 12, 30, 0),
    )
    db.set_trace_callback(None)
    assert len(statements) <= 6
    assert sum("followup_episode_links" in sql for sql in statements) <= 2


def test_read_model_and_timeline_never_mutate_source_or_projection():
    db = _db()
    before_source = _source_snapshot(db)
    before_projection = _projection_snapshot(db)
    model = FollowupUnifiedReadModelService(db).list_items(
        per_page=50,
        now=datetime(2026, 8, 3, 12, 30, 0),
    )
    for item in model["items"]:
        FollowupTimelineService(db).build(item["episode_id"])
    assert _source_snapshot(db) == before_source
    assert _projection_snapshot(db) == before_projection


def test_timeline_is_deterministic_provenance_aware_and_phi_minimized():
    db = _db()
    episode_id = db.execute(
        "SELECT episode_id FROM followup_episodes ORDER BY episode_id LIMIT 1"
    ).fetchone()[0]
    service = FollowupTimelineService(db)
    first = service.build(episode_id)
    second = service.build(episode_id)
    assert first == second
    assert first and first["items"]
    assert any(item["kind"] == "EPISODE_EVENT" for item in first["items"])
    assert any(item["kind"] == "SOURCE_STATE" for item in first["items"])
    rendered = repr(first).lower()
    for forbidden in (
        "message_body",
        "phone_number",
        "full_name",
        "note",
        "clinical_value",
        "payload_json",
    ):
        assert forbidden not in rendered


def test_incompatible_disposable_cache_is_recreated_empty_and_idempotent():
    db = _db()
    before_source = _source_snapshot(db)
    before_episode = _episode_snapshot(db)
    _install_legacy_projection_cache(db)

    legacy = projection_storage_status(db)
    assert legacy["table_exists"] is True
    assert legacy["compatible"] is False
    assert legacy["missing_column_count"] > 0

    repaired = ensure_followup_projection_storage(db)
    assert repaired["cache_recreated"] is True
    assert repaired["cache_row_count"] == 0
    columns = {
        str(row[1])
        for row in db.execute("PRAGMA table_info(followup_work_item_projection)")
    }
    assert PROJECTION_REQUIRED_COLUMNS <= columns
    assert _source_snapshot(db) == before_source
    assert _episode_snapshot(db) == before_episode

    rerun = ensure_followup_projection_storage(db)
    assert rerun["cache_recreated"] is False
    assert rerun["cache_row_count"] == 0
    assert _source_snapshot(db) == before_source
    assert _episode_snapshot(db) == before_episode


def test_incompatible_cache_returns_controlled_readiness_instead_of_sql_error():
    db = _db()
    _install_legacy_projection_cache(db)
    result = FollowupUnifiedReadModelService(db).list_items(
        now=datetime(2026, 8, 3, 12, 30, 0)
    )
    assert result["projection_ready"] is False
    assert result["read_error_code"] == "PROJECTION_SCHEMA_INCOMPATIBLE"
    assert result["items"] == []


def test_missing_patient_identity_columns_return_controlled_state():
    db = _db()
    db.execute("ALTER TABLE patient_links RENAME TO patient_links_authoritative")
    db.execute("CREATE TABLE patient_links (id INTEGER PRIMARY KEY)")
    db.commit()
    result = FollowupUnifiedReadModelService(db).list_items()
    assert result["projection_ready"] is False
    assert result["read_error_code"] == "PATIENT_IDENTITY_SCHEMA_INCOMPATIBLE"


def _minimal_route_app(db: sqlite3.Connection, *, enabled: bool) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(SPECIALIST_ROOT / "src" / "templates"),
    )
    app.config.update(
        TESTING=True,
        SECRET_KEY="test",
        FOLLOWUP_UNIFIED_WORKLIST_READONLY=enabled,
    )

    @app.before_request
    def _user():
        g.user = {"id": 1, "role": "manager", "username": "manager"}

    app.register_blueprint(unified_followups.bp)
    return app


def _allow_permissions(monkeypatch) -> None:
    monkeypatch.setattr(
        permission_module,
        "decide",
        lambda _user, required: PermissionDecision(
            permission=required,
            allowed=True,
            source="test",
        ),
    )


def test_routes_are_flag_gated_get_only_and_cache_disabled(monkeypatch):
    db = _db()
    monkeypatch.setattr(unified_followups, "get_db", lambda: db)
    _allow_permissions(monkeypatch)
    monkeypatch.setattr(
        unified_followups,
        "render_template",
        lambda _template, **_context: "ok",
    )

    disabled = _minimal_route_app(db, enabled=False).test_client()
    assert disabled.get("/followups/unified/").status_code == 404

    enabled = _minimal_route_app(db, enabled=True).test_client()
    response = enabled.get("/followups/unified/")
    assert response.status_code == 200
    assert response.headers["Cache-Control"].startswith("private, no-store")
    assert enabled.post("/followups/unified/").status_code == 405


def test_incompatible_cache_route_returns_controlled_page_not_500(monkeypatch):
    db = _db()
    _install_legacy_projection_cache(db)
    monkeypatch.setattr(unified_followups, "get_db", lambda: db)
    _allow_permissions(monkeypatch)

    rendered: list[tuple[str, dict]] = []

    def fake_render(template, **context):
        rendered.append((template, context))
        model = context.get("model") or {}
        readiness = context.get("readiness") or {}
        return model.get("read_error_code") or readiness.get("code") or "ok"

    monkeypatch.setattr(unified_followups, "render_template", fake_render)
    client = _minimal_route_app(db, enabled=True).test_client()

    list_response = client.get("/followups/unified/")
    assert list_response.status_code == 200
    assert b"PROJECTION_SCHEMA_INCOMPATIBLE" in list_response.data
    assert rendered[-1][0] == "followups/unified_worklist.html"

    detail_response = client.get("/followups/unified/fuep_missing")
    assert detail_response.status_code == 200
    assert b"PROJECTION_SCHEMA_INCOMPATIBLE" in detail_response.data
    assert rendered[-1][0] == "followups/unified_unavailable.html"


def test_templates_and_registration_preserve_read_only_boundary():
    app_source = (SPECIALIST_ROOT / "src" / "app.py").read_text(encoding="utf-8")
    route_source = (
        SPECIALIST_ROOT / "src" / "api" / "unified_followups.py"
    ).read_text(encoding="utf-8")
    list_page = (
        SPECIALIST_ROOT / "src" / "templates" / "followups" /
        "unified_worklist.html"
    ).read_text(encoding="utf-8")
    detail_page = (
        SPECIALIST_ROOT / "src" / "templates" / "followups" /
        "unified_detail.html"
    ).read_text(encoding="utf-8")
    unavailable_page = (
        SPECIALIST_ROOT / "src" / "templates" / "followups" /
        "unified_unavailable.html"
    ).read_text(encoding="utf-8")
    hub = (
        SPECIALIST_ROOT / "src" / "templates" / "sms" / "_hub_tabs.html"
    ).read_text(encoding="utf-8")

    assert "unified_followups_bp" in app_source
    assert "@bp.get" in route_source
    assert route_source.count("@bp.post") == 4
    assert "_require_actions_flag()" in route_source
    assert "_require_routing_flag()" in route_source
    assert "methods=[\"POST\"]" not in route_source
    assert "FOLLOWUP_UNIFIED_WORKLIST_READONLY" in route_source
    assert 'method="post"' not in list_page.lower()
    assert 'method="post"' in detail_page.lower()
    assert "actions_enabled" in detail_page
    assert 'method="post"' not in unavailable_page.lower()
    assert "انجام شد" not in list_page
    assert "دریافت برای رسیدگی" in detail_page
    assert "هیچ تغییری در پرونده یا تسک ایجاد نمی‌کند" in detail_page
    assert "هیچ داده، رابطه یا وضعیت بالینی حدس زده نشده است" in unavailable_page
    assert "config.get('FOLLOWUP_UNIFIED_WORKLIST_READONLY')" in hub
    assert "url_for('unified_followups.index')" in hub


def test_invalid_filters_fail_closed_to_unfiltered_values():
    result = FollowupUnifiedReadModelService(_db()).list_items(
        state_class="DROP TABLE",
        role="ROOT",
        sla_state="UNKNOWN",
        page="bad",
        per_page=9999,
        now=datetime(2026, 8, 3, 12, 30, 0),
    )
    assert result["filters"]["state"] == ""
    assert result["filters"]["role"] == ""
    assert result["filters"]["sla"] == ""
    assert result["page"] == 1
    assert result["per_page"] == 50
    assert result["total"] == 4

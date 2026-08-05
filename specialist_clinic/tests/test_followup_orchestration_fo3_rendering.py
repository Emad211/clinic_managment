from __future__ import annotations

from pathlib import Path


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]


def _build_real_app(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.core import get_db
    from src.app import create_app
    from src.services.followup_orchestration.backfill import (
        FollowupEpisodeBackfillService,
    )
    from src.services.followup_orchestration.projection_service import (
        FollowupProjectionService,
    )

    core._initialized = False
    database = tmp_path / "fo3-render.db"
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(database),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "fo3-render-test",
            "FOLLOWUP_UNIFIED_WORKLIST_READONLY": True,
        }
    )
    context = app.app_context()
    context.push()
    db = get_db()
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, phone_number, enrolled_by,
                enrolled_at, updated_at)
               VALUES ('FO3TEST001', 'بیمار تست نمای یکپارچه', '09120000003',
                       'pytest', '2026-08-03 09:00:00',
                       '2026-08-03 09:00:00')"""
        ).lastrowid
    )
    db.execute(
        """INSERT INTO followup_tasks
           (patient_link_id, due_date, reason, detail, status,
            source_event, fulfillment, created_at)
           VALUES (?, '2026-08-04', 'manual', 'پیگیری تستی', 'open',
                   'manual', 'in_person', '2026-08-03 09:05:00')""",
        (patient_id,),
    )
    db.commit()

    backfill = FollowupEpisodeBackfillService(db).run(apply=True)
    assert backfill["episodes_created"] == 1
    projection = FollowupProjectionService(db).run(
        as_of_at="2026-08-03 12:00:00",
        apply=True,
    )
    assert projection["projection_count"] == 1

    user_id = int(db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()[0])
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = user_id
    return app, context, db, client


def _install_legacy_projection_cache(db) -> None:
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


def test_real_flask_app_renders_work_center_and_history(tmp_path):
    from src.adapters.sqlite import core

    _app, context, db, client = _build_real_app(tmp_path)
    try:
        # The approved default is "My work". This fixture has not claimed the item,
        # so the broad rendering check explicitly opens the All-active view.
        list_response = client.get("/followups/unified/?view=all")
        assert list_response.status_code == 200
        list_html = list_response.get_data(as_text=True)
        assert "مرکز کارها" in list_html
        assert "بیمار تست نمای یکپارچه" in list_html
        assert "رسیدگی" in list_html

        episode_id = str(
            db.execute(
                "SELECT episode_id FROM followup_episodes ORDER BY episode_id LIMIT 1"
            ).fetchone()[0]
        )
        detail_response = client.get(
            f"/followups/unified/{episode_id}?view=all"
        )
        assert detail_response.status_code == 200
        detail_html = detail_response.get_data(as_text=True)
        assert "بیمار تست نمای یکپارچه" in detail_html
        assert "تاریخچه کار" in detail_html
        assert "کاری که اکنون باید انجام شود" in detail_html
        assert "دریافت برای رسیدگی" not in detail_html
    finally:
        context.pop()
        core._initialized = False


def test_real_flask_app_renders_controlled_legacy_cache_state_not_500(tmp_path):
    from src.adapters.sqlite import core

    _app, context, db, client = _build_real_app(tmp_path)
    try:
        _install_legacy_projection_cache(db)
        response = client.get("/followups/unified/?view=all")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "اطلاعات ذخیره‌شدهٔ این نما با نسخهٔ جدید سازگار نیست" in html
        assert "بازکردن پیگیری قدیمی" in html
        assert "PROJECTION_SCHEMA_INCOMPATIBLE" in html
        assert "خطای غیرمنتظره" not in html
    finally:
        context.pop()
        core._initialized = False


def test_unified_templates_do_not_use_ambiguous_dict_items_attribute():
    list_template = (
        SPECIALIST_ROOT / "src" / "templates" / "followups" /
        "unified_worklist.html"
    ).read_text(encoding="utf-8")
    detail_template = (
        SPECIALIST_ROOT / "src" / "templates" / "followups" /
        "unified_detail.html"
    ).read_text(encoding="utf-8")

    # Jinja resolves dot attributes before mapping keys. `model.items` therefore
    # means the built-in dict method rather than the projection rows and caused the
    # owner-reported HTTP 500. Mapping keys named `items` must use bracket notation.
    assert "model.items" not in list_template
    assert "timeline.items" not in detail_template
    assert "model['items']" in list_template
    assert "timeline['items']" in detail_template


def test_user_facing_copy_avoids_projection_jargon_and_hides_technical_data():
    from src.services.followup_orchestration.read_model_service import READINESS_COPY

    list_template = (
        SPECIALIST_ROOT / "src" / "templates" / "followups" /
        "unified_worklist.html"
    ).read_text(encoding="utf-8")
    detail_template = (
        SPECIALIST_ROOT / "src" / "templates" / "followups" /
        "unified_detail.html"
    ).read_text(encoding="utf-8")
    readiness_copy = "\n".join(
        value
        for copy in READINESS_COPY.values()
        for value in (copy["label"], copy["help"])
    )

    visible_copy = "\n".join((list_template, readiness_copy))
    for forbidden in (
        "Projection قدیمی",
        "سن Projection",
        "Projection هنوز ساخته نشده است",
        "Projection را صریحاً بازسازی کنید",
    ):
        assert forbidden not in visible_copy
        assert forbidden not in detail_template

    assert "نیازمند بازخوانی" in list_template
    assert "جزئیات پشتیبانی" in list_template
    assert "اطلاعات این نما نیازمند بازخوانی است" in detail_template
    assert "آخرین بازسازی" in detail_template
    assert "اطلاعات نمای یکپارچه هنوز آماده نشده است" in readiness_copy
    assert "اطلاعات ذخیره‌شدهٔ این نما با نسخهٔ جدید سازگار نیست" in readiness_copy

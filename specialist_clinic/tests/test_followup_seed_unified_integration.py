from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

from src.services.followup_orchestration.demo_seed_preparation import (
    DemoSeedFollowupPreparationService,
)
from src.services.followup_orchestration.read_model_service import (
    FollowupUnifiedReadModelService,
)


@pytest.fixture()
def seeded_app(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.core import get_db
    from src.app import create_app
    from src.services.clinical_engine.demo_cohort import DemoCohortService

    core._initialized = False
    database = tmp_path / "seeded-unified.db"
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(database),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "seeded-unified-test",
            "FOLLOWUP_UNIFIED_WORKLIST_READONLY": True,
            "FOLLOWUP_UNIFIED_WORKLIST_ACTIONS": True,
            "FOLLOWUP_AUTO_ROUTING": True,
        }
    )
    context = app.app_context()
    context.push()
    summary = DemoCohortService().ensure(actor="pytest-seed", force=True)
    assert summary["patient_count"] == 10
    assert summary["totals"]["followups"] > 0
    yield app, database, get_db()
    context.pop()
    core._initialized = False


def _demo_task_ids(db) -> list[int]:
    return [
        int(row[0])
        for row in db.execute(
            """SELECT CAST(value AS INTEGER)
               FROM settings
               WHERE key LIKE 'demo_followup_task_id:TEST%:%'
               ORDER BY key"""
        ).fetchall()
    ]


def _foux_counts(db) -> tuple[int, int, int, int]:
    rows = db.execute(
        """SELECT
             (SELECT COUNT(*) FROM followup_episodes episode
              JOIN patient_links patient ON patient.id=episode.patient_link_id
              WHERE patient.national_id GLOB 'TEST[0-9][0-9][0-9][0-9]'),
             (SELECT COUNT(*) FROM followup_episode_links link
              JOIN followup_episodes episode ON episode.episode_id=link.episode_id
              JOIN patient_links patient ON patient.id=episode.patient_link_id
              WHERE patient.national_id GLOB 'TEST[0-9][0-9][0-9][0-9]'),
             (SELECT COUNT(*) FROM followup_episode_events event
              JOIN followup_episodes episode ON episode.episode_id=event.episode_id
              JOIN patient_links patient ON patient.id=episode.patient_link_id
              WHERE patient.national_id GLOB 'TEST[0-9][0-9][0-9][0-9]'),
             (SELECT COUNT(*) FROM followup_work_item_projection projection
              JOIN patient_links patient ON patient.id=projection.patient_link_id
              WHERE patient.national_id GLOB 'TEST[0-9][0-9][0-9][0-9]')"""
    ).fetchone()
    return tuple(int(value) for value in rows)


def test_seeded_sources_are_not_misreported_as_a_genuine_empty_result(seeded_app):
    _app, _database, db = seeded_app
    assert db.execute("SELECT COUNT(*) FROM followup_tasks").fetchone()[0] > 0
    assert db.execute(
        "SELECT COUNT(*) FROM followup_work_item_projection"
    ).fetchone()[0] == 0

    readiness = FollowupUnifiedReadModelService(db).readiness()
    assert readiness["ready"] is False
    assert readiness["code"] == "PROJECTION_EMPTY_WITH_SOURCE_DATA"
    assert "دادهٔ پیگیری وجود دارد" in readiness["label"]


def test_canonical_seed_preparation_populates_unified_and_is_idempotent(
    seeded_app,
):
    _app, _database, db = seeded_app
    from src.services.clinical_engine.demo_cohort import DemoCohortService

    task_ids_before = _demo_task_ids(db)
    first = DemoSeedFollowupPreparationService(db).run(
        as_of_at=DemoCohortService.reference_at(),
        actor_username="pytest-seed-followup",
    )
    first_counts = _foux_counts(db)

    assert first["demo_followup_task_count"] == len(task_ids_before)
    assert first["demo_episode_count"] > 0
    assert first["demo_projection_count"] > 0
    assert first_counts[0] == first["demo_episode_count"]
    assert first_counts[3] == first["demo_projection_count"]

    model = FollowupUnifiedReadModelService(db).list_items(per_page=50)
    assert model["projection_ready"] is True
    assert model["total"] >= first["demo_projection_count"]
    assert model["items"]

    DemoCohortService().ensure(actor="pytest-seed-repeat", force=True)
    task_ids_after = _demo_task_ids(db)
    assert task_ids_after == task_ids_before

    second = DemoSeedFollowupPreparationService(db).run(
        as_of_at=DemoCohortService.reference_at(),
        actor_username="pytest-seed-followup-repeat",
    )
    second_counts = _foux_counts(db)
    assert second_counts == first_counts
    assert second["backfill"]["episodes_created"] == 0
    assert second["backfill"]["links_created"] == 0
    assert second["demo_projection_count"] == first["demo_projection_count"]


def test_explicit_recovery_command_prepares_existing_seeded_database(
    seeded_app, monkeypatch,
):
    _app, database, db = seeded_app
    from src.adapters.sqlite import core
    from src.services.clinical_engine.demo_cohort import DemoCohortService

    # Release the fixture connection before the recovery command opens the same DB.
    db.commit()
    core.close_connection()
    monkeypatch.setenv("FOLLOWUP_PROJECTION_SHADOW", "1")

    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "prepare_seeded_followup_view.py"
    )
    spec = importlib.util.spec_from_file_location("prepare_seeded_followup_view", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    result = module.run(
        database,
        as_of_at=DemoCohortService.reference_at().isoformat(sep=" "),
    )
    assert result["contains_phi"] is False
    assert result["demo_projection_count"] > 0
    assert result["backfill"]["episodes_created"] > 0


def test_manager_prepare_demo_cohort_also_prepares_unified(seeded_app):
    app, _database, db = seeded_app
    admin = db.execute(
        "SELECT id FROM users WHERE username='admin'"
    ).fetchone()
    assert admin

    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = int(admin["id"])

    response = client.post("/manager/clinical-engine/prepare-demo-cohort")
    assert response.status_code in {302, 303}
    assert db.execute(
        "SELECT COUNT(*) FROM followup_work_item_projection"
    ).fetchone()[0] > 0
    assert FollowupUnifiedReadModelService(db).readiness()["ready"] is True


def test_reseed_preserves_user_created_followup_for_test_patient(seeded_app):
    _app, _database, db = seeded_app
    from src.services.clinical_engine.demo_cohort import DemoCohortService

    patient_id = int(
        db.execute(
            "SELECT id FROM patient_links WHERE national_id='TEST0001'"
        ).fetchone()[0]
    )
    canonical_before = _demo_task_ids(db)
    cursor = db.execute(
        """INSERT INTO followup_tasks
           (patient_link_id, due_date, reason, detail, status, assigned_to,
            fulfillment, source_event, created_at)
           VALUES (?, '2026-08-20', 'manual',
                   'پیگیری دستی ثبت‌شده هنگام مرور UX', 'open',
                   'کاربر تست', 'in_person', 'manual-user-entry',
                   '2026-08-03 18:00:00')""",
        (patient_id,),
    )
    extra_id = int(cursor.lastrowid)
    db.commit()

    DemoCohortService().ensure(actor="pytest-seed-with-extra", force=True)
    preserved = db.execute(
        "SELECT detail, source_event FROM followup_tasks WHERE id=?",
        (extra_id,),
    ).fetchone()
    assert preserved
    assert preserved["detail"] == "پیگیری دستی ثبت‌شده هنگام مرور UX"
    assert preserved["source_event"] == "manual-user-entry"
    assert _demo_task_ids(db) == canonical_before


def test_seed_preparation_service_keeps_sql_in_repository():
    root = Path(__file__).resolve().parents[1]
    service = (
        root / "src" / "services" / "followup_orchestration"
        / "demo_seed_preparation.py"
    ).read_text(encoding="utf-8")
    repository = (
        root / "src" / "adapters" / "sqlite"
        / "demo_seed_followup_repo.py"
    ).read_text(encoding="utf-8")

    assert "DemoSeedFollowupRepository" in service
    assert "SELECT " not in service.upper()
    assert "WITH demo_patients AS" in repository

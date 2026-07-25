"""Regression guards: non-v2 surfaces may describe data, never interpret it."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(relative: str) -> str:
    return (ROOT / "src" / relative).read_text(encoding="utf-8")


def test_patient_page_has_no_insulin_or_dose_recommendation_calculator():
    page = source("templates/patients/detail.html")
    route = source("api/patients.py")
    for token in (
        "insulinModal",
        "insBtn",
        "insTarget",
        "شروع انسولین پایه",
        "گام بعدی پیشنهادی",
        "بولوس پراندیال",
        "پیشنهاد دوزِ",
    ):
        assert token not in page
    assert "dosage_guidance" not in route
    assert "TARGETS" not in route


def test_patient_trends_show_values_and_deltas_without_targets_or_risk_labels():
    page = source("templates/patients/detail.html")
    for token in (
        "ریسک بالینی",
        "کنترل کلی",
        "risk_label",
        "series[sel[0]].target",
        "FPG در محدودهٔ هدف",
        "r.level=='danger'",
        "نرمال</span>",
        "suggested_labs",
        "آزمایش‌های پیشنهادی",
    ):
        assert token not in page
    assert "تغییر عددی" in page


def test_analytics_service_is_descriptive_and_has_no_parallel_risk_engine():
    analytics = source("services/analytics_service.py")
    for token in (
        "eval_rule",
        "VitalsService",
        "def _risk(",
        "_level_from",
        "risk_weight",
        "danger_count",
        "improved =",
        '"target"',
        '"level"',
    ):
        assert token not in analytics
    assert '"projection_policy": "DESCRIPTIVE_ONLY"' in analytics


def test_patient_directory_never_classifies_or_sorts_by_clinical_values():
    route = source("api/patients.py")
    page = source("templates/patients/list.html")
    for token in (
        "def control_of",
        "def _lvl",
        "uncontrolled-first",
        "filter='uncontrolled'",
        "counts.uncontrolled",
        "p.control",
        "p.hba1c>8",
        "p.sys>=140",
        "p.fbs>=180",
        "کنترل‌نشده",
        "کنترل‌شده",
    ):
        assert token not in route + page
    assert "DESCRIPTIVE_ONLY" in route


def test_vitals_service_has_no_threshold_or_control_classification_api():
    service = source("services/vitals_service.py")
    for token in (
        "THRESHOLDS",
        "evaluate_reading",
        "control_status",
        "clinical_rules_service",
        "uncontrolled",
        "borderline",
    ):
        assert token not in service
    assert "DESCRIPTIVE_ONLY" in service


def test_administrative_automation_never_interprets_high_readings():
    engagement = source("services/engagement_service.py")
    campaign = source("services/sms/campaign_service.py")
    for token in (
        "ClinicalRulesRepository",
        "hba1c_danger",
        "systolic_danger",
        "sys_danger",
        "segment == 'uncontrolled'",
    ):
        assert token not in engagement + campaign
    assert 'event["event_key"] != "uncontrolled"' in engagement
    assert "RETIRED_CLINICAL_EVENTS" in engagement
    assert "retired_clinical_event" in engagement


def test_control_room_and_dashboard_are_administrative_only():
    service = source("services/control_room_service.py")
    room = source("templates/control_room.html")
    dashboard = source("templates/dashboard.html")
    route = source("api/dashboard.py")
    for token in (
        "CONTROL_VITALS",
        "eval_indicator",
        "ClinicalRulesRepository",
        "control_rate",
        "summary.uncontrolled",
        "کنترل‌نشده بر اساس آستانه",
        "نرخ کنترل بیماری",
        "خارج از محدوده",
    ):
        assert token not in service + room + dashboard + route
    assert '"projection_policy": "ADMINISTRATIVE_ONLY"' in service


def test_indicator_manager_cannot_edit_threshold_target_or_risk_fields():
    route = source("api/manager.py")
    repo = source("adapters/sqlite/clinical_rules_repo.py")
    page = source("templates/manager/disease_detail.html")
    for token in (
        'num("warn")',
        'num("danger")',
        'num("target")',
        'num("goal_low")',
        'num("goal_high")',
        'name="warn"',
        'name="danger"',
        'name="target"',
        'name="risk_weight"',
        '"risk_weight",',
        '"goal_low",',
        '"goal_high",',
    ):
        assert token not in route + repo + page
    assert "فراداده" in page


def test_quick_visit_does_not_display_treatment_targets():
    page = source("templates/doctor_queue/visit_quick.html")
    assert "i.target" not in page
    assert "(هدف" not in page


def test_legacy_indicator_evaluator_is_physically_retired():
    service = source("services/clinical_rules_service.py")
    assert "def evaluate(" not in service
    assert "def evaluate_key(" not in service
    for token in ("danger", "warn =", "direction ==", "larger is worse"):
        assert token not in service
    assert "Clinical Engine v2" in service


def test_pre_v2_periodic_protocol_runtime_is_physically_retired():
    manager = source("api/manager.py")
    schema = source("adapters/sqlite/schema.sql")
    assert "ProtocolService" not in manager
    assert "due_for_protocol" not in manager
    assert "CREATE TABLE IF NOT EXISTS care_protocols" not in schema
    assert "INSERT OR IGNORE INTO care_protocols" not in schema


def test_copied_database_disables_retired_clinical_engagement(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "logic-consolidation.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "logic-consolidation-test",
    })
    try:
        with app.app_context():
            db = core.get_db()
            assert db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='care_protocols'"
            ).fetchone() is None
            rows = db.execute(
                """SELECT event_key, is_active, channel FROM engagement_events
                   WHERE event_key IN (
                     'uncontrolled','monitoring_due','screening_due','vaccine_due','red_flag'
                   )"""
            ).fetchall()
            assert all(int(row["is_active"]) == 0 and row["channel"] == "off" for row in rows)
    finally:
        core._initialized = False

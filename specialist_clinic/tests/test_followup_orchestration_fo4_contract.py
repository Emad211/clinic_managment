from __future__ import annotations

from pathlib import Path


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]


def test_fo4_runtime_is_flagged_and_does_not_write_operational_sources():
    api = (
        SPECIALIST_ROOT / "src" / "api" / "unified_followups.py"
    ).read_text(encoding="utf-8")
    ownership = (
        SPECIALIST_ROOT / "src" / "services" / "followup_orchestration" /
        "ownership_service.py"
    ).read_text(encoding="utf-8")

    assert "FOLLOWUP_UNIFIED_WORKLIST_ACTIONS" in api
    assert "FOLLOWUP_AUTO_ROUTING" in api
    assert "_require_actions_flag()" in api
    assert "_require_routing_flag()" in api
    assert api.count("@bp.post") == 6
    assert "def handle" in api
    assert "def record_contact" in api
    assert "_require_structured_contact_flag()" in api
    assert "FOLLOWUP_STRUCTURED_CONTACT" in api

    normalized = ownership.upper()
    for forbidden in (
        "UPDATE FOLLOWUP_TASKS",
        "DELETE FROM FOLLOWUP_TASKS",
        "UPDATE CLINICAL_TASK_EVENTS",
        "DELETE FROM CLINICAL_TASK_EVENTS",
        "UPDATE CARE_PLAN_COMMITMENT_EVENTS",
        "DELETE FROM CARE_PLAN_COMMITMENT_EVENTS",
        "UPDATE SMS_MESSAGES",
        "UPDATE APPOINTMENTS",
    ):
        assert forbidden not in normalized

    assert 'event_type="CLAIMED"' in ownership
    assert 'event_type="ASSIGNED"' in ownership
    assert 'event_type="ROUTED"' in ownership
    assert 'self.db.execute("BEGIN IMMEDIATE")' in ownership
    assert "STALE_OWNERSHIP_FORM" in ownership
    assert "OWNERSHIP_IDEMPOTENCY_CONFLICT" in ownership
    assert "def _require_nonterminal" in ownership
    assert ownership.count("self._require_nonterminal(episode_id)") >= 4
    assert "TERMINAL_OWNERSHIP_MUTATION" in ownership


def test_fo5_contact_repository_supports_explicit_monotonic_recorded_time():
    repository = (
        SPECIALIST_ROOT / "src" / "adapters" / "sqlite" /
        "followup_operations_repo.py"
    ).read_text(encoding="utf-8")
    service = (
        SPECIALIST_ROOT / "src" / "services" / "followup_orchestration" /
        "structured_contact_service.py"
    ).read_text(encoding="utf-8")

    assert "recorded_at: datetime | str | None = None" in repository
    assert "recorded = _text(recorded_at)" in repository
    assert "datetime.fromisoformat(recorded) < datetime.fromisoformat(occurred)" in repository
    assert "recorded = occurred" in repository
    assert "recorded_at=current_time" in service


def test_fo4_ui_distinguishes_queue_from_personal_owner_without_claim_ceremony():
    list_page = (
        SPECIALIST_ROOT / "src" / "templates" / "followups" /
        "unified_worklist.html"
    ).read_text(encoding="utf-8")
    detail_page = (
        SPECIALIST_ROOT / "src" / "templates" / "followups" /
        "unified_detail.html"
    ).read_text(encoding="utf-8")

    assert "صف مسئول" in list_page
    assert "مسئول فعلی" in list_page
    assert "بدون مسئول" in list_page
    assert "unified_followups.handle" in list_page
    assert "رسیدگی و واگذاری" in detail_page
    assert "دریافت برای رسیدگی" not in detail_page
    assert "آزادکردن و بازگرداندن به صف" in detail_page
    assert "ثبت مسئول" in detail_page
    assert "actions_enabled" in detail_page
    assert "routing_enabled" in detail_page

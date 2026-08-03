from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import importlib.util
import sys

from src.services.followup_orchestration.next_action_policy import (
    FollowupNextActionPolicy,
)
from src.services.followup_orchestration.read_model_service import (
    FollowupUnifiedReadModelService,
    SLA_LABELS,
)


# Policy, SQL filtering and rendered badges must expose one effective vocabulary.
EXPECTED_SLA_STATES = (
    "FUTURE",
    "DUE_TODAY",
    "OVERDUE",
    "DUE_UNKNOWN",
    "WAITING",
    "BLOCKED",
    "TERMINAL",
)


def test_policy_output_and_filter_use_one_sla_vocabulary():
    as_of = datetime(2026, 8, 3, 12, 0, 0)
    emitted = {
        FollowupNextActionPolicy._sla("TERMINAL", None, as_of),
        FollowupNextActionPolicy._sla("BLOCKED", None, as_of),
        FollowupNextActionPolicy._sla("WAITING", None, as_of),
        FollowupNextActionPolicy._sla("ACTION_REQUIRED", None, as_of),
        FollowupNextActionPolicy._sla(
            "ACTION_REQUIRED", as_of - timedelta(minutes=1), as_of
        ),
        FollowupNextActionPolicy._sla(
            "ACTION_REQUIRED", as_of + timedelta(hours=2), as_of
        ),
        FollowupNextActionPolicy._sla(
            "ACTION_REQUIRED", as_of + timedelta(days=1), as_of
        ),
    }
    assert emitted == set(EXPECTED_SLA_STATES)
    assert tuple(SLA_LABELS) == EXPECTED_SLA_STATES

    for state in EXPECTED_SLA_STATES:
        filters = FollowupUnifiedReadModelService._normalize_filters(
            query=None,
            state_class=None,
            role=None,
            sla_state=state.lower(),
        )
        assert filters["sla"] == state

    for obsolete in ("ON_TIME", "DUE_SOON", "NONE"):
        filters = FollowupUnifiedReadModelService._normalize_filters(
            query=None,
            state_class=None,
            role=None,
            sla_state=obsolete,
        )
        assert filters["sla"] == ""


def test_unified_ui_uses_canonical_labels_and_visible_due_state():
    root = Path(__file__).resolve().parents[1]
    api = (root / "src" / "api" / "unified_followups.py").read_text(
        encoding="utf-8"
    )
    read_model = (
        root / "src" / "services" / "followup_orchestration"
        / "read_model_service.py"
    ).read_text(encoding="utf-8")
    template = (
        root / "src" / "templates" / "followups" / "unified_worklist.html"
    ).read_text(encoding="utf-8")

    assert "PROJECTION_EMPTY_WITH_SOURCE_DATA" in read_model
    assert "sla_labels=SLA_LABELS" in api
    assert "item.sla_label" in template
    assert "item.sla_tone" in template
    for obsolete in ("ON_TIME", "DUE_SOON", '"NONE"'):
        assert obsolete not in api


def _fo3_fixture_module():
    path = Path(__file__).with_name("test_followup_orchestration_fo3.py")
    spec = importlib.util.spec_from_file_location(
        "fo3_fixture_module_for_effective_sla", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_overdue_filter_uses_request_time_not_stale_persisted_state():
    module = _fo3_fixture_module()
    db = module._db()
    row = db.execute(
        """SELECT episode_id FROM followup_work_item_projection
           WHERE state_class='ACTION_REQUIRED' ORDER BY episode_id LIMIT 1"""
    ).fetchone()
    assert row
    episode_id = str(row[0])
    db.execute(
        """UPDATE followup_work_item_projection
           SET action_due_at='2026-08-03 11:00:00', sla_state='FUTURE'
           WHERE episode_id=?""",
        (episode_id,),
    )
    db.commit()

    service = FollowupUnifiedReadModelService(db)
    overdue = service.list_items(
        sla_state="OVERDUE", now=datetime(2026, 8, 3, 12, 30, 0)
    )
    assert overdue["total"] >= 1
    selected = next(
        item for item in overdue["items"] if item["episode_id"] == episode_id
    )
    assert selected["sla_state"] == "OVERDUE"
    assert selected["sla_label"] == "موعدگذشته"
    assert selected["is_overdue"] is True

    future = service.list_items(
        sla_state="FUTURE", now=datetime(2026, 8, 3, 12, 30, 0), per_page=50
    )
    assert episode_id not in {item["episode_id"] for item in future["items"]}

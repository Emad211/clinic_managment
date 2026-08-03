from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from src.services.followup_orchestration.next_action_policy import (
    FollowupNextActionPolicy,
)
from src.services.followup_orchestration.read_model_service import (
    FollowupUnifiedReadModelService,
    SLA_LABELS,
)


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

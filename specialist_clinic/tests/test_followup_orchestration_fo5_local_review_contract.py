from __future__ import annotations

from pathlib import Path


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
GUIDE = (
    SPECIALIST_ROOT
    / "docs"
    / "FOLLOWUP_ORCHESTRATION_FO5_LOCAL_UX_ACCEPTANCE.md"
)
LAUNCHER = SPECIALIST_ROOT / "scripts" / "start_fo5_local_review.ps1"


def test_fo5_local_review_guide_is_bound_to_validated_runtime_and_issue():
    guide = GUIDE.read_text(encoding="utf-8")

    assert "Issue:** `#107`" in guide
    assert "94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852" in guide
    assert "2ab1cb1ec956bb9534dea7dd383b76bbf5fb3f5c" in guide
    assert "30865955479" in guide
    assert "801 passed" in guide
    assert "54 passed" in guide
    assert "TEST_ONLY / SYNTHETIC_OR_RESETTABLE" in guide
    assert "Real patient data:** `FORBIDDEN`" in guide
    assert "FO5_UX_ACCEPTED = true|false" in guide
    assert "FO-6 remains blocked" in guide


def test_fo5_review_launcher_uses_canonical_database_and_bounded_flags():
    launcher = LAUNCHER.read_text(encoding="utf-8")

    required_on = (
        "FOLLOWUP_EPISODES_ENABLED",
        "FOLLOWUP_PROJECTION_SHADOW",
        "FOLLOWUP_UNIFIED_WORKLIST_READONLY",
        "FOLLOWUP_UNIFIED_WORKLIST_ACTIONS",
        "FOLLOWUP_AUTO_ROUTING",
        "FOLLOWUP_STRUCTURED_CONTACT",
    )
    required_off = (
        "FOLLOWUP_SMS_AUTO_GUARDED",
        "FOLLOWUP_APPOINTMENT_SYNC",
        "FOLLOWUP_EVIDENCE_ASSIST",
        "FOLLOWUP_AUTOMATION_HEALTH",
    )
    for flag in required_on + required_off:
        assert flag in launcher

    assert '"SPECIALIST_DB_PATH"' in launcher
    assert "SPECIALIST_DATABASE_PATH" not in launcher
    assert "prepare_seeded_followup_view.py" in launcher
    assert "Copy-Item" in launcher
    assert "fo5-local-review-$Stamp.db" in launcher
    assert "PreviousValues" in launcher
    assert "94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852" in launcher
    assert "Acceptance Issue: #107" in launcher

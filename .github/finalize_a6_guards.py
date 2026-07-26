from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A6 guard anchor missing in {relative}: {old[:220]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Freeze captures a materialized consent event, never a virtual UI default.
replace_once(
    "specialist_clinic/src/services/campaign_economics_service.py",
    '''            consent = governance.summary(patient_id)[purpose]
            try:
                phone = canonicalize_iran_mobile(candidate.get("phone_number"))
''',
    '''            consent_decision = governance.decision(patient_id, purpose)
            consent = {
                "id": consent_decision.event_id,
                "decision": consent_decision.decision,
                "allowed": consent_decision.allowed,
            }
            try:
                phone = canonicalize_iran_mobile(candidate.get("phone_number"))
''',
)

# A legacy/backfilled cohort is visible for history but can never be executed.
replace_once(
    "specialist_clinic/src/services/campaign_economics_service.py",
    '''            snapshot = self.repository.audience_snapshot(campaign_id)
            execution_id = (
                str(snapshot["execution_id"])
                if snapshot
                else "campaign-exec-" + uuid.uuid4().hex
            )
''',
    '''            snapshot = self.repository.audience_snapshot(campaign_id)
            if snapshot and snapshot.get("source_code") != "NEW_FROZEN":
                raise CampaignExecutionError("LEGACY_AUDIENCE_NOT_EXECUTABLE")
            execution_id = (
                str(snapshot["execution_id"])
                if snapshot
                else "campaign-exec-" + uuid.uuid4().hex
            )
''',
)

# Missing configured direct cost is an explicit blocker, including zero accepted messages
# only after the execution has actually created messages.
replace_once(
    "specialist_clinic/src/adapters/sqlite/campaign_economics_repo.py",
    '''        cost_complete = (
            provider_accepted_messages == costs["costed_messages"]
            if provider_accepted_messages
            else True
        )
''',
    '''        cost_complete = (
            provider_accepted_messages == costs["costed_messages"]
            if provider_accepted_messages
            else messages["messages"] == 0
        )
''',
)

Path(__file__).unlink()

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "specialist_clinic/src/services/campaign_economics_service.py"
text = path.read_text(encoding="utf-8")

# Runs after finalize_a6_guards.py.
old_signature = '''    def freeze_audience(
        self,
        campaign_id: int,
        *,
        execution_id: str,
        actor_username: str,
    ) -> dict:
'''
new_signature = '''    def freeze_audience(
        self,
        campaign_id: int,
        *,
        execution_id: str,
        actor_username: str,
        commit: bool = True,
    ) -> dict:
'''
if new_signature not in text:
    if old_signature not in text:
        raise AssertionError("A6 freeze signature anchor missing")
    text = text.replace(old_signature, new_signature, 1)

old_consent = '''            consent_decision = governance.decision(patient_id, purpose)
            consent = {
                "id": consent_decision.event_id,
                "decision": consent_decision.decision,
                "allowed": consent_decision.allowed,
            }
'''
new_consent = '''            consent = governance.repository.ensure_patient_defaults(
                patient_id,
                actor_username=actor_username,
                commit=False,
            )[purpose]
            consent = {
                **consent,
                "allowed": consent["decision"] == "GRANTED",
            }
'''
if new_consent not in text:
    if old_consent not in text:
        raise AssertionError("A6 materialized consent anchor missing")
    text = text.replace(old_consent, new_consent, 1)

old_create_tail = '''            members=members,
            actor_username=actor_username,
        )
'''
new_create_tail = '''            members=members,
            actor_username=actor_username,
            commit=commit,
        )
'''
freeze_start = text.index("    def freeze_audience(")
prepare_start = text.index("    def prepare_execution(", freeze_start)
freeze_block = text[freeze_start:prepare_start]
if new_create_tail not in freeze_block:
    if old_create_tail not in freeze_block:
        raise AssertionError("A6 audience commit anchor missing")
    freeze_block = freeze_block.replace(old_create_tail, new_create_tail, 1)
    text = text[:freeze_start] + freeze_block + text[prepare_start:]

start = text.index("    def prepare_execution(")
end = text.index("    def projected_wallet_balance(", start)
replacement = '''    def prepare_execution(
        self,
        campaign_id: int,
        *,
        actor_username: str,
    ) -> dict:
        campaign = self.repository.campaign(campaign_id)
        if not campaign:
            raise LookupError("campaign not found")
        current = self.repository.current_lifecycle(campaign_id)
        if current is None:
            current = self.register_campaign(
                campaign_id, actor_username=actor_username
            )
        if current["status"] in {"COMPLETED", "CANCELLED"}:
            raise CampaignExecutionError(
                f"campaign is terminal: {current['status']}"
            )
        snapshot = self.repository.audience_snapshot(campaign_id)
        if snapshot and snapshot.get("source_code") != "NEW_FROZEN":
            raise CampaignExecutionError("LEGACY_AUDIENCE_NOT_EXECUTABLE")

        if current["status"] in {"SENDING", "AWAITING_DELIVERY"}:
            if not snapshot or snapshot["execution_id"] != current["execution_id"]:
                raise CampaignExecutionError(
                    "ACTIVE_CAMPAIGN_AUDIENCE_MISSING_OR_MISMATCHED"
                )
            return {
                "campaign": campaign,
                "lifecycle": current,
                "snapshot": snapshot,
                "members": self.repository.audience_members(
                    campaign_id, assignment="TREATED"
                ),
            }
        if current["status"] not in {
            "DRAFT", "SCHEDULED", "FAILED", "ENTERED_IN_ERROR", "PREPARING"
        }:
            raise CampaignExecutionError(
                f"campaign cannot be prepared from {current['status']}"
            )

        execution_id = (
            str(snapshot["execution_id"])
            if snapshot
            else str(current.get("execution_id") or "campaign-exec-" + uuid.uuid4().hex)
        )
        db = self._db()
        if db.in_transaction:
            raise CampaignExecutionError("CALLER_TRANSACTION_ACTIVE")
        db.execute("BEGIN IMMEDIATE")
        try:
            current = self.repository.current_lifecycle(campaign_id)
            if current["status"] != "PREPARING":
                current = self.repository.append_lifecycle(
                    campaign_id=campaign_id,
                    status="PREPARING",
                    actor_username=actor_username,
                    execution_id=execution_id,
                    expected_current_event_id=int(current["id"]),
                    idempotency_key=(
                        f"campaign:{campaign_id}:{execution_id}:preparing"
                    ),
                    note=(
                        "Execution preparation started; audience and lifecycle "
                        "advance atomically."
                    ),
                    commit=False,
                )
            snapshot = self.freeze_audience(
                campaign_id,
                execution_id=execution_id,
                actor_username=actor_username,
                commit=False,
            )
            current = self.repository.current_lifecycle(campaign_id)
            if current["status"] == "PREPARING":
                current = self.repository.append_lifecycle(
                    campaign_id=campaign_id,
                    status="SENDING",
                    actor_username=actor_username,
                    execution_id=execution_id,
                    expected_current_event_id=int(current["id"]),
                    idempotency_key=(
                        f"campaign:{campaign_id}:{execution_id}:sending"
                    ),
                    note=(
                        "Frozen treated audience is ready for governed submission."
                    ),
                    commit=False,
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {
            "campaign": campaign,
            "lifecycle": current,
            "snapshot": snapshot,
            "members": self.repository.audience_members(
                campaign_id, assignment="TREATED"
            ),
        }

'''
text = text[:start] + replacement + text[end:]
path.write_text(text, encoding="utf-8")
Path(__file__).unlink()

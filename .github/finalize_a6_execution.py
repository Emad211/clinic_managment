from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A6 execution target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(
            f"A6 execution anchor missing in {relative}: {old[:220]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# A6 claim is only a short-lived concurrency lease; mutable campaign.status is not truth.
replace_once(
    "specialist_clinic/src/services/sms/campaign_execution_service.py",
    '''from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository
''',
    '''from src.adapters.sqlite.campaign_execution_claim_repo import (
    CampaignExecutionClaimRepository,
)
from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository
''',
)
replace_once(
    "specialist_clinic/src/services/sms/campaign_execution_service.py",
    '''        self.sms = SmsRepository()
        self.economics = CampaignEconomicsService()
''',
    '''        self.sms = SmsRepository()
        self.claims = CampaignExecutionClaimRepository()
        self.economics = CampaignEconomicsService()
''',
)
replace_once(
    "specialist_clinic/src/services/sms/campaign_execution_service.py",
    '''        if not self.sms.claim_campaign(campaign_id, claim_token):
''',
    '''        if not self.claims.claim(campaign_id, claim_token):
''',
)
replace_once(
    "specialist_clinic/src/services/sms/campaign_execution_service.py",
    '''            self.sms.release_campaign(campaign_id, claim_token, compat)
''',
    '''            self.claims.release(campaign_id, claim_token)
''',
)
replace_once(
    "specialist_clinic/src/services/sms/campaign_execution_service.py",
    '''            self.sms.release_campaign(campaign_id, claim_token, "failed")
''',
    '''            self.claims.release(campaign_id, claim_token)
''',
)
# Remove compatibility variable after claim release no longer accepts it.
replace_once(
    "specialist_clinic/src/services/sms/campaign_execution_service.py",
    '''            current_status = str(reconciled["lifecycle"]["status"])
            compat = {
                "COMPLETED": "done",
                "FAILED": "failed",
                "CANCELLED": "cancelled",
            }.get(current_status, "sending")
            self.claims.release(campaign_id, claim_token)
''',
    '''            self.claims.release(campaign_id, claim_token)
''',
)

# Legacy campaign snapshots are untrusted and never receive new wallet/cost mutations.
replace_once(
    "specialist_clinic/src/services/campaign_economics_service.py",
    '''        campaign = self.repository.campaign(campaign_id)
        if not campaign:
            raise LookupError("campaign not found")
        for message in self.repository.campaign_messages(campaign_id):
''',
    '''        campaign = self.repository.campaign(campaign_id)
        if not campaign:
            raise LookupError("campaign not found")
        snapshot = self.repository.audience_snapshot(campaign_id)
        trusted_execution = bool(
            snapshot and snapshot.get("source_code") == "NEW_FROZEN"
        )
        if trusted_execution:
            for message in self.repository.campaign_messages(campaign_id):
                status = str(message.get("status") or "")
                if status in {"accepted", "delivered", "sent"}:
                    self.record_cost_for_message(
                        int(message["id"]), actor_username=actor_username
                    )
                    self.ensure_wallet_grant(
                        int(message["id"]), actor_username=actor_username
                    )
                if str(message.get("delivery_status") or "") in {
                    "NumberBlackListed", "OperatorBlackList", "Canceled", "Failed",
                    "Undelivered", "StatusUnknown", "SubmissionUnknown",
                }:
                    self.compensate_wallet_for_message(
                        int(message["id"]), actor_username=actor_username
                    )
        for message in []:
''',
)
# Delete the old loop body, now made unreachable by the explicit empty iterator.
service_path = target("specialist_clinic/src/services/campaign_economics_service.py")
service = service_path.read_text(encoding="utf-8")
old_unreachable = '''        for message in []:
            status = str(message.get("status") or "")
            if status in {"accepted", "delivered", "sent"}:
                self.record_cost_for_message(
                    int(message["id"]), actor_username=actor_username
                )
                self.ensure_wallet_grant(
                    int(message["id"]), actor_username=actor_username
                )
            if str(message.get("delivery_status") or "") in {
                "NumberBlackListed", "OperatorBlackList", "Canceled", "Failed",
                "Undelivered", "StatusUnknown", "SubmissionUnknown",
            }:
                self.compensate_wallet_for_message(
                    int(message["id"]), actor_username=actor_username
                )
'''
if old_unreachable in service:
    service = service.replace(old_unreachable, "", 1)
    service_path.write_text(service, encoding="utf-8")

# Keep the public seam used by scheduler/routes/tests, but delegate all campaign execution.
campaign_path = target("specialist_clinic/src/services/sms/campaign_service.py")
text = campaign_path.read_text(encoding="utf-8")
start = text.index("def run_campaign(")
end = text.index("\ndef send_single(", start)
wrapper = '''def run_campaign(campaign_id: int) -> dict:
    """Execute one campaign through the immutable A6 contract."""
    from src.services.sms.campaign_execution_service import (
        GovernedCampaignExecutionService,
    )

    return GovernedCampaignExecutionService().run(int(campaign_id))


'''
text = text[:start] + wrapper + text[end + 1 :]
campaign_path.write_text(text, encoding="utf-8")

# Delivery reconciliation also reconciles wallet compensation, costs and lifecycle.
replace_once(
    "specialist_clinic/src/services/sms/delivery_service.py",
    '''        for campaign_id_value in affected:
            self.legacy_repo.refresh_campaign_counts(campaign_id_value)
        return {
            "checked": checked,
            "updated": updated,
            "errors": errors,
            "provider_errors": dict(provider_errors),
        }
''',
    '''        lifecycle_errors = 0
        for campaign_id_value in affected:
            self.legacy_repo.refresh_campaign_counts(campaign_id_value)
            try:
                from src.services.campaign_economics_service import (
                    CampaignEconomicsService,
                )
                CampaignEconomicsService().reconcile_campaign_state(
                    int(campaign_id_value),
                    actor_username="system:sms-delivery-reconciliation",
                )
            except Exception:
                lifecycle_errors += 1
                logger.exception(
                    "campaign economics reconciliation failed campaign=%s",
                    campaign_id_value,
                )
        return {
            "checked": checked,
            "updated": updated,
            "errors": errors + lifecycle_errors,
            "provider_errors": dict(provider_errors),
            "campaign_lifecycle_errors": lifecycle_errors,
        }
''',
)

# Revenue dashboard consumes explicit A6 projection, never time-window estimates.
revenue_path = target("specialist_clinic/src/services/revenue_service.py")
revenue = revenue_path.read_text(encoding="utf-8")
start = revenue.index("    def campaign_revenue(")
end = revenue.index("    def campaign_incrementality(", start)
replacement = '''    def campaign_revenue(self, ids_hint: list[int] | None = None) -> dict:
        """Campaign economics from explicit Journey/invoice lineage only."""
        from src.adapters.sqlite.campaign_economics_repo import (
            CampaignEconomicsRepository,
        )

        repository = CampaignEconomicsRepository()
        rows = []
        attributable_total = 0
        direct_cost_total = 0
        net_total = 0
        all_ready = True
        for campaign in self.finance.campaigns():
            projection = repository.campaign_projection(int(campaign["id"]))
            ready = bool(
                projection["safe_to_sum"]
                and projection["measurement_status"] == "READY"
            )
            all_ready = all_ready and ready
            if ready:
                attributable_total += int(projection["finance"]["collected"])
                direct_cost_total += int(projection["costs"]["direct_cost"])
                net_total += int(projection["net_contribution"])
            rows.append(
                {
                    "id": int(campaign["id"]),
                    "name": campaign["name"],
                    "type": campaign["campaign_type"],
                    "recipients": int(
                        projection["audience"].get("eligible_count") or 0
                    ),
                    "treated": int(
                        projection["audience"].get("treated_count") or 0
                    ),
                    "control": int(
                        projection["audience"].get("control_count") or 0
                    ),
                    "accepted": int(
                        projection["messages"].get("provider_accepted") or 0
                    ),
                    "sent": int(
                        projection["messages"].get("provider_accepted") or 0
                    ),
                    "delivered": int(projection["messages"]["delivered"]),
                    "positive_responses": int(
                        projection["responses"]["positive"]
                    ),
                    "journeys": int(projection["attributions"]["journeys"]),
                    "revenue": (
                        int(projection["finance"]["collected"])
                        if ready else None
                    ),
                    "invoices": int(projection["finance"]["invoices"]),
                    "direct_cost": (
                        int(projection["costs"]["direct_cost"])
                        if ready else None
                    ),
                    "net_contribution": (
                        int(projection["net_contribution"]) if ready else None
                    ),
                    "roi_percent": projection["roi_percent"] if ready else None,
                    "measurement_status": projection["measurement_status"],
                    "safe_to_sum": ready,
                }
            )
        safe_to_sum = bool(rows) and all_ready
        return {
            "rows": rows,
            "attributed_total": attributable_total if safe_to_sum else 0,
            "direct_cost_total": direct_cost_total if safe_to_sum else 0,
            "net_contribution_total": net_total if safe_to_sum else 0,
            "credit_distributed": 0,
            "window_days": None,
            "safe_to_sum": safe_to_sum,
            "measurement_status": (
                "READY" if safe_to_sum else "CAMPAIGN_ECONOMICS_INCOMPLETE"
            ),
            "policy_version": "EXPLICIT_CAMPAIGN_JOURNEY_ROI_V1",
        }

'''
revenue = revenue[:start] + replacement + revenue[end:]
revenue = revenue.replace(
    '''    def campaign_incrementality(self, campaign_id: int) -> dict | None:
        return None
''',
    '''    def campaign_incrementality(self, campaign_id: int) -> dict | None:
        # No causal claim is published merely because a control group exists.
        # A6 reports explicit attribution and ROI; causal inference needs a separate,
        # adequately powered analysis contract.
        return None
''',
    1,
)
revenue_path.write_text(revenue, encoding="utf-8")

Path(__file__).unlink()

"""Governed A6 campaign execution over a frozen immutable audience."""
from __future__ import annotations

import uuid

from src.adapters.sqlite.campaign_execution_claim_repo import (
    CampaignExecutionClaimRepository,
)
from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository
from src.adapters.sqlite.sms_repo import SmsRepository
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.services.campaign_economics_service import (
    CampaignEconomicsService,
    CampaignExecutionError,
)
from src.services.sms.compliance import sanitize
from src.services.sms.governance_service import (
    SmsConsentDenied,
    SmsGovernanceService,
    canonicalize_iran_mobile,
)
from src.services.sms.guardrail_service import (
    SmsGuardrailDenied,
    SmsGuardrailService,
)
from src.services.sms.provider import OutgoingSms, UnconfiguredProvider, get_provider


class GovernedCampaignExecutionService:
    def __init__(self):
        self.sms = SmsRepository()
        self.claims = CampaignExecutionClaimRepository()
        self.economics = CampaignEconomicsService()
        self.dispatch = SmsDispatchRepository()
        self.governance = SmsGovernanceService()
        self.guardrails = SmsGuardrailService(self.sms)

    @staticmethod
    def _fa_num(number: int) -> str:
        rendered = f"{int(number):,}"
        return rendered.translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹،"))

    @classmethod
    def personalize(
        cls,
        body: str,
        *,
        name: str,
        credit: int = 0,
        balance: int = 0,
    ) -> str:
        output = str(body or "")
        output = output.replace("{name}", name or "بیمار")
        output = output.replace("{credit}", cls._fa_num(credit))
        output = output.replace("{balance}", cls._fa_num(balance))
        return output

    def _message_body(self, campaign: dict, member: dict) -> str:
        credit = int(campaign.get("credit_amount") or 0)
        balance = WalletRepository().get_balance(int(member["patient_link_id"]))
        current_grant = self.economics.repository.current_wallet_grant(
            int(campaign["id"]), int(member["patient_link_id"])
        )
        if campaign.get("campaign_type") == "wallet_credit" and credit > 0:
            if not current_grant or current_grant.get("status") != "ACTIVE":
                balance += credit
        return sanitize(
            self.personalize(
                campaign.get("body") or "",
                name=member.get("full_name") or "بیمار",
                credit=credit,
                balance=balance,
            )
        )

    def run(
        self,
        campaign_id: int,
        *,
        actor_username: str = "system:campaign-execution",
    ) -> dict:
        if self.guardrails.is_outside_allowed_hours():
            return {
                "error": "outside allowed SMS hours",
                "reason": "quiet",
                "total": 0,
            }
        prepared = self.economics.prepare_execution(
            int(campaign_id), actor_username=actor_username
        )
        campaign = prepared["campaign"]
        lifecycle = prepared["lifecycle"]
        execution_id = str(lifecycle["execution_id"])
        provider = get_provider()
        if isinstance(provider, UnconfiguredProvider):
            current = self.economics.repository.current_lifecycle(campaign_id)
            if current and current["status"] in {"PREPARING", "SENDING"}:
                self.economics.repository.append_lifecycle(
                    campaign_id=campaign_id,
                    status="FAILED",
                    actor_username=actor_username,
                    execution_id=execution_id,
                    outcome_code="PROVIDER_UNCONFIGURED",
                    expected_current_event_id=int(current["id"]),
                    idempotency_key=(
                        f"campaign:{campaign_id}:{execution_id}:"
                        "failed:provider-unconfigured"
                    ),
                )
            return {
                "error": "provider not configured",
                "reason": "provider_unconfigured",
                "total": len(prepared["members"]),
            }

        claim_token = uuid.uuid4().hex
        if not self.claims.claim(campaign_id, claim_token):
            return {
                "error": "campaign already running",
                "duplicate": True,
            }

        purpose = self.economics.purpose_for_campaign(campaign)
        message_type = (
            "Informational" if purpose == "CARE" else "PromotionalToCustomers"
        )
        claimed: list[tuple[int, str, str, str]] = []
        consent_skipped = invalid_phone = already_processed = guardrail_skipped = 0
        try:
            for member in prepared["members"]:
                patient_id = int(member["patient_link_id"])
                try:
                    consent = self.governance.require_allowed(
                        patient_link_id=patient_id,
                        purpose=purpose,
                    )
                    phone = canonicalize_iran_mobile(
                        member.get("recipient_canonical")
                        or member.get("phone_number")
                    )
                except SmsConsentDenied:
                    consent_skipped += 1
                    continue
                except ValueError:
                    invalid_phone += 1
                    continue
                try:
                    self.guardrails.require_allowed(patient_id)
                except SmsGuardrailDenied:
                    guardrail_skipped += 1
                    continue

                body = self._message_body(campaign, member)
                key = (
                    f"campaign:{campaign_id}:execution:{execution_id}:"
                    f"patient:{patient_id}"
                )
                message_id, _created = self.dispatch.create_message(
                    campaign_id=campaign_id,
                    patient_link_id=patient_id,
                    recipient=phone,
                    body=body,
                    provider_name=provider.provider_name,
                    idempotency_key=key,
                    source_type="campaign",
                    source_ref=str(campaign_id),
                    purpose=purpose,
                    consent_event_id=int(consent.event_id),
                    consent_decision=consent.decision,
                    source_policy="A6_FROZEN_AUDIENCE_CURRENT_CONSENT",
                    created_by=actor_username,
                )
                if self.dispatch.claim_submission(message_id):
                    claimed.append((message_id, key, phone, body))
                else:
                    existing = self.dispatch.get(message_id) or {}
                    if existing.get("status") in {"accepted", "delivered", "sent"}:
                        self.economics.record_cost_for_message(
                            message_id, actor_username=actor_username
                        )
                        self.economics.ensure_wallet_grant(
                            message_id, actor_username=actor_username
                        )
                        already_processed += 1

            accepted = failed = pending = 0
            for start in range(0, len(claimed), 100):
                chunk = claimed[start : start + 100]
                result = provider.send_batch(
                    [
                        OutgoingSms(ref_id=key, recipient=phone, body=body)
                        for _message_id, key, phone, body in chunk
                    ],
                    message_type=message_type,
                )
                by_ref = {item.ref_id: item for item in result.items}
                for message_id, key, _phone, _body in chunk:
                    item = by_ref.get(key)
                    if item is None:
                        self.dispatch.record_submission(
                            message_id,
                            ok=False,
                            pending=True,
                            delivery_status="SubmissionUnknown",
                            error="پاسخ متناظر از سرویس‌دهنده دریافت نشد",
                        )
                        pending += 1
                        continue
                    self.dispatch.record_submission(
                        message_id,
                        ok=item.ok,
                        pending=item.pending,
                        provider_request_id=item.provider_request_id,
                        provider_msgid=item.provider_msgid,
                        delivery_status=item.delivery_status,
                        error=item.error,
                        retryable=item.retryable,
                    )
                    if item.ok:
                        self.economics.record_cost_for_message(
                            message_id, actor_username=actor_username
                        )
                        self.economics.ensure_wallet_grant(
                            message_id, actor_username=actor_username
                        )
                        accepted += 1
                    elif item.pending:
                        pending += 1
                    else:
                        failed += 1

            self.sms.refresh_campaign_counts(campaign_id)
            reconciled = self.economics.reconcile_campaign_state(
                campaign_id, actor_username=actor_username
            )
            current_status = str(reconciled["lifecycle"]["status"])
            compat = {
                "COMPLETED": "done",
                "FAILED": "failed",
                "CANCELLED": "cancelled",
            }.get(current_status, "sending")
            self.claims.release(campaign_id, claim_token)
            return {
                "total": int(prepared["snapshot"]["treated_count"]),
                "accepted": accepted + already_processed,
                "sent": accepted + already_processed,
                "failed": failed,
                "pending": pending,
                "control": int(prepared["snapshot"]["control_count"]),
                "excluded": int(prepared["snapshot"]["excluded_count"]),
                "consent_skipped_after_freeze": consent_skipped,
                "invalid_phone_after_freeze": invalid_phone,
                "guardrail_skipped": guardrail_skipped,
                "lifecycle": reconciled["lifecycle"],
                "measurement_status": reconciled["projection"][
                    "measurement_status"
                ],
            }
        except Exception as exc:
            current = self.economics.repository.current_lifecycle(campaign_id)
            if current and current["status"] in {"PREPARING", "SENDING"}:
                try:
                    self.economics.repository.append_lifecycle(
                        campaign_id=campaign_id,
                        status="FAILED",
                        actor_username=actor_username,
                        execution_id=execution_id,
                        outcome_code="EXECUTION_EXCEPTION",
                        expected_current_event_id=int(current["id"]),
                        idempotency_key=(
                            f"campaign:{campaign_id}:{execution_id}:"
                            "failed:execution-exception"
                        ),
                        note=str(exc)[:500],
                    )
                except Exception:
                    pass
            self.sms.release_campaign(campaign_id, claim_token, "failed")
            raise


__all__ = ["GovernedCampaignExecutionService"]

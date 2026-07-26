"""A6 orchestration for immutable campaign execution and explicit ROI attribution."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import math
import sqlite3
import uuid

from src.adapters.sqlite.campaign_economics_repo import (
    CampaignEconomicsConflict,
    CampaignEconomicsRepository,
    CampaignEconomicsValidationError,
)
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository
from src.adapters.sqlite.sms_governance_repo import SmsGovernanceRepository
from src.adapters.sqlite.sms_repo import SmsRepository
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.common.utils import iran_now
from src.services.sms.governance_service import (
    SmsConsentDenied,
    SmsGovernanceService,
    canonicalize_iran_mobile,
)


class CampaignExecutionError(RuntimeError):
    pass


class CampaignEconomicsService:
    def __init__(
        self,
        *,
        repository: CampaignEconomicsRepository | None = None,
        db: sqlite3.Connection | None = None,
        clock=None,
    ):
        self._connection = db
        self.repository = repository or CampaignEconomicsRepository(db)
        self.clock = clock or iran_now

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    @staticmethod
    def purpose_for_campaign(campaign: dict) -> str:
        return "CARE" if campaign.get("campaign_type") == "reminder" else "MARKETING"

    @staticmethod
    def estimate_sms_parts(body: str) -> int:
        """Conservative GSM/Unicode segmentation estimate, clearly labeled estimated."""
        text = str(body or "")
        if not text:
            return 1
        unicode_message = any(ord(char) > 127 for char in text)
        single = 70 if unicode_message else 160
        multipart = 67 if unicode_message else 153
        return 1 if len(text) <= single else int(math.ceil(len(text) / multipart))

    def configured_part_cost(self, provider_name: str) -> int | None:
        key = f"sms_cost_per_part_{str(provider_name).lower()}_toman"
        raw = SmsRepository().get_setting(key)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _candidate_rows(self, segment: str) -> list[dict]:
        db = self._db()
        base = (
            "SELECT DISTINCT patient.id,patient.full_name,patient.phone_number,"
            "patient.accounting_patient_id FROM patient_links patient"
        )
        where = (
            "patient.is_active=1 AND COALESCE(patient.enrolled_by,'')<>'seed'"
        )
        if segment == "all":
            sql, params = f"{base} WHERE {where}", ()
        elif segment in {"diabetes", "hypertension"}:
            sql = (
                f"{base} JOIN patient_conditions pc "
                "ON pc.patient_link_id=patient.id AND pc.is_active=1 "
                "JOIN conditions condition ON condition.id=pc.condition_id "
                f"WHERE {where} AND condition.code=?"
            )
            params = (segment,)
        elif segment == "lapsed":
            sql = f"""{base} WHERE {where} AND NOT EXISTS (
                SELECT 1 FROM vital_readings vital
                WHERE vital.patient_link_id=patient.id
                  AND vital.measured_at>=datetime(
                      'now','+3 hours','+30 minutes','-120 days'
                  )
            )"""
            params = ()
        elif segment == "refill_due":
            sql = f"""{base} JOIN patient_medications medication
                ON medication.patient_link_id=patient.id AND medication.is_active=1
                WHERE {where} AND medication.refill_due_date IS NOT NULL
                  AND medication.refill_due_date<=date(
                      'now','+3 hours','+30 minutes','+7 days'
                  )"""
            params = ()
        else:
            raise CampaignEconomicsValidationError("unknown campaign segment")
        return [dict(row) for row in db.execute(sql, params).fetchall()]

    def register_campaign(
        self,
        campaign_id: int,
        *,
        actor_username: str,
    ) -> dict:
        campaign = self.repository.campaign(campaign_id)
        if not campaign:
            raise LookupError("campaign not found")
        current = self.repository.current_lifecycle(campaign_id)
        if current:
            return current
        scheduled = bool(campaign.get("scheduled_at"))
        return self.repository.append_lifecycle(
            campaign_id=campaign_id,
            status="SCHEDULED" if scheduled else "DRAFT",
            actor_username=actor_username,
            idempotency_key=f"campaign-created:{campaign_id}",
            note="Campaign definition registered in immutable lifecycle.",
        )

    def freeze_audience(
        self,
        campaign_id: int,
        *,
        execution_id: str,
        actor_username: str,
    ) -> dict:
        existing = self.repository.audience_snapshot(campaign_id)
        if existing:
            return existing
        campaign = self.repository.campaign(campaign_id)
        if not campaign:
            raise LookupError("campaign not found")
        purpose = self.purpose_for_campaign(campaign)
        candidates = self._candidate_rows(str(campaign.get("segment") or "all"))
        governance = SmsGovernanceService()
        seed = hashlib.sha256(
            f"campaign:{campaign_id}:{execution_id}:{campaign.get('created_at')}".encode(
                "utf-8"
            )
        ).hexdigest()
        eligible: list[dict] = []
        excluded: list[dict] = []
        for candidate in candidates:
            patient_id = int(candidate["id"])
            consent = governance.summary(patient_id)[purpose]
            try:
                phone = canonicalize_iran_mobile(candidate.get("phone_number"))
            except ValueError:
                excluded.append(
                    {
                        "patient_link_id": patient_id,
                        "accounting_patient_id": candidate.get("accounting_patient_id"),
                        "assignment": "EXCLUDED",
                        "eligibility": "INVALID_PHONE",
                        "finance_scope": (
                            "ATTRIBUTABLE"
                            if candidate.get("accounting_patient_id") is not None
                            else "NO_ACCOUNTING_LINK"
                        ),
                        "consent_event_id": consent.get("id"),
                        "consent_decision": consent["decision"],
                        "recipient_canonical": None,
                        "exclusion_reason": "INVALID_PHONE",
                    }
                )
                continue
            if not consent["allowed"]:
                excluded.append(
                    {
                        "patient_link_id": patient_id,
                        "accounting_patient_id": candidate.get("accounting_patient_id"),
                        "assignment": "EXCLUDED",
                        "eligibility": "CONSENT_REVOKED",
                        "finance_scope": (
                            "ATTRIBUTABLE"
                            if candidate.get("accounting_patient_id") is not None
                            else "NO_ACCOUNTING_LINK"
                        ),
                        "consent_event_id": consent.get("id"),
                        "consent_decision": consent["decision"],
                        "recipient_canonical": phone,
                        "exclusion_reason": f"{purpose}_CONSENT_REVOKED",
                    }
                )
                continue
            eligible.append(
                {
                    "patient_link_id": patient_id,
                    "accounting_patient_id": candidate.get("accounting_patient_id"),
                    "eligibility": "ELIGIBLE",
                    "finance_scope": (
                        "ATTRIBUTABLE"
                        if candidate.get("accounting_patient_id") is not None
                        else "NO_ACCOUNTING_LINK"
                    ),
                    "consent_event_id": consent.get("id"),
                    "consent_decision": consent["decision"],
                    "recipient_canonical": phone,
                    "exclusion_reason": None,
                    "rank_hash": hashlib.sha256(
                        f"{seed}:{patient_id}".encode("utf-8")
                    ).hexdigest(),
                }
            )
        eligible.sort(key=lambda row: (row["rank_hash"], row["patient_link_id"]))
        holdout_percent = int(campaign.get("holdout_percent") or 0)
        control_count = 0
        if holdout_percent > 0 and len(eligible) >= 2:
            control_count = max(1, round(len(eligible) * holdout_percent / 100.0))
            control_count = min(control_count, len(eligible) - 1)
        members: list[dict] = []
        for rank, member in enumerate(eligible, start=1):
            members.append(
                {
                    **{key: value for key, value in member.items() if key != "rank_hash"},
                    "assignment": "CONTROL" if rank <= control_count else "TREATED",
                    "assigned_rank": rank,
                }
            )
        for offset, member in enumerate(
            sorted(excluded, key=lambda row: row["patient_link_id"]),
            start=len(members) + 1,
        ):
            members.append({**member, "assigned_rank": offset})
        return self.repository.create_audience_snapshot(
            campaign_id=campaign_id,
            execution_id=execution_id,
            source_code="NEW_FROZEN",
            segment_key=str(campaign.get("segment") or "all"),
            purpose=purpose,
            holdout_percent=holdout_percent,
            random_seed=seed,
            members=members,
            actor_username=actor_username,
        )

    def prepare_execution(
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
            current = self.register_campaign(campaign_id, actor_username=actor_username)
        if current["status"] in {"COMPLETED", "CANCELLED"}:
            raise CampaignExecutionError(
                f"campaign is terminal: {current['status']}"
            )
        if current["status"] not in {"DRAFT", "SCHEDULED", "FAILED", "ENTERED_IN_ERROR"}:
            if current["status"] in {"PREPARING", "SENDING", "AWAITING_DELIVERY"}:
                execution_id = str(current["execution_id"])
            else:
                raise CampaignExecutionError(
                    f"campaign cannot be prepared from {current['status']}"
                )
        else:
            snapshot = self.repository.audience_snapshot(campaign_id)
            execution_id = (
                str(snapshot["execution_id"])
                if snapshot
                else "campaign-exec-" + uuid.uuid4().hex
            )
            current = self.repository.append_lifecycle(
                campaign_id=campaign_id,
                status="PREPARING",
                actor_username=actor_username,
                execution_id=execution_id,
                expected_current_event_id=int(current["id"]),
                idempotency_key=f"campaign:{campaign_id}:{execution_id}:preparing",
                note="Execution preparation started; audience will be frozen once.",
            )
        snapshot = self.freeze_audience(
            campaign_id,
            execution_id=execution_id,
            actor_username=actor_username,
        )
        current = self.repository.current_lifecycle(campaign_id)
        if current["status"] == "PREPARING":
            current = self.repository.append_lifecycle(
                campaign_id=campaign_id,
                status="SENDING",
                actor_username=actor_username,
                execution_id=execution_id,
                expected_current_event_id=int(current["id"]),
                idempotency_key=f"campaign:{campaign_id}:{execution_id}:sending",
                note="Frozen treated audience is ready for governed submission.",
            )
        return {
            "campaign": campaign,
            "lifecycle": current,
            "snapshot": snapshot,
            "members": self.repository.audience_members(
                campaign_id, assignment="TREATED"
            ),
        }

    def projected_wallet_balance(self, patient_link_id: int, credit_amount: int) -> int:
        return WalletRepository(self._db()).get_balance(patient_link_id) + int(
            credit_amount
        )

    def record_cost_for_message(
        self,
        message_id: int,
        *,
        actor_username: str = "system:campaign-cost",
    ) -> dict | None:
        db = self._db()
        message = db.execute(
            "SELECT * FROM sms_messages WHERE id=?",
            (int(message_id),),
        ).fetchone()
        if not message or message["campaign_id"] is None:
            return None
        if str(message["status"] or "") not in {"accepted", "delivered", "sent"}:
            return None
        current = self.repository.current_message_cost(message_id)
        if current and current["status"] == "ACTIVE":
            return current
        rate = self.configured_part_cost(str(message["provider"] or ""))
        if rate is None:
            return None
        parts = self.estimate_sms_parts(str(message["body"] or ""))
        return self.repository.record_message_cost(
            campaign_id=int(message["campaign_id"]),
            message_id=int(message_id),
            evidence_type="ESTIMATED_CONFIGURED_RATE",
            parts=parts,
            unit_cost=rate,
            actor_username=actor_username,
            source_ref=f"settings:sms_cost_per_part_{message['provider']}_toman",
            idempotency_key=f"campaign-message-cost:{message_id}:rate:{rate}:parts:{parts}",
            note="Estimated direct provider cost; not provider-reported actual cost.",
        )

    def ensure_wallet_grant(
        self,
        message_id: int,
        *,
        actor_username: str = "system:campaign-wallet",
    ) -> dict | None:
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            message = db.execute(
                "SELECT * FROM sms_messages WHERE id=?",
                (int(message_id),),
            ).fetchone()
            if not message or message["campaign_id"] is None:
                db.commit()
                return None
            campaign = db.execute(
                "SELECT * FROM sms_campaigns WHERE id=?",
                (int(message["campaign_id"]),),
            ).fetchone()
            if not campaign or campaign["campaign_type"] != "wallet_credit":
                db.commit()
                return None
            amount = int(campaign["credit_amount"] or 0)
            if amount <= 0:
                db.commit()
                return None
            if str(message["status"] or "") not in {"accepted", "delivered", "sent"}:
                raise CampaignExecutionError(
                    "wallet grant requires provider-accepted message"
                )
            current = self.repository.current_wallet_grant(
                int(campaign["id"]), int(message["patient_link_id"])
            )
            if current:
                db.commit()
                return current
            expires_at = None
            if campaign["credit_expires_days"]:
                expires_at = (
                    self.clock()
                    + timedelta(days=int(campaign["credit_expires_days"]))
                ).strftime("%Y-%m-%d")
            transaction = WalletRepository(db).apply(
                int(message["patient_link_id"]),
                amount,
                reason="campaign",
                campaign_id=int(campaign["id"]),
                note=str(campaign["name"]),
                expires_at=expires_at,
                created_by=actor_username,
                idempotency_key=(
                    f"campaign-wallet-grant:{campaign['id']}:"
                    f"patient:{message['patient_link_id']}"
                ),
                commit=False,
            )
            event = self.repository.append_wallet_grant_event(
                campaign_id=int(campaign["id"]),
                patient_link_id=int(message["patient_link_id"]),
                message_id=int(message_id),
                event_type="GRANTED",
                amount=amount,
                wallet_transaction_id=int(transaction["id"]),
                actor_username=actor_username,
                reason_code="PROVIDER_ACCEPTED_MESSAGE",
                idempotency_key=f"campaign-wallet-event:grant:{campaign['id']}:{message['patient_link_id']}",
                commit=False,
            )
            db.commit()
            return event
        except Exception:
            db.rollback()
            raise

    def compensate_wallet_for_message(
        self,
        message_id: int,
        *,
        actor_username: str = "system:campaign-wallet-compensation",
    ) -> dict | None:
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            message = db.execute(
                "SELECT * FROM sms_messages WHERE id=?",
                (int(message_id),),
            ).fetchone()
            if not message or message["campaign_id"] is None:
                db.commit()
                return None
            current = self.repository.current_wallet_grant(
                int(message["campaign_id"]), int(message["patient_link_id"])
            )
            if not current or current["status"] != "ACTIVE":
                db.commit()
                return current
            status = str(message["delivery_status"] or "")
            if status not in {
                "NumberBlackListed", "OperatorBlackList", "Canceled", "Failed",
                "Undelivered", "StatusUnknown", "SubmissionUnknown",
            }:
                db.commit()
                return current
            later_debit = db.execute(
                """SELECT 1 FROM wallet_transactions
                   WHERE patient_link_id=? AND id>? AND amount<0 LIMIT 1""",
                (
                    int(message["patient_link_id"]),
                    int(current["wallet_transaction_id"]),
                ),
            ).fetchone()
            balance = WalletRepository(db).get_balance(int(message["patient_link_id"]))
            amount = int(current["amount"])
            if later_debit or balance < amount:
                event = self.repository.append_wallet_grant_event(
                    campaign_id=int(message["campaign_id"]),
                    patient_link_id=int(message["patient_link_id"]),
                    message_id=int(message_id),
                    event_type="COMPENSATION_REVIEW_REQUIRED",
                    amount=amount,
                    wallet_transaction_id=int(current["wallet_transaction_id"]),
                    actor_username=actor_username,
                    reason_code="NON_DELIVERY_AFTER_CREDIT_ACTIVITY",
                    note=(
                        "Automatic compensation blocked because a later wallet debit "
                        "exists or the current balance is below the grant amount."
                    ),
                    idempotency_key=f"campaign-wallet-review:{message['campaign_id']}:{message['patient_link_id']}",
                    commit=False,
                )
            else:
                transaction = WalletRepository(db).apply(
                    int(message["patient_link_id"]),
                    -amount,
                    reason="campaign_compensation",
                    campaign_id=int(message["campaign_id"]),
                    note="Compensated after terminal non-delivery.",
                    created_by=actor_username,
                    idempotency_key=f"campaign-wallet-compensation:{message['campaign_id']}:{message['patient_link_id']}",
                    commit=False,
                )
                event = self.repository.append_wallet_grant_event(
                    campaign_id=int(message["campaign_id"]),
                    patient_link_id=int(message["patient_link_id"]),
                    message_id=int(message_id),
                    event_type="COMPENSATED",
                    amount=amount,
                    wallet_transaction_id=int(current["wallet_transaction_id"]),
                    compensation_transaction_id=int(transaction["id"]),
                    actor_username=actor_username,
                    reason_code="TERMINAL_NON_DELIVERY",
                    idempotency_key=f"campaign-wallet-event:compensate:{message['campaign_id']}:{message['patient_link_id']}",
                    commit=False,
                )
            db.commit()
            return event
        except Exception:
            db.rollback()
            raise

    def reconcile_campaign_state(
        self,
        campaign_id: int,
        *,
        actor_username: str = "system:campaign-reconciliation",
    ) -> dict:
        campaign = self.repository.campaign(campaign_id)
        if not campaign:
            raise LookupError("campaign not found")
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
        counts = self.repository.message_state_counts(campaign_id)
        current = self.repository.current_lifecycle(campaign_id)
        if not current:
            current = self.register_campaign(
                campaign_id, actor_username=actor_username
            )
        execution_id = current.get("execution_id") or (
            self.repository.audience_snapshot(campaign_id) or {}
        ).get("execution_id")
        if counts["messages"] == 0:
            if current["status"] in {"PREPARING", "SENDING"}:
                current = self.repository.append_lifecycle(
                    campaign_id=campaign_id,
                    status="FAILED",
                    actor_username=actor_username,
                    execution_id=execution_id,
                    outcome_code="NO_MESSAGES_CREATED",
                    expected_current_event_id=int(current["id"]),
                    idempotency_key=f"campaign:{campaign_id}:{execution_id}:failed:no-messages",
                )
        elif counts["nonterminal"]:
            if current["status"] == "SENDING":
                current = self.repository.append_lifecycle(
                    campaign_id=campaign_id,
                    status="AWAITING_DELIVERY",
                    actor_username=actor_username,
                    execution_id=execution_id,
                    outcome_code="DELIVERY_PENDING",
                    expected_current_event_id=int(current["id"]),
                    idempotency_key=f"campaign:{campaign_id}:{execution_id}:awaiting-delivery",
                )
        else:
            if counts["delivered"] == 0:
                target = "FAILED"
                outcome = "NO_DELIVERIES"
            else:
                target = "COMPLETED"
                outcome = (
                    "ALL_DELIVERED"
                    if counts["failed"] == 0
                    else "PARTIAL_DELIVERY_FAILURE"
                )
            if current["status"] in {"SENDING", "AWAITING_DELIVERY"}:
                current = self.repository.append_lifecycle(
                    campaign_id=campaign_id,
                    status=target,
                    actor_username=actor_username,
                    execution_id=execution_id,
                    outcome_code=outcome,
                    expected_current_event_id=int(current["id"]),
                    idempotency_key=f"campaign:{campaign_id}:{execution_id}:terminal:{target}:{outcome}",
                )
        return {
            "lifecycle": current,
            "counts": counts,
            "projection": self.repository.campaign_projection(campaign_id),
        }

    def record_response(
        self,
        *,
        campaign_id: int,
        patient_link_id: int,
        response_type: str,
        evidence_type: str,
        actor_username: str,
        idempotency_key: str,
        message_id: int | None = None,
        evidence_ref: str | None = None,
        note: str | None = None,
        expected_current_event_id: int | None = None,
    ) -> dict:
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            event = self.repository.record_response(
                campaign_id=campaign_id,
                patient_link_id=patient_link_id,
                response_type=response_type,
                evidence_type=evidence_type,
                actor_username=actor_username,
                idempotency_key=idempotency_key,
                message_id=message_id,
                evidence_ref=evidence_ref,
                note=note,
                expected_current_event_id=expected_current_event_id,
                commit=False,
            )
            if str(response_type).upper() == "OPT_OUT":
                campaign = self.repository.campaign(campaign_id)
                purpose = self.purpose_for_campaign(campaign)
                if purpose == "MARKETING":
                    consent_repo = SmsGovernanceRepository(db)
                    current = consent_repo.current_consent(
                        patient_link_id, "MARKETING"
                    )
                    consent_repo.append_consent(
                        patient_link_id=patient_link_id,
                        purpose="MARKETING",
                        decision="REVOKED",
                        source_code="CAMPAIGN_RESPONSE_OPT_OUT",
                        actor_username=actor_username,
                        actor_user_id=None,
                        idempotency_key=f"campaign-response-optout:{event['id']}",
                        reason_code="PATIENT_OPT_OUT",
                        note=note,
                        expected_current_event_id=(
                            int(current["id"]) if current else None
                        ),
                        commit=False,
                    )
            db.commit()
            return event
        except Exception:
            db.rollback()
            raise

    def attribute_response_to_journey(
        self,
        *,
        response_event_id: int,
        journey_id: str,
        actor_username: str,
        idempotency_key: str,
        note: str | None = None,
        commit: bool = True,
    ) -> dict:
        return self.repository.attribute_journey(
            journey_id=journey_id,
            response_event_id=response_event_id,
            actor_username=actor_username,
            idempotency_key=idempotency_key,
            note=note,
            commit=commit,
        )

    def positive_response_options(self, patient_link_id: int) -> list[dict]:
        return self.repository.positive_response_options(patient_link_id)

    def projection(self, campaign_id: int) -> dict:
        return self.repository.campaign_projection(campaign_id)


__all__ = [
    "CampaignEconomicsConflict",
    "CampaignEconomicsService",
    "CampaignEconomicsValidationError",
    "CampaignExecutionError",
]

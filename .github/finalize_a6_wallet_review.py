from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A6 wallet anchor missing in {relative}: {old[:220]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "specialist_clinic/src/adapters/sqlite/campaign_economics_schema.py",
    '''                'GRANTED','COMPENSATED','COMPENSATION_REVIEW_REQUIRED',
                'ENTERED_IN_ERROR'
''',
    '''                'GRANTED','GRANT_REVIEW_REQUIRED','GRANT_NOT_REQUIRED',
                'COMPENSATED','COMPENSATION_REVIEW_REQUIRED','ENTERED_IN_ERROR'
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/campaign_economics_schema.py",
    '''            status TEXT NOT NULL CHECK (status IN (
                'ACTIVE','COMPENSATED','REVIEW_REQUIRED','ENTERED_IN_ERROR'
            )),
''',
    '''            status TEXT NOT NULL CHECK (status IN (
                'ACTIVE','NO_GRANT','COMPENSATED','REVIEW_REQUIRED','ENTERED_IN_ERROR'
            )),
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/campaign_economics_schema.py",
    '''                (event_type='GRANTED' AND status='ACTIVE' AND
                 wallet_transaction_id IS NOT NULL) OR
                (event_type='COMPENSATED' AND status='COMPENSATED' AND
''',
    '''                (event_type='GRANTED' AND status='ACTIVE' AND
                 wallet_transaction_id IS NOT NULL) OR
                (event_type='GRANT_REVIEW_REQUIRED' AND
                 status='REVIEW_REQUIRED') OR
                (event_type='GRANT_NOT_REQUIRED' AND status='NO_GRANT' AND
                 wallet_transaction_id IS NULL AND
                 compensation_transaction_id IS NULL) OR
                (event_type='COMPENSATED' AND status='COMPENSATED' AND
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/campaign_economics_schema.py",
    '''        WHEN NOT EXISTS (
            SELECT 1 FROM campaign_wallet_grant_events event
            WHERE event.campaign_id=NEW.campaign_id
              AND event.patient_link_id=NEW.patient_link_id
        ) AND (NEW.event_type<>'GRANTED' OR NEW.supersedes_event_id IS NOT NULL)
        BEGIN SELECT RAISE(ABORT,'first campaign wallet event must grant'); END;
''',
    '''        WHEN NOT EXISTS (
            SELECT 1 FROM campaign_wallet_grant_events event
            WHERE event.campaign_id=NEW.campaign_id
              AND event.patient_link_id=NEW.patient_link_id
        ) AND (
            NEW.event_type NOT IN ('GRANTED','GRANT_REVIEW_REQUIRED')
            OR NEW.supersedes_event_id IS NOT NULL
        )
        BEGIN SELECT RAISE(ABORT,'first campaign wallet event must grant or require review'); END;
''',
)

replace_once(
    "specialist_clinic/src/adapters/sqlite/campaign_economics_repo.py",
    '''        status_by_event = {
            "GRANTED": "ACTIVE",
            "COMPENSATED": "COMPENSATED",
''',
    '''        status_by_event = {
            "GRANTED": "ACTIVE",
            "GRANT_REVIEW_REQUIRED": "REVIEW_REQUIRED",
            "GRANT_NOT_REQUIRED": "NO_GRANT",
            "COMPENSATED": "COMPENSATED",
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/campaign_economics_repo.py",
    '''            if current and event == "GRANTED":
                if current["status"] == "ACTIVE":
                    if commit:
                        db.commit()
                    return current
                raise CampaignEconomicsConflict("wallet grant stream already exists")
''',
    '''            if current and event == "GRANT_REVIEW_REQUIRED":
                if current["status"] == "REVIEW_REQUIRED":
                    if commit:
                        db.commit()
                    return current
                raise CampaignEconomicsConflict("wallet grant stream already exists")
            if current and event == "GRANTED":
                if current["status"] == "ACTIVE":
                    if commit:
                        db.commit()
                    return current
                if current["status"] != "REVIEW_REQUIRED":
                    raise CampaignEconomicsConflict("wallet grant stream already exists")
            if current and event == "GRANT_NOT_REQUIRED":
                if current["status"] == "NO_GRANT":
                    if commit:
                        db.commit()
                    return current
                if current["status"] != "REVIEW_REQUIRED":
                    raise CampaignEconomicsConflict("wallet grant stream is not under review")
''',
)

# Service method for ambiguous submission before any wallet transaction exists.
service_path = ROOT / "specialist_clinic/src/services/campaign_economics_service.py"
service = service_path.read_text(encoding="utf-8")
anchor = '''    def compensate_wallet_for_message(
'''
method = '''    def mark_wallet_grant_review(
        self,
        message_id: int,
        *,
        actor_username: str = "system:campaign-wallet-review",
    ) -> dict | None:
        db = self._db()
        message = db.execute(
            "SELECT * FROM sms_messages WHERE id=?",
            (int(message_id),),
        ).fetchone()
        if not message or message["campaign_id"] is None:
            return None
        campaign = db.execute(
            "SELECT * FROM sms_campaigns WHERE id=?",
            (int(message["campaign_id"]),),
        ).fetchone()
        if not campaign or campaign["campaign_type"] != "wallet_credit":
            return None
        amount = int(campaign["credit_amount"] or 0)
        if amount <= 0:
            return None
        current = self.repository.current_wallet_grant(
            int(campaign["id"]), int(message["patient_link_id"])
        )
        if current:
            return current
        return self.repository.append_wallet_grant_event(
            campaign_id=int(campaign["id"]),
            patient_link_id=int(message["patient_link_id"]),
            message_id=int(message_id),
            event_type="GRANT_REVIEW_REQUIRED",
            amount=amount,
            actor_username=actor_username,
            reason_code="SUBMISSION_OUTCOME_UNKNOWN",
            note=(
                "Provider submission outcome is ambiguous; no credit was granted "
                "until a later provider result resolves the obligation."
            ),
            idempotency_key=(
                f"campaign-wallet-review:grant:{campaign['id']}:"
                f"{message['patient_link_id']}"
            ),
        )

    def resolve_wallet_review_no_grant(
        self,
        message_id: int,
        *,
        actor_username: str = "system:campaign-wallet-review",
    ) -> dict | None:
        db = self._db()
        message = db.execute(
            "SELECT * FROM sms_messages WHERE id=?",
            (int(message_id),),
        ).fetchone()
        if not message or message["campaign_id"] is None:
            return None
        current = self.repository.current_wallet_grant(
            int(message["campaign_id"]), int(message["patient_link_id"])
        )
        if not current or current["status"] != "REVIEW_REQUIRED":
            return current
        return self.repository.append_wallet_grant_event(
            campaign_id=int(message["campaign_id"]),
            patient_link_id=int(message["patient_link_id"]),
            message_id=int(message_id),
            event_type="GRANT_NOT_REQUIRED",
            amount=int(current["amount"]),
            actor_username=actor_username,
            reason_code="DEFINITIVE_NON_DELIVERY_NO_GRANT",
            note="Provider later reported definitive non-delivery; no credit was issued.",
            idempotency_key=(
                f"campaign-wallet-review:no-grant:{message['campaign_id']}:"
                f"{message['patient_link_id']}"
            ),
        )

'''
if method.strip() not in service:
    if anchor not in service:
        raise AssertionError("A6 wallet review insertion anchor missing")
    service = service.replace(anchor, method + anchor, 1)
    service_path.write_text(service, encoding="utf-8")

replace_once(
    "specialist_clinic/src/services/campaign_economics_service.py",
    '''                if str(message.get("delivery_status") or "") in {
                    "NumberBlackListed", "OperatorBlackList", "Canceled", "Failed",
                    "Undelivered", "StatusUnknown", "SubmissionUnknown",
                }:
                    self.compensate_wallet_for_message(
                        int(message["id"]), actor_username=actor_username
                    )
''',
    '''                delivery_status = str(message.get("delivery_status") or "")
                if delivery_status == "SubmissionUnknown":
                    self.mark_wallet_grant_review(
                        int(message["id"]), actor_username=actor_username
                    )
                elif delivery_status in {
                    "NumberBlackListed", "OperatorBlackList", "Canceled", "Failed",
                    "Undelivered", "StatusUnknown",
                }:
                    current_grant = self.repository.current_wallet_grant(
                        int(message["campaign_id"]), int(message["patient_link_id"])
                    )
                    if current_grant and current_grant["status"] == "REVIEW_REQUIRED":
                        self.resolve_wallet_review_no_grant(
                            int(message["id"]), actor_username=actor_username
                        )
                    else:
                        self.compensate_wallet_for_message(
                            int(message["id"]), actor_username=actor_username
                        )
''',
)

Path(__file__).unlink()

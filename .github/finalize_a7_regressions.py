from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Health contract.
path = ROOT / "specialist_clinic/tests/test_operational_security_hardening.py"
text = path.read_text(encoding="utf-8")
old = '''        "sms_governance",
        "campaign_economics",
    }
'''
new = '''        "sms_governance",
        "campaign_economics",
        "payer_adjustments",
    }
'''
if new not in text:
    if old not in text:
        raise AssertionError("A7 health regression anchor missing")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

# A6 manual financial helper now creates payer evidence and an explicit no-adjustment
# review for the current observation.  This preserves the A6 ROI test under A7.
path = ROOT / "specialist_clinic/tests/test_campaign_economics_a6.py"
text = path.read_text(encoding="utf-8")
old_call = '''    funnel.record_observation_once(
        context=context,
        snapshot={
            "accounting_invoice_id": invoice_id,
            "accounting_patient_id": accounting_patient_id,
            "invoice_status": "closed",
            "work_date": "2026-07-26",
            "closed_at": "2026-07-26 11:00:00",
            "source_total_amount": billed,
            "visits_billed": billed,
            "injections_billed": 0,
            "procedures_billed": 0,
            "billed_amount": billed,
            "visits_collected": collected,
            "injections_collected": 0,
            "procedures_collected": 0,
            "collected_amount": collected,
            "billable_item_count": 1,
            "paid_item_count": paid_items,
            "collection_state": collection_state,
            "source_fingerprint": fingerprint,
        },
        observed_at="2026-07-26 11:05:00",
        created_by="pytest-a6",
    )
'''
new_call = '''    snapshot = {
        "accounting_invoice_id": invoice_id,
        "accounting_patient_id": accounting_patient_id,
        "invoice_status": "closed",
        "work_date": "2026-07-26",
        "closed_at": "2026-07-26 11:00:00",
        "source_total_amount": billed,
        "visits_billed": billed,
        "injections_billed": 0,
        "procedures_billed": 0,
        "billed_amount": billed,
        "visits_collected": collected,
        "injections_collected": 0,
        "procedures_collected": 0,
        "collected_amount": collected,
        "billable_item_count": 1,
        "paid_item_count": paid_items,
        "unpaid_item_count": 0 if paid_items else 1,
        "collection_state": collection_state,
        "patient_cash_collected": 0,
        "patient_card_collected": collected,
        "insurance_collected": 0,
        "unknown_collected": 0,
        "unpaid_amount": max(billed - collected, 0),
        "unknown_payment_type_count": 0,
        "payer_breakdown_evidence": "ACCOUNTING_ITEM_PAYMENT_TYPE_V1",
        "source_fingerprint": fingerprint,
    }
    observation, _created = funnel.record_observation_once(
        context=context,
        snapshot=snapshot,
        observed_at="2026-07-26 11:05:00",
        created_by="pytest-a6",
    )
    from src.services.specialist_payer_adjustment_service import (
        SpecialistPayerAdjustmentService,
    )
    payer = SpecialistPayerAdjustmentService()
    evidence = payer.attach_reconciliation_evidence(
        observation=observation,
        snapshot=snapshot,
        observed_at="2026-07-26 11:05:00",
        actor_username="pytest-a6",
    )
    payer.mark_reviewed(
        accounting_invoice_id=invoice_id,
        actor_username="pytest-a6",
        actor_user_id=None,
        with_adjustment=False,
        note="A6 fixture reviewed with no additional adjustment.",
        expected_current_event_id=int(evidence["review"]["id"]),
        idempotency_key=f"a6-fixture-review:{invoice_id}:{observation['id']}",
    )
'''
if new_call not in text:
    if old_call not in text:
        raise AssertionError("A7 A6 financial helper anchor missing")
    path.write_text(text.replace(old_call, new_call, 1), encoding="utf-8")

Path(__file__).unlink()

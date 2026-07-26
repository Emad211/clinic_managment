from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "specialist_clinic/src/adapters/sqlite/campaign_economics_repo.py"
text = path.read_text(encoding="utf-8")

old_current = '''            """SELECT attribution.*, journey.origin_type, journey.origin_ref
               FROM campaign_journey_attribution_events attribution
               JOIN care_journeys journey ON journey.journey_id=attribution.journey_id
               WHERE attribution.campaign_id=?
                 AND attribution.id=(
                     SELECT head.id FROM campaign_journey_attribution_events head
                     WHERE head.journey_id=attribution.journey_id
                     ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                 ) AND attribution.status='ATTRIBUTED'
               ORDER BY attribution.recorded_at,attribution.id""",
'''
new_current = '''            """SELECT attribution.*, journey.origin_type, journey.origin_ref,
                      CASE WHEN attribution.response_event_id=(
                          SELECT latest_response.id
                          FROM campaign_response_events latest_response
                          WHERE latest_response.campaign_id=attribution.campaign_id
                            AND latest_response.patient_link_id=attribution.patient_link_id
                          ORDER BY latest_response.recorded_at DESC,
                                   latest_response.id DESC LIMIT 1
                      ) AND EXISTS (
                          SELECT 1 FROM campaign_response_events response
                          WHERE response.id=attribution.response_event_id
                            AND response.response_type='POSITIVE'
                      ) THEN 1 ELSE 0 END AS response_current_positive
               FROM campaign_journey_attribution_events attribution
               JOIN care_journeys journey ON journey.journey_id=attribution.journey_id
               WHERE attribution.campaign_id=?
                 AND attribution.id=(
                     SELECT head.id FROM campaign_journey_attribution_events head
                     WHERE head.journey_id=attribution.journey_id
                     ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                 ) AND attribution.status='ATTRIBUTED'
               ORDER BY attribution.recorded_at,attribution.id""",
'''
if new_current not in text:
    if old_current not in text:
        raise AssertionError("A6 attribution current query anchor missing")
    text = text.replace(old_current, new_current, 1)

old_finance = '''                 ) AND attribution.status='ATTRIBUTED'
               ORDER BY attribution.journey_id,observation.accounting_invoice_id""",
'''
new_finance = '''                 ) AND attribution.status='ATTRIBUTED'
                 AND attribution.response_event_id=(
                     SELECT latest_response.id
                     FROM campaign_response_events latest_response
                     WHERE latest_response.campaign_id=attribution.campaign_id
                       AND latest_response.patient_link_id=attribution.patient_link_id
                     ORDER BY latest_response.recorded_at DESC,
                              latest_response.id DESC LIMIT 1
                 )
                 AND EXISTS (
                     SELECT 1 FROM campaign_response_events positive_response
                     WHERE positive_response.id=attribution.response_event_id
                       AND positive_response.response_type='POSITIVE'
                 )
               ORDER BY attribution.journey_id,observation.accounting_invoice_id""",
'''
if new_finance not in text:
    if old_finance not in text:
        raise AssertionError("A6 attribution finance query anchor missing")
    text = text.replace(old_finance, new_finance, 1)

old_projection = '''        attributions = self.current_campaign_attributions(campaign_id)
        financial = self.financial_rows_for_campaign(campaign_id)
        observed_journeys = {row["journey_id"] for row in financial if row["accounting_invoice_id"] is not None}
        attributed_journeys = {row["journey_id"] for row in attributions}
'''
new_projection = '''        attributions = self.current_campaign_attributions(campaign_id)
        trusted_attributions = [
            row for row in attributions if int(row["response_current_positive"] or 0) == 1
        ]
        stale_attributions = [
            row for row in attributions if int(row["response_current_positive"] or 0) != 1
        ]
        financial = self.financial_rows_for_campaign(campaign_id)
        observed_journeys = {row["journey_id"] for row in financial if row["accounting_invoice_id"] is not None}
        attributed_journeys = {row["journey_id"] for row in trusted_attributions}
'''
if new_projection not in text:
    if old_projection not in text:
        raise AssertionError("A6 attribution projection anchor missing")
    text = text.replace(old_projection, new_projection, 1)

text = text.replace(
    '''            and finance_complete
            and costs["wallet_review_required"] == 0
''',
    '''            and finance_complete
            and not stale_attributions
            and costs["wallet_review_required"] == 0
''',
    1,
)
old_status = '''        elif not finance_complete:
            measurement_status = "FINANCIAL_RECONCILIATION_INCOMPLETE"
        elif costs["wallet_review_required"]:
'''
new_status = '''        elif stale_attributions:
            measurement_status = "STALE_RESPONSE_ATTRIBUTION_REVIEW_REQUIRED"
        elif not finance_complete:
            measurement_status = "FINANCIAL_RECONCILIATION_INCOMPLETE"
        elif costs["wallet_review_required"]:
'''
if new_status not in text:
    if old_status not in text:
        raise AssertionError("A6 attribution status anchor missing")
    text = text.replace(old_status, new_status, 1)

old_return = '''            "attributions": {
                "journeys": len(attributed_journeys),
                "rows": attributions,
            },
'''
new_return = '''            "attributions": {
                "journeys": len(attributed_journeys),
                "stale": len(stale_attributions),
                "rows": attributions,
            },
'''
if new_return not in text:
    if old_return not in text:
        raise AssertionError("A6 attribution return anchor missing")
    text = text.replace(old_return, new_return, 1)

path.write_text(text, encoding="utf-8")
Path(__file__).unlink()

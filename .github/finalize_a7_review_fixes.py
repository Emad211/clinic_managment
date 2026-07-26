from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "specialist_clinic/src/adapters/sqlite/specialist_payer_adjustment_repo.py"
text = path.read_text(encoding="utf-8")

# Runs after finalize_a7_core.py, where `force` has already been added.
old_key = '''            event_type = "REVIEW_REQUIRED" if current is None else "REOPENED"
            recorded = _time()
            payload = {
'''
new_key = '''            event_type = "REVIEW_REQUIRED" if current is None else "REOPENED"
            if current is None:
                review_key = (
                    f"financial-review-required:"
                    f"{observation['accounting_invoice_id']}:"
                    f"{observation['id']}"
                )
            elif force:
                review_key = (
                    f"financial-review-reopen:"
                    f"{observation['accounting_invoice_id']}:"
                    f"{observation['id']}:after:{current['id']}"
                )
            else:
                review_key = (
                    f"financial-review-required:"
                    f"{observation['accounting_invoice_id']}:"
                    f"{observation['id']}"
                )
            recorded = _time()
            payload = {
'''
if new_key not in text:
    if old_key not in text:
        raise AssertionError("A7 review key anchor missing")
    text = text.replace(old_key, new_key, 1)
old_payload_key = '''                "idempotency_key": (
                    f"financial-review-required:"
                    f"{observation['accounting_invoice_id']}:"
                    f"{observation['id']}"
                ),
'''
new_payload_key = '''                "idempotency_key": review_key,
'''
if new_payload_key not in text:
    if old_payload_key not in text:
        raise AssertionError("A7 review payload key anchor missing")
    text = text.replace(old_payload_key, new_payload_key, 1)

# Ensure reversal specifically forces a new review event.
start = text.index("    def reverse_adjustment(")
end = text.index("    # ------------------------------------------------------------- projections", start)
block = text[start:end]
old_call = '''                self.ensure_review_required(
                    observation=observation,
                    actor_username=actor_username,
                    commit=False,
                )
'''
new_call = '''                self.ensure_review_required(
                    observation=observation,
                    actor_username=actor_username,
                    force=True,
                    commit=False,
                )
'''
if new_call not in block:
    if old_call not in block:
        raise AssertionError("A7 reverse review reopen anchor missing")
    block = block.replace(old_call, new_call, 1)
    text = text[:start] + block + text[end:]

# Old test readers and historical observations may not provide a payer split.  Preserve
# honesty by placing all collected cash in UNKNOWN with LEGACY_UNAVAILABLE evidence.
old_components = '''            collected_components = {
                "patient_cash_collected": int(
                    snapshot.get("patient_cash_collected") or 0
                ),
                "patient_card_collected": int(
                    snapshot.get("patient_card_collected") or 0
                ),
                "insurance_collected": int(
                    snapshot.get("insurance_collected") or 0
                ),
                "unknown_collected": int(
                    snapshot.get("unknown_collected") or 0
                ),
            }
'''
new_components = '''            evidence_code = str(
                snapshot.get("payer_breakdown_evidence") or ""
            ).strip()
            if evidence_code:
                collected_components = {
                    "patient_cash_collected": int(
                        snapshot.get("patient_cash_collected") or 0
                    ),
                    "patient_card_collected": int(
                        snapshot.get("patient_card_collected") or 0
                    ),
                    "insurance_collected": int(
                        snapshot.get("insurance_collected") or 0
                    ),
                    "unknown_collected": int(
                        snapshot.get("unknown_collected") or 0
                    ),
                }
            else:
                collected_components = {
                    "patient_cash_collected": 0,
                    "patient_card_collected": 0,
                    "insurance_collected": 0,
                    "unknown_collected": int(
                        observation["collected_amount"] or 0
                    ),
                }
                evidence_code = "LEGACY_UNAVAILABLE"
'''
if new_components not in text:
    if old_components not in text:
        raise AssertionError("A7 legacy payer fallback anchor missing")
    text = text.replace(old_components, new_components, 1)
old_evidence = '''                "evidence_code": str(
                    snapshot.get("payer_breakdown_evidence")
                    or "LEGACY_UNAVAILABLE"
                ),
'''
new_evidence = '''                "evidence_code": evidence_code,
'''
if new_evidence not in text:
    if old_evidence not in text:
        raise AssertionError("A7 payer evidence anchor missing")
    text = text.replace(old_evidence, new_evidence, 1)

path.write_text(text, encoding="utf-8")
Path(__file__).unlink()

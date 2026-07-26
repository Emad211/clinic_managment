from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A6 failure-fix anchor missing in {relative}: {old[:240]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# A later Delivered/Accepted result resolves GRANT_REVIEW_REQUIRED by issuing the grant.
replace_once(
    "specialist_clinic/src/services/campaign_economics_service.py",
    '''            current = self.repository.current_wallet_grant(
                int(campaign["id"]), int(message["patient_link_id"])
            )
            if current:
                db.commit()
                return current
            expires_at = None
''',
    '''            current = self.repository.current_wallet_grant(
                int(campaign["id"]), int(message["patient_link_id"])
            )
            if current and current["status"] == "ACTIVE":
                db.commit()
                return current
            if current and current["status"] not in {"REVIEW_REQUIRED"}:
                db.commit()
                return current
            expires_at = None
''',
)

# Preserve the lifecycle sequence even when delivery becomes terminal before the first poll.
replace_once(
    "specialist_clinic/src/services/campaign_economics_service.py",
    '''            if current["status"] in {"SENDING", "AWAITING_DELIVERY"}:
                current = self.repository.append_lifecycle(
                    campaign_id=campaign_id,
                    status=target,
                    actor_username=actor_username,
                    execution_id=execution_id,
                    outcome_code=outcome,
                    expected_current_event_id=int(current["id"]),
                    idempotency_key=f"campaign:{campaign_id}:{execution_id}:terminal:{target}:{outcome}",
                )
''',
    '''            if current["status"] == "SENDING":
                current = self.repository.append_lifecycle(
                    campaign_id=campaign_id,
                    status="AWAITING_DELIVERY",
                    actor_username=actor_username,
                    execution_id=execution_id,
                    outcome_code="DELIVERY_RECONCILED",
                    expected_current_event_id=int(current["id"]),
                    idempotency_key=(
                        f"campaign:{campaign_id}:{execution_id}:"
                        "awaiting-delivery:terminal-observed"
                    ),
                )
            if current["status"] == "AWAITING_DELIVERY":
                current = self.repository.append_lifecycle(
                    campaign_id=campaign_id,
                    status=target,
                    actor_username=actor_username,
                    execution_id=execution_id,
                    outcome_code=outcome,
                    expected_current_event_id=int(current["id"]),
                    idempotency_key=f"campaign:{campaign_id}:{execution_id}:terminal:{target}:{outcome}",
                )
''',
)

# Preserve the established fail-closed status when no campaign definitions exist.
replace_once(
    "specialist_clinic/src/services/revenue_service.py",
    '''        safe_to_sum = bool(rows) and all_ready
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
''',
    '''        safe_to_sum = bool(rows) and all_ready
        if not rows:
            measurement_status = "JOURNEY_LINK_REQUIRED"
        elif safe_to_sum:
            measurement_status = "READY"
        else:
            measurement_status = "CAMPAIGN_ECONOMICS_INCOMPLETE"
        return {
            "rows": rows,
            "attributed_total": attributable_total if safe_to_sum else 0,
            "direct_cost_total": direct_cost_total if safe_to_sum else 0,
            "net_contribution_total": net_total if safe_to_sum else 0,
            "credit_distributed": 0,
            "window_days": None,
            "safe_to_sum": safe_to_sum,
            "measurement_status": measurement_status,
            "policy_version": "EXPLICIT_CAMPAIGN_JOURNEY_ROI_V1",
        }
''',
)

Path(__file__).unlink()

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A7 target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A7 anchor missing in {relative}: {old[:240]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# SQLite does not permit subqueries in CHECK constraints; enforce the same invariant
# with a fail-closed insert trigger.
schema_path = target(
    "specialist_clinic/src/adapters/sqlite/specialist_payer_adjustment_schema.py"
)
schema = schema_path.read_text(encoding="utf-8")
invalid_check = '''            CHECK (
                patient_cash_collected+patient_card_collected+
                insurance_collected+unknown_collected=(
                    SELECT collected_amount
                    FROM specialist_financial_observations observation
                    WHERE observation.id=financial_observation_id
                )
            ),
'''
if invalid_check in schema:
    schema = schema.replace(invalid_check, "", 1)
trigger_anchor = '''        CREATE TRIGGER IF NOT EXISTS trg_payer_breakdown_scope
'''
amount_trigger = '''        CREATE TRIGGER IF NOT EXISTS trg_payer_breakdown_amount
        BEFORE INSERT ON specialist_payer_breakdown_observations
        WHEN NEW.patient_cash_collected+NEW.patient_card_collected+
             NEW.insurance_collected+NEW.unknown_collected<>(
                 SELECT observation.collected_amount
                 FROM specialist_financial_observations observation
                 WHERE observation.id=NEW.financial_observation_id
             )
        BEGIN SELECT RAISE(ABORT,'payer breakdown does not match collected amount'); END;

'''
if amount_trigger.strip() not in schema:
    if trigger_anchor not in schema:
        raise AssertionError("A7 payer amount trigger anchor missing")
    schema = schema.replace(trigger_anchor, amount_trigger + trigger_anchor, 1)
schema_path.write_text(schema, encoding="utf-8")

# Review helper can be force-reopened after adjustment reversal.
replace_once(
    "specialist_clinic/src/adapters/sqlite/specialist_payer_adjustment_repo.py",
    '''        actor_username: str = "system:financial-reconciliation",
        commit: bool = True,
    ) -> tuple[dict, bool]:
''',
    '''        actor_username: str = "system:financial-reconciliation",
        force: bool = False,
        commit: bool = True,
    ) -> tuple[dict, bool]:
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/specialist_payer_adjustment_repo.py",
    '''                and current["status"] in {"REVIEW_REQUIRED", "REVIEWED"}
            ):
''',
    '''                and current["status"] in {"REVIEW_REQUIRED", "REVIEWED"}
                and not force
            ):
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/specialist_payer_adjustment_repo.py",
    '''            event_type = "REVIEW_REQUIRED" if current is None else "REOPENED"
''',
    '''            event_type = "REVIEW_REQUIRED" if current is None else "REOPENED"
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/specialist_payer_adjustment_repo.py",
    '''                    actor_username=actor_username,
                    commit=False,
                )
''',
    '''                    actor_username=actor_username,
                    force=True,
                    commit=False,
                )
''',
)

# Review may only certify adjustments explicitly attached to the current accounting
# observation. Old active streams must be corrected or reversed first.
replace_once(
    "specialist_clinic/src/adapters/sqlite/specialist_payer_adjustment_repo.py",
    '''            active = self.active_adjustments(accounting_invoice_id)
            if with_adjustment and not active:
''',
    '''            active = self.active_adjustments(accounting_invoice_id)
            stale_adjustments = [
                row for row in active
                if int(row["financial_observation_id"]) != int(observation["id"])
            ]
            if stale_adjustments:
                raise SpecialistFinancialReviewValidationError(
                    "active adjustments belong to an older financial observation; "
                    "correct or reverse them before review"
                )
            if with_adjustment and not active:
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/specialist_payer_adjustment_repo.py",
    '''        adjustment_total = sum(
            int(row["signed_amount"]) for row in adjustments
        )
''',
    '''        stale_adjustments = [
            row for row in adjustments
            if int(row["financial_observation_id"]) != int(observation["id"])
        ]
        adjustment_total = sum(
            int(row["signed_amount"])
            for row in adjustments
            if int(row["financial_observation_id"]) == int(observation["id"])
        )
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/specialist_payer_adjustment_repo.py",
    '''        if not breakdown:
            status = "PAYER_BREAKDOWN_MISSING"
        elif not review or int(review["financial_observation_id"]) != int(
''',
    '''        if not breakdown:
            status = "PAYER_BREAKDOWN_MISSING"
        elif stale_adjustments:
            status = "ADJUSTMENT_OBSERVATION_STALE"
        elif not review or int(review["financial_observation_id"]) != int(
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/specialist_payer_adjustment_repo.py",
    '''            "adjustments": adjustments,
            "adjustment_total": adjustment_total,
''',
    '''            "adjustments": adjustments,
            "stale_adjustments": stale_adjustments,
            "adjustment_total": adjustment_total,
''',
)

# Canonical startup.
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    from src.adapters.sqlite.campaign_economics_schema import (
        ensure_campaign_economics_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
''',
    '''    from src.adapters.sqlite.campaign_economics_schema import (
        ensure_campaign_economics_storage,
    )
    from src.adapters.sqlite.specialist_payer_adjustment_schema import (
        ensure_specialist_payer_adjustment_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    ensure_campaign_economics_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_campaign_economics_storage(db)
    ensure_specialist_payer_adjustment_storage(db)
    ensure_clinical_validation_storage(db)
''',
)

# Audit root.
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''from src.adapters.sqlite.campaign_economics_schema import (
    ensure_campaign_economics_storage,
)
from src.common.utils import iran_now
''',
    '''from src.adapters.sqlite.campaign_economics_schema import (
    ensure_campaign_economics_storage,
)
from src.adapters.sqlite.specialist_payer_adjustment_schema import (
    ensure_specialist_payer_adjustment_storage,
)
from src.common.utils import iran_now
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    'SCOPE_VERSION = "1.8-campaign-economics"',
    'SCOPE_VERSION = "1.9-payer-adjustments"',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''    "campaign_message_cost_events",
    "security_permission_events",
''',
    '''    "campaign_message_cost_events",
    "specialist_payer_breakdown_observations",
    "specialist_financial_adjustment_events",
    "specialist_financial_review_events",
    "security_permission_events",
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''        ensure_campaign_economics_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
    '''        ensure_campaign_economics_storage(db)
        ensure_specialist_payer_adjustment_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
)

# PHI-free readiness checks only storage consistency; pending business reviews do not
# make liveness/readiness fail.
replace_once(
    "specialist_clinic/src/api/health.py",
    '''from src.adapters.sqlite.campaign_economics_schema import (
    ensure_campaign_economics_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
''',
    '''from src.adapters.sqlite.campaign_economics_schema import (
    ensure_campaign_economics_storage,
)
from src.adapters.sqlite.specialist_payer_adjustment_schema import (
    ensure_specialist_payer_adjustment_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "campaign_message_cost_events",
    }
)''',
    '''        "campaign_message_cost_events",
        "specialist_payer_breakdown_observations",
        "specialist_financial_adjustment_events",
        "specialist_financial_review_events",
    }
)''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    ensure_campaign_economics_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_campaign_economics_storage(db)
    ensure_specialist_payer_adjustment_storage(db)
    ensure_clinical_validation_storage(db)
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    campaign_economics_ok = inconsistent_campaign is None

    return {
''',
    '''    campaign_economics_ok = inconsistent_campaign is None
    payer_orphan = db.execute(
        """SELECT 1 FROM specialist_payer_breakdown_observations payer
           LEFT JOIN specialist_financial_observations observation
             ON observation.id=payer.financial_observation_id
           WHERE observation.id IS NULL LIMIT 1"""
    ).fetchone()
    payer_adjustment_storage_ok = payer_orphan is None

    return {
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "campaign_economics": campaign_economics_ok,
    }
''',
    '''        "campaign_economics": campaign_economics_ok,
        "payer_adjustments": payer_adjustment_storage_ok,
    }
''',
)
health_path = target("specialist_clinic/src/api/health.py")
health = health_path.read_text(encoding="utf-8")
health = health.replace(
    '''            "campaign_economics": False,
        }
''',
    '''            "campaign_economics": False,
            "payer_adjustments": False,
        }
''',
)
health_path.write_text(health, encoding="utf-8")

# Fine-grained permissions.
replace_once(
    "specialist_clinic/src/security/permissions.py",
    '''    SMS_CAMPAIGN_ECONOMICS_VIEW = "sms.campaign.economics.view"
    RULE_REVIEW_CLINICAL = "rule.review.clinical"
''',
    '''    SMS_CAMPAIGN_ECONOMICS_VIEW = "sms.campaign.economics.view"
    FINANCIAL_REVIEW_VIEW = "financial.review.view"
    FINANCIAL_RECONCILE = "financial.reconcile"
    FINANCIAL_ADJUSTMENT_RECORD = "financial.adjustment.record"
    FINANCIAL_ADJUSTMENT_CORRECT = "financial.adjustment.correct"
    FINANCIAL_REVIEW_COMPLETE = "financial.review.complete"
    RULE_REVIEW_CLINICAL = "rule.review.clinical"
''',
)
# Staff can see pending review state, but only managers/default explicit grants mutate it.
replace_once(
    "specialist_clinic/src/security/permissions.py",
    '''            Permission.SMS_CAMPAIGN_ATTRIBUTION_RECORD,
        }
''',
    '''            Permission.SMS_CAMPAIGN_ATTRIBUTION_RECORD,
            Permission.FINANCIAL_REVIEW_VIEW,
        }
''',
)

Path(__file__).unlink()

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def path(relative: str) -> Path:
    target = ROOT / relative
    if not target.exists():
        raise AssertionError(f"A6 target missing: {relative}")
    return target


def replace_once(relative: str, old: str, new: str) -> None:
    target = path(relative)
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A6 anchor missing in {relative}: {old[:200]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Repository schema checks must never commit a caller-owned transaction.
replace_once(
    "specialist_clinic/src/adapters/sqlite/campaign_economics_repo.py",
    '''    def _db(self) -> sqlite3.Connection:
        db = self._connection or get_db()
        ensure_campaign_economics_storage(db)
        return db
''',
    '''    def _db(self) -> sqlite3.Connection:
        db = self._connection or get_db()
        installed = db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='campaign_lifecycle_events'"
        ).fetchone()
        if not installed:
            if db.in_transaction:
                raise RuntimeError(
                    "campaign economics storage is missing inside a caller transaction"
                )
            ensure_campaign_economics_storage(db)
        return db
''',
)

# A delivered message was necessarily provider-accepted; direct cost completeness must
# include both currently accepted/in-flight messages and terminal delivered messages.
replace_once(
    "specialist_clinic/src/adapters/sqlite/campaign_economics_repo.py",
    '''        cost_complete = (
            messages["accepted"] == costs["costed_messages"]
            if messages["accepted"]
            else True
        )
''',
    '''        provider_accepted_messages = messages["accepted"] + messages["delivered"]
        cost_complete = (
            provider_accepted_messages == costs["costed_messages"]
            if provider_accepted_messages
            else True
        )
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/campaign_economics_repo.py",
    '''            "messages": messages,
''',
    '''            "messages": {
                **messages,
                "provider_accepted": provider_accepted_messages,
            },
''',
)

# Canonical startup schema.
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    from src.adapters.sqlite.sms_governance_schema import (
        ensure_sms_governance_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
''',
    '''    from src.adapters.sqlite.sms_governance_schema import (
        ensure_sms_governance_storage,
    )
    from src.adapters.sqlite.campaign_economics_schema import (
        ensure_campaign_economics_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    ensure_specialist_financial_funnel_storage(db)
    ensure_sms_governance_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_specialist_financial_funnel_storage(db)
    ensure_sms_governance_storage(db)
    ensure_campaign_economics_storage(db)
    ensure_clinical_validation_storage(db)
''',
)

# PHI-free readiness checks schema and lifecycle consistency.
replace_once(
    "specialist_clinic/src/api/health.py",
    '''from src.adapters.sqlite.sms_governance_schema import (
    ensure_sms_governance_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
''',
    '''from src.adapters.sqlite.sms_governance_schema import (
    ensure_sms_governance_storage,
)
from src.adapters.sqlite.campaign_economics_schema import (
    ensure_campaign_economics_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "sms_delivery_events",
    }
)''',
    '''        "sms_delivery_events",
        "campaign_lifecycle_events",
        "campaign_audience_snapshots",
        "campaign_audience_members",
        "campaign_response_events",
        "campaign_journey_attribution_events",
        "campaign_wallet_grant_events",
        "campaign_message_cost_events",
    }
)''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    ensure_sms_governance_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_sms_governance_storage(db)
    ensure_campaign_economics_storage(db)
    ensure_clinical_validation_storage(db)
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    sms_governance_ok = int(ungoverned_messages or 0) == 0

    return {
''',
    '''    sms_governance_ok = int(ungoverned_messages or 0) == 0
    inconsistent_campaign = db.execute(
        """SELECT 1 FROM campaign_lifecycle_events lifecycle
           WHERE lifecycle.id=(
               SELECT head.id FROM campaign_lifecycle_events head
               WHERE head.campaign_id=lifecycle.campaign_id
               ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
           )
             AND lifecycle.status IN (
                 'PREPARING','SENDING','AWAITING_DELIVERY'
             )
             AND NOT EXISTS (
                 SELECT 1 FROM campaign_audience_snapshots audience
                 WHERE audience.campaign_id=lifecycle.campaign_id
                   AND audience.execution_id=lifecycle.execution_id
             )
           LIMIT 1"""
    ).fetchone()
    campaign_economics_ok = inconsistent_campaign is None

    return {
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "sms_governance": sms_governance_ok,
    }
''',
    '''        "sms_governance": sms_governance_ok,
        "campaign_economics": campaign_economics_ok,
    }
''',
)
health_path = path("specialist_clinic/src/api/health.py")
health = health_path.read_text(encoding="utf-8")
health = health.replace(
    '''            "sms_governance": False,
        }
''',
    '''            "sms_governance": False,
            "campaign_economics": False,
        }
''',
)
health_path.write_text(health, encoding="utf-8")

# Audit root covers every immutable A6 table.
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''from src.adapters.sqlite.sms_governance_schema import (
    ensure_sms_governance_storage,
)
from src.common.utils import iran_now
''',
    '''from src.adapters.sqlite.sms_governance_schema import (
    ensure_sms_governance_storage,
)
from src.adapters.sqlite.campaign_economics_schema import (
    ensure_campaign_economics_storage,
)
from src.common.utils import iran_now
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    'SCOPE_VERSION = "1.7-sms-governance"',
    'SCOPE_VERSION = "1.8-campaign-economics"',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''    "sms_delivery_events",
    "security_permission_events",
''',
    '''    "sms_delivery_events",
    "campaign_lifecycle_events",
    "campaign_audience_snapshots",
    "campaign_audience_members",
    "campaign_response_events",
    "campaign_journey_attribution_events",
    "campaign_wallet_grant_events",
    "campaign_message_cost_events",
    "security_permission_events",
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''        ensure_sms_governance_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
    '''        ensure_sms_governance_storage(db)
        ensure_campaign_economics_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
)

# Fine-grained operational permissions.
replace_once(
    "specialist_clinic/src/security/permissions.py",
    '''    SMS_CONSENT_MANAGE = "sms.consent.manage"
    RULE_REVIEW_CLINICAL = "rule.review.clinical"
''',
    '''    SMS_CONSENT_MANAGE = "sms.consent.manage"
    SMS_CAMPAIGN_RESPONSE_RECORD = "sms.campaign.response.record"
    SMS_CAMPAIGN_ATTRIBUTION_RECORD = "sms.campaign.attribution.record"
    SMS_CAMPAIGN_ATTRIBUTION_CORRECT = "sms.campaign.attribution.correct"
    SMS_CAMPAIGN_ECONOMICS_VIEW = "sms.campaign.economics.view"
    RULE_REVIEW_CLINICAL = "rule.review.clinical"
''',
)
replace_once(
    "specialist_clinic/src/security/permissions.py",
    '''            Permission.SMS_CONSENT_MANAGE,
        }
''',
    '''            Permission.SMS_CONSENT_MANAGE,
            Permission.SMS_CAMPAIGN_RESPONSE_RECORD,
            Permission.SMS_CAMPAIGN_ATTRIBUTION_RECORD,
        }
''',
)

Path(__file__).unlink()

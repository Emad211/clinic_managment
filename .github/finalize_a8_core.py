from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A8 target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A8 anchor missing in {relative}: {old[:220]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Fix the legacy backfill bind count before schema installation.
replace_once(
    "specialist_clinic/src/adapters/sqlite/specialist_service_lineage_schema.py",
    '''               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)""",
            (*payload.values(), _hash(payload)),
''',
    '''               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (*payload.values(), _hash(payload)),
''',
)

# Canonical startup installation.
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    from src.adapters.sqlite.specialist_payer_adjustment_schema import (
        ensure_specialist_payer_adjustment_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
''',
    '''    from src.adapters.sqlite.specialist_payer_adjustment_schema import (
        ensure_specialist_payer_adjustment_storage,
    )
    from src.adapters.sqlite.specialist_service_lineage_schema import (
        ensure_specialist_service_lineage_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    ensure_campaign_economics_storage(db)
    ensure_specialist_payer_adjustment_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_campaign_economics_storage(db)
    ensure_specialist_payer_adjustment_storage(db)
    ensure_specialist_service_lineage_storage(db)
    ensure_clinical_validation_storage(db)
''',
)

# Audit coverage.
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''from src.adapters.sqlite.specialist_payer_adjustment_schema import (
    ensure_specialist_payer_adjustment_storage,
)
from src.common.utils import iran_now
''',
    '''from src.adapters.sqlite.specialist_payer_adjustment_schema import (
    ensure_specialist_payer_adjustment_storage,
)
from src.adapters.sqlite.specialist_service_lineage_schema import (
    ensure_specialist_service_lineage_storage,
)
from src.common.utils import iran_now
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    'SCOPE_VERSION = "1.9-payer-adjustments"',
    'SCOPE_VERSION = "2.0-service-lineage"',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''    "specialist_financial_review_events",
    "security_permission_events",
''',
    '''    "specialist_financial_review_events",
    "specialist_service_snapshot_manifests",
    "specialist_service_line_observations",
    "security_permission_events",
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''        ensure_campaign_economics_storage(db)
        ensure_specialist_payer_adjustment_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
    '''        ensure_campaign_economics_storage(db)
        ensure_specialist_payer_adjustment_storage(db)
        ensure_specialist_service_lineage_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
)

# PHI-free readiness: structural consistency only. Legacy-unavailable manifests are valid.
replace_once(
    "specialist_clinic/src/api/health.py",
    '''from src.adapters.sqlite.specialist_payer_adjustment_schema import (
    ensure_specialist_payer_adjustment_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
''',
    '''from src.adapters.sqlite.specialist_payer_adjustment_schema import (
    ensure_specialist_payer_adjustment_storage,
)
from src.adapters.sqlite.specialist_service_lineage_schema import (
    ensure_specialist_service_lineage_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "specialist_financial_review_events",
    }
)''',
    '''        "specialist_financial_review_events",
        "specialist_service_snapshot_manifests",
        "specialist_service_line_observations",
    }
)''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    ensure_campaign_economics_storage(db)
    ensure_specialist_payer_adjustment_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_campaign_economics_storage(db)
    ensure_specialist_payer_adjustment_storage(db)
    ensure_specialist_service_lineage_storage(db)
    ensure_clinical_validation_storage(db)
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    payer_adjustment_storage_ok = payer_orphan is None

    return {
''',
    '''    payer_adjustment_storage_ok = payer_orphan is None
    service_inconsistent = db.execute(
        """SELECT manifest.snapshot_id
           FROM specialist_service_snapshot_manifests manifest
           LEFT JOIN specialist_financial_observations observation
             ON observation.id=manifest.financial_observation_id
           LEFT JOIN specialist_service_line_observations line
             ON line.snapshot_id=manifest.snapshot_id
           GROUP BY manifest.snapshot_id
           HAVING observation.id IS NULL
              OR (manifest.status='COMPLETE' AND (
                    COUNT(line.id)<>manifest.expected_line_count
                    OR COALESCE(SUM(line.total_amount),0)<>
                       manifest.expected_total_amount
                    OR manifest.expected_line_count<>observation.billable_item_count
                    OR manifest.expected_total_amount<>observation.billed_amount
                    OR SUM(CASE WHEN line.id IS NOT NULL AND (
                         line.accounting_invoice_id<>manifest.accounting_invoice_id
                         OR line.journey_id<>manifest.journey_id
                         OR line.encounter_id<>manifest.encounter_id
                         OR line.patient_link_id<>manifest.patient_link_id
                    ) THEN 1 ELSE 0 END)>0
                 ))
              OR (manifest.status='LEGACY_UNAVAILABLE' AND COUNT(line.id)<>0)
           LIMIT 1"""
    ).fetchone()
    service_lineage_ok = service_inconsistent is None

    return {
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "payer_adjustments": payer_adjustment_storage_ok,
    }
''',
    '''        "payer_adjustments": payer_adjustment_storage_ok,
        "service_lineage": service_lineage_ok,
    }
''',
)
health = target("specialist_clinic/src/api/health.py")
text = health.read_text(encoding="utf-8")
text = text.replace(
    '''            "payer_adjustments": False,
        }
''',
    '''            "payer_adjustments": False,
            "service_lineage": False,
        }
''',
)
health.write_text(text, encoding="utf-8")

Path(__file__).unlink()

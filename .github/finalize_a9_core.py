from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def path(relative: str) -> Path:
    target = ROOT / relative
    if not target.exists():
        raise AssertionError(f"A9 target missing: {relative}")
    return target


def replace_once(relative: str, old: str, new: str) -> None:
    target = path(relative)
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A9 anchor missing in {relative}: {old[:220]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    from src.adapters.sqlite.specialist_service_lineage_schema import (
        ensure_specialist_service_lineage_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
''',
    '''    from src.adapters.sqlite.specialist_service_lineage_schema import (
        ensure_specialist_service_lineage_storage,
    )
    from src.adapters.sqlite.encounter_documentation_schema import (
        ensure_encounter_documentation_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    ensure_specialist_service_lineage_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_specialist_service_lineage_storage(db)
    ensure_encounter_documentation_storage(db)
    ensure_clinical_validation_storage(db)
''',
)

replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''from src.adapters.sqlite.specialist_service_lineage_schema import (
    ensure_specialist_service_lineage_storage,
)
from src.common.utils import iran_now
''',
    '''from src.adapters.sqlite.specialist_service_lineage_schema import (
    ensure_specialist_service_lineage_storage,
)
from src.adapters.sqlite.encounter_documentation_schema import (
    ensure_encounter_documentation_storage,
)
from src.common.utils import iran_now
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    'SCOPE_VERSION = "2.0-service-lineage"',
    'SCOPE_VERSION = "2.1-encounter-documentation"',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''    "specialist_service_line_observations",
    "security_permission_events",
''',
    '''    "specialist_service_line_observations",
    "care_encounter_document_requirements",
    "care_encounter_document_events",
    "security_permission_events",
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''        ensure_specialist_service_lineage_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
    '''        ensure_specialist_service_lineage_storage(db)
        ensure_encounter_documentation_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
)

replace_once(
    "specialist_clinic/src/api/health.py",
    '''from src.adapters.sqlite.specialist_service_lineage_schema import (
    ensure_specialist_service_lineage_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
''',
    '''from src.adapters.sqlite.specialist_service_lineage_schema import (
    ensure_specialist_service_lineage_storage,
)
from src.adapters.sqlite.encounter_documentation_schema import (
    ensure_encounter_documentation_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "specialist_service_line_observations",
    }
)''',
    '''        "specialist_service_line_observations",
        "care_encounter_document_requirements",
        "care_encounter_document_events",
    }
)''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    ensure_specialist_service_lineage_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_specialist_service_lineage_storage(db)
    ensure_encounter_documentation_storage(db)
    ensure_clinical_validation_storage(db)
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    service_lineage_ok = service_inconsistent is None

    return {
''',
    '''    service_lineage_ok = service_inconsistent is None
    document_inconsistent = db.execute(
        """SELECT 1
           FROM care_encounter_document_requirements requirement
           LEFT JOIN care_encounters encounter
             ON encounter.encounter_id=requirement.encounter_id
           WHERE encounter.encounter_id IS NULL
              OR encounter.journey_id<>requirement.journey_id
              OR encounter.patient_link_id<>requirement.patient_link_id
              OR encounter.accounting_invoice_id IS NOT requirement.accounting_invoice_id
           UNION ALL
           SELECT 1
           FROM care_encounter_document_events document
           LEFT JOIN care_encounters encounter
             ON encounter.encounter_id=document.encounter_id
           WHERE encounter.encounter_id IS NULL
              OR encounter.journey_id<>document.journey_id
              OR encounter.patient_link_id<>document.patient_link_id
              OR encounter.accounting_invoice_id<>document.accounting_invoice_id
           LIMIT 1"""
    ).fetchone()
    encounter_documentation_ok = document_inconsistent is None

    return {
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "service_lineage": service_lineage_ok,
    }
''',
    '''        "service_lineage": service_lineage_ok,
        "encounter_documentation": encounter_documentation_ok,
    }
''',
)
health = path("specialist_clinic/src/api/health.py")
text = health.read_text(encoding="utf-8")
text = text.replace(
    '''            "service_lineage": False,
        }
''',
    '''            "service_lineage": False,
            "encounter_documentation": False,
        }
''',
)
health.write_text(text, encoding="utf-8")

replace_once(
    "specialist_clinic/src/security/permissions.py",
    '''    CLINICAL_ENCOUNTER_MANAGE = "clinical.encounter.manage"
    CLINICAL_DECISION_RECORD = "clinical.decision.record"
''',
    '''    CLINICAL_ENCOUNTER_MANAGE = "clinical.encounter.manage"
    CLINICAL_DOCUMENT_WRITE = "clinical.document.write"
    CLINICAL_DOCUMENT_AMEND = "clinical.document.amend"
    CLINICAL_DECISION_RECORD = "clinical.decision.record"
''',
)
replace_once(
    "specialist_clinic/src/security/permissions.py",
    '''            Permission.CLINICAL_DATA_RECORD,
            Permission.CLINICAL_TASK_VIEW,
''',
    '''            Permission.CLINICAL_DATA_RECORD,
            Permission.CLINICAL_DOCUMENT_WRITE,
            Permission.CLINICAL_TASK_VIEW,
''',
)

Path(__file__).unlink()

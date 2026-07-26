from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def file(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A10 core target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = file(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A10 core anchor missing in {relative}: {old[:220]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Startup schema.
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    from src.adapters.sqlite.encounter_documentation_schema import (
        ensure_encounter_documentation_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
''',
    '''    from src.adapters.sqlite.encounter_documentation_schema import (
        ensure_encounter_documentation_storage,
    )
    from src.adapters.sqlite.encounter_plan_commitment_schema import (
        ensure_encounter_plan_commitment_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    ensure_encounter_documentation_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_encounter_documentation_storage(db)
    ensure_encounter_plan_commitment_storage(db)
    ensure_clinical_validation_storage(db)
''',
)

# Database-level guard against mutable task shortcuts.
replace_once(
    "specialist_clinic/src/adapters/sqlite/encounter_plan_commitment_schema.py",
    '''        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_task_scope
        BEFORE INSERT ON care_plan_commitment_task_links
''',
    '''        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_task_mutation_guard
        BEFORE UPDATE OF status,due_date,assigned_to,appointment_id,resolved_at
        ON followup_tasks
        WHEN OLD.source_engine='encounter_plan'
        BEGIN SELECT RAISE(ABORT,'plan commitment tasks require append-only lifecycle'); END;

        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_task_scope
        BEFORE INSERT ON care_plan_commitment_task_links
''',
)

# Audit hash chain.
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''from src.adapters.sqlite.encounter_documentation_schema import (
    ensure_encounter_documentation_storage,
)
from src.common.utils import iran_now
''',
    '''from src.adapters.sqlite.encounter_documentation_schema import (
    ensure_encounter_documentation_storage,
)
from src.adapters.sqlite.encounter_plan_commitment_schema import (
    ensure_encounter_plan_commitment_storage,
)
from src.common.utils import iran_now
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    'SCOPE_VERSION = "2.1-encounter-documentation"',
    'SCOPE_VERSION = "2.2-encounter-plan-commitments"',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''    "care_encounter_document_events",
    "security_permission_events",
''',
    '''    "care_encounter_document_events",
    "care_plan_commitments",
    "care_plan_commitment_task_links",
    "care_plan_commitment_events",
    "security_permission_events",
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''        ensure_encounter_documentation_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
    '''        ensure_encounter_documentation_storage(db)
        ensure_encounter_plan_commitment_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
)

# Readiness schema and structural consistency.
replace_once(
    "specialist_clinic/src/api/health.py",
    '''from src.adapters.sqlite.encounter_documentation_schema import (
    ensure_encounter_documentation_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
''',
    '''from src.adapters.sqlite.encounter_documentation_schema import (
    ensure_encounter_documentation_storage,
)
from src.adapters.sqlite.encounter_plan_commitment_schema import (
    ensure_encounter_plan_commitment_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "care_encounter_document_events",
    }
)''',
    '''        "care_encounter_document_events",
        "care_plan_commitments",
        "care_plan_commitment_task_links",
        "care_plan_commitment_events",
    }
)''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    ensure_encounter_documentation_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_encounter_documentation_storage(db)
    ensure_encounter_plan_commitment_storage(db)
    ensure_clinical_validation_storage(db)
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    encounter_documentation_ok = document_inconsistent is None

    return {
''',
    '''    encounter_documentation_ok = document_inconsistent is None
    plan_commitment_inconsistent = db.execute(
        """SELECT 1
           FROM care_plan_commitment_task_links link
           JOIN care_plan_commitments commitment
             ON commitment.commitment_id=link.commitment_id
           LEFT JOIN followup_tasks task ON task.id=link.task_id
           LEFT JOIN care_plan_commitment_events event
             ON event.commitment_id=commitment.commitment_id
            AND event.id=(
                SELECT head.id FROM care_plan_commitment_events head
                WHERE head.commitment_id=commitment.commitment_id
                ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
            )
           WHERE task.id IS NULL
              OR task.patient_link_id<>commitment.patient_link_id
              OR task.source_engine<>'encounter_plan'
              OR task.source_rule<>commitment.commitment_id
              OR event.id IS NULL
           LIMIT 1"""
    ).fetchone()
    encounter_plan_ok = plan_commitment_inconsistent is None

    return {
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "encounter_documentation": encounter_documentation_ok,
    }
''',
    '''        "encounter_documentation": encounter_documentation_ok,
        "encounter_plan_commitments": encounter_plan_ok,
    }
''',
)
health = file("specialist_clinic/src/api/health.py")
text = health.read_text(encoding="utf-8")
text = text.replace(
    '''            "encounter_documentation": False,
        }
''',
    '''            "encounter_documentation": False,
            "encounter_plan_commitments": False,
        }
''',
)
health.write_text(text, encoding="utf-8")

# Dedicated permission vocabulary. Staff can operate commitments; amendments remain separate.
replace_once(
    "specialist_clinic/src/security/permissions.py",
    '''    CLINICAL_DOCUMENT_WRITE = "clinical.document.write"
    CLINICAL_DOCUMENT_AMEND = "clinical.document.amend"
''',
    '''    CLINICAL_DOCUMENT_WRITE = "clinical.document.write"
    CLINICAL_DOCUMENT_AMEND = "clinical.document.amend"
    FOLLOWUP_PLAN_TRANSITION = "followup.plan.transition"
''',
)
replace_once(
    "specialist_clinic/src/security/permissions.py",
    '''            Permission.CLINICAL_DOCUMENT_WRITE,
            Permission.CLINICAL_TASK_VIEW,
''',
    '''            Permission.CLINICAL_DOCUMENT_WRITE,
            Permission.FOLLOWUP_PLAN_TRANSITION,
            Permission.CLINICAL_TASK_VIEW,
''',
)

Path(__file__).unlink()

"""Minimal PHI-free liveness and operational readiness endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify

from src.adapters.sqlite.clinical_audit_integrity_schema import (
    ensure_clinical_audit_integrity_storage,
)
from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository,
)
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.operational_lease_schema import (
    ensure_operational_lease_storage,
)
from src.adapters.sqlite.specialist_enrollment_repo import (
    SpecialistEnrollmentRepository,
)
from src.adapters.sqlite.specialist_revenue_boundary_schema import (
    ensure_specialist_revenue_boundary_storage,
)
from src.adapters.sqlite.followup_operations_schema import (
    ensure_followup_operations_storage,
)
from src.adapters.sqlite.clinical_task_contract_schema import (
    ensure_clinical_task_contract_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
    ensure_clinical_validation_storage,
)
from src.adapters.sqlite.security_permission_schema import (
    ensure_security_permission_storage,
)
from src.security.permissions import Permission, permission_required
from src.services.clinical_audit_integrity import (
    ClinicalAuditIntegrityService,
)


bp = Blueprint("health", __name__, url_prefix="/health")

_REQUIRED_TABLES = frozenset(
    {
        "patient_links",
        "clinical_engine_runs",
        "clinical_rule_versions",
        "clinical_recommendation_events",
        "clinical_decision_events",
        "clinical_task_events",
        "clinical_outcome_events",
        "clinical_data_conflict_events",
        "security_permission_events",
        "operational_leases",
        "operational_job_runs",
        "clinical_audit_checkpoints",
        "clinical_validation_reports",
        "clinical_validation_attestations",
        "specialist_program_enrollments",
        "care_journeys",
        "care_journey_events",
        "care_encounters",
        "care_encounter_events",
        "accounting_invoice_attribution_events",
        "followup_contact_events",
        "followup_booking_requests",
        "clinical_task_contracts",
        "clinical_outcome_canonical_links",
    }
)


def _readiness_checks() -> dict[str, bool]:
    db = get_db()
    ensure_security_permission_storage(db)
    ensure_operational_lease_storage(db)
    ensure_specialist_revenue_boundary_storage(db)
    ensure_followup_operations_storage(db)
    ensure_clinical_task_contract_storage(db)
    ensure_clinical_validation_storage(db)
    ensure_clinical_audit_integrity_storage(db)

    quick = db.execute("PRAGMA quick_check").fetchone()
    integrity_ok = bool(quick and str(quick[0]).lower() == "ok")
    tables = {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    schema_ok = _REQUIRED_TABLES <= tables

    activation = ClinicalEngineActivationRepository()
    raw_mode = activation.raw_mode()
    activation_ok = (
        raw_mode in {"off", "shadow"}
        or (
            raw_mode in {"on_selected", "on"}
            and activation.valid_seal(raw_mode)
        )
    )
    audit = ClinicalAuditIntegrityService().verify_latest(
        require_checkpoint=raw_mode in {"on_selected", "on"}
    )
    audit_ok = audit.ok

    # A RUNNING job is unhealthy only when it is old and no matching live lease
    # owns its fencing token. This reports no job name, owner or timestamp.
    stuck = db.execute(
        """SELECT 1
           FROM operational_job_runs job
           WHERE job.status='RUNNING'
             AND datetime(job.started_at) < datetime('now','-2 hours')
             AND NOT EXISTS (
                 SELECT 1 FROM operational_leases lease
                 WHERE lease.lease_name=job.lease_name
                   AND lease.owner_id=job.owner_id
                   AND lease.fencing_token=job.fencing_token
                   AND datetime(lease.expires_at)>datetime('now','+3 hours','+30 minutes')
             )
           LIMIT 1"""
    ).fetchone()
    worker_ok = stuck is None
    revenue_scope_ok = SpecialistEnrollmentRepository(
        db
    ).missing_scope_count() == 0

    return {
        "database": integrity_ok,
        "schema": schema_ok,
        "activation": activation_ok,
        "audit": audit_ok,
        "worker": worker_ok,
        "revenue_scope": revenue_scope_ok,
    }


@bp.get("/live")
def live():
    return jsonify({"status": "ok"})


@bp.get("/ready")
def ready():
    try:
        checks = _readiness_checks()
    except Exception:
        checks = {
            "database": False,
            "schema": False,
            "activation": False,
            "audit": False,
            "worker": False,
            "revenue_scope": False,
        }
    is_ready = all(checks.values())
    # Public readiness discloses no table, patient, path, mode, secret or exception.
    return jsonify({"status": "ready" if is_ready else "not_ready"}), (
        200 if is_ready else 503
    )


@bp.get("/details")
@permission_required(Permission.OPERATIONAL_HEALTH_VIEW)
def details():
    try:
        checks = _readiness_checks()
        error = None
    except Exception:
        checks = {
            "database": False,
            "schema": False,
            "activation": False,
            "audit": False,
            "worker": False,
            "revenue_scope": False,
        }
        error = "health_check_failed"
    is_ready = all(checks.values())
    payload = {
        "status": "ready" if is_ready else "not_ready",
        "checks": checks,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if error:
        payload["error"] = error
    return jsonify(payload), (200 if is_ready else 503)

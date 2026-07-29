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
from src.adapters.sqlite.clinical_alert_schema import (
    ensure_clinical_alert_storage,
)
from src.adapters.sqlite.specialist_financial_funnel_schema import (
    ensure_specialist_financial_funnel_storage,
)
from src.adapters.sqlite.specialist_financial_funnel_repo import (
    SpecialistFinancialFunnelRepository,
)
from src.adapters.sqlite.sms_governance_schema import (
    ensure_sms_governance_storage,
)
from src.adapters.sqlite.campaign_economics_schema import (
    ensure_campaign_economics_storage,
)
from src.adapters.sqlite.specialist_payer_adjustment_schema import (
    ensure_specialist_payer_adjustment_storage,
)
from src.adapters.sqlite.specialist_service_lineage_schema import (
    ensure_specialist_service_lineage_storage,
)
from src.adapters.sqlite.encounter_documentation_schema import (
    ensure_encounter_documentation_storage,
)
from src.adapters.sqlite.encounter_plan_commitment_schema import (
    ensure_encounter_plan_commitment_storage,
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
from src.services.first_run_service import FirstRunService


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
        "clinical_alerts",
        "clinical_alert_events",
        "encounter_appointment_links",
        "encounter_appointment_link_events",
        "specialist_financial_observations",
        "sms_consent_events",
        "sms_message_governance",
        "sms_delivery_events",
        "campaign_lifecycle_events",
        "campaign_audience_snapshots",
        "campaign_audience_members",
        "campaign_response_events",
        "campaign_journey_attribution_events",
        "campaign_wallet_grant_events",
        "campaign_message_cost_events",
        "specialist_payer_breakdown_observations",
        "specialist_financial_adjustment_events",
        "specialist_financial_review_events",
        "specialist_service_snapshot_manifests",
        "specialist_service_line_observations",
        "care_encounter_document_requirements",
        "care_encounter_document_events",
        "care_plan_commitments",
        "care_plan_commitment_task_links",
        "care_plan_commitment_events",
    }
)


def _readiness_checks() -> dict[str, bool]:
    db = get_db()
    ensure_security_permission_storage(db)
    ensure_operational_lease_storage(db)
    ensure_specialist_revenue_boundary_storage(db)
    ensure_followup_operations_storage(db)
    ensure_clinical_task_contract_storage(db)
    ensure_clinical_alert_storage(db)
    ensure_specialist_financial_funnel_storage(db)
    ensure_sms_governance_storage(db)
    ensure_campaign_economics_storage(db)
    ensure_specialist_payer_adjustment_storage(db)
    ensure_specialist_service_lineage_storage(db)
    ensure_encounter_documentation_storage(db)
    ensure_encounter_plan_commitment_storage(db)
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
    finance_scope = SpecialistFinancialFunnelRepository(db).reconciliation_scope()
    finance_projection_ok = finance_scope["missing_observations"] == 0
    ungoverned_messages = db.execute(
        """SELECT COUNT(*) AS count FROM sms_messages message
           WHERE NOT EXISTS (
               SELECT 1 FROM sms_message_governance governance
               WHERE governance.message_id=message.id
           )"""
    ).fetchone()["count"]
    sms_governance_ok = int(ungoverned_messages or 0) == 0
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
    payer_orphan = db.execute(
        """SELECT 1 FROM specialist_payer_breakdown_observations payer
           LEFT JOIN specialist_financial_observations observation
             ON observation.id=payer.financial_observation_id
           WHERE observation.id IS NULL LIMIT 1"""
    ).fetchone()
    payer_adjustment_storage_ok = payer_orphan is None
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
        "database": integrity_ok,
        "schema": schema_ok,
        "first_run": not FirstRunService().setup_required(),
        "activation": activation_ok,
        "audit": audit_ok,
        "worker": worker_ok,
        "revenue_scope": revenue_scope_ok,
        "finance_projection": finance_projection_ok,
        "sms_governance": sms_governance_ok,
        "campaign_economics": campaign_economics_ok,
        "payer_adjustments": payer_adjustment_storage_ok,
        "service_lineage": service_lineage_ok,
        "encounter_documentation": encounter_documentation_ok,
        "encounter_plan_commitments": encounter_plan_ok,
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
            "first_run": False,
            "activation": False,
            "audit": False,
            "worker": False,
            "revenue_scope": False,
            "finance_projection": False,
            "sms_governance": False,
            "campaign_economics": False,
            "payer_adjustments": False,
            "service_lineage": False,
            "encounter_documentation": False,
            "encounter_plan_commitments": False,
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
            "first_run": False,
            "activation": False,
            "audit": False,
            "worker": False,
            "revenue_scope": False,
            "finance_projection": False,
            "sms_governance": False,
            "campaign_economics": False,
            "payer_adjustments": False,
            "service_lineage": False,
            "encounter_documentation": False,
            "encounter_plan_commitments": False,
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

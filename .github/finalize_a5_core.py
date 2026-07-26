from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A5 target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A5 anchor missing in {relative}: {old[:180]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Database guard: legacy claim paths cannot submit an ungoverned message.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/adapters/sqlite/sms_governance_schema.py",
    '''        CREATE TRIGGER IF NOT EXISTS trg_sms_delivery_no_update
''',
    '''        CREATE TRIGGER IF NOT EXISTS trg_sms_message_submission_governance
        BEFORE UPDATE OF delivery_status ON sms_messages
        WHEN NEW.delivery_status='Submitting' AND NOT EXISTS (
            SELECT 1 FROM sms_message_governance governance
            WHERE governance.message_id=NEW.id
              AND governance.allowed_at_submission=1
              AND governance.consent_decision='GRANTED'
              AND governance.provider_name=NEW.provider
        )
        BEGIN SELECT RAISE(ABORT, 'SMS submission requires governed consent'); END;

        CREATE TRIGGER IF NOT EXISTS trg_sms_delivery_no_update
''',
)

# ---------------------------------------------------------------------------
# Bootstrap and health/readiness.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    from src.adapters.sqlite.clinical_validation_schema import (
        ensure_clinical_validation_storage,
    )
''',
    '''    from src.adapters.sqlite.sms_governance_schema import (
        ensure_sms_governance_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
        ensure_clinical_validation_storage,
    )
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    ensure_specialist_financial_funnel_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_specialist_financial_funnel_storage(db)
    ensure_sms_governance_storage(db)
    ensure_clinical_validation_storage(db)
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''from src.adapters.sqlite.clinical_validation_schema import (
    ensure_clinical_validation_storage,
)
''',
    '''from src.adapters.sqlite.sms_governance_schema import (
    ensure_sms_governance_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
    ensure_clinical_validation_storage,
)
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "specialist_financial_observations",
    }
)''',
    '''        "specialist_financial_observations",
        "sms_consent_events",
        "sms_message_governance",
        "sms_delivery_events",
    }
)''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    ensure_specialist_financial_funnel_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_specialist_financial_funnel_storage(db)
    ensure_sms_governance_storage(db)
    ensure_clinical_validation_storage(db)
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    finance_scope = SpecialistFinancialFunnelRepository(db).reconciliation_scope()
    finance_projection_ok = finance_scope["missing_observations"] == 0

    return {
''',
    '''    finance_scope = SpecialistFinancialFunnelRepository(db).reconciliation_scope()
    finance_projection_ok = finance_scope["missing_observations"] == 0
    ungoverned_messages = db.execute(
        """SELECT COUNT(*) AS count FROM sms_messages message
           WHERE NOT EXISTS (
               SELECT 1 FROM sms_message_governance governance
               WHERE governance.message_id=message.id
           )"""
    ).fetchone()["count"]
    sms_governance_ok = int(ungoverned_messages or 0) == 0

    return {
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "finance_projection": finance_projection_ok,
    }
''',
    '''        "finance_projection": finance_projection_ok,
        "sms_governance": sms_governance_ok,
    }
''',
)
# There are two fail-closed dictionaries (public and details).
health_path = target("specialist_clinic/src/api/health.py")
health = health_path.read_text(encoding="utf-8")
health = health.replace(
    '''            "finance_projection": False,
        }
''',
    '''            "finance_projection": False,
            "sms_governance": False,
        }
''',
)
health = health.replace(
    '''            "revenue_scope": False,
        }
        error = "health_check_failed"
''',
    '''            "revenue_scope": False,
            "finance_projection": False,
            "sms_governance": False,
        }
        error = "health_check_failed"
''',
)
health_path.write_text(health, encoding="utf-8")

# ---------------------------------------------------------------------------
# Tamper-evident audit scope.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''from src.adapters.sqlite.specialist_financial_funnel_schema import (
    ensure_specialist_financial_funnel_storage,
)
''',
    '''from src.adapters.sqlite.specialist_financial_funnel_schema import (
    ensure_specialist_financial_funnel_storage,
)
from src.adapters.sqlite.sms_governance_schema import (
    ensure_sms_governance_storage,
)
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    'SCOPE_VERSION = "1.6-specialist-attendance-collection"',
    'SCOPE_VERSION = "1.7-sms-governance"',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''    "specialist_financial_observations",
    "security_permission_events",
''',
    '''    "specialist_financial_observations",
    "sms_consent_events",
    "sms_message_governance",
    "sms_delivery_events",
    "security_permission_events",
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''        ensure_specialist_financial_funnel_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
    '''        ensure_specialist_financial_funnel_storage(db)
        ensure_sms_governance_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
)

# ---------------------------------------------------------------------------
# Fine-grained SMS permissions.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/security/permissions.py",
    '''    CLINICAL_ALERT_RESOLVE = "clinical.alert.resolve"
    RULE_REVIEW_CLINICAL = "rule.review.clinical"
''',
    '''    CLINICAL_ALERT_RESOLVE = "clinical.alert.resolve"
    SMS_VIEW = "sms.view"
    SMS_TEMPLATE_MANAGE = "sms.template.manage"
    SMS_APPROVAL_REVIEW = "sms.approval.review"
    SMS_SINGLE_SEND = "sms.send.single"
    SMS_CAMPAIGN_CREATE = "sms.campaign.create"
    SMS_CAMPAIGN_SEND = "sms.campaign.send"
    SMS_DELIVERY_RECONCILE = "sms.delivery.reconcile"
    SMS_SETTINGS_MANAGE = "sms.settings.manage"
    SMS_CONSENT_MANAGE = "sms.consent.manage"
    RULE_REVIEW_CLINICAL = "rule.review.clinical"
''',
)
replace_once(
    "specialist_clinic/src/security/permissions.py",
    '''            Permission.CLINICAL_ALERT_ACKNOWLEDGE,
        }
''',
    '''            Permission.CLINICAL_ALERT_ACKNOWLEDGE,
            Permission.SMS_VIEW,
            Permission.SMS_APPROVAL_REVIEW,
            Permission.SMS_SINGLE_SEND,
            Permission.SMS_DELIVERY_RECONCILE,
            Permission.SMS_CONSENT_MANAGE,
        }
''',
)

# ---------------------------------------------------------------------------
# Compatibility repository: honest provider readiness and campaign counts.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/adapters/sqlite/sms_repo.py",
    '''    def provider_configured(self) -> bool:
        """True if any SMS panel (Kavenegar or Mediana) has an API key set."""
        return bool((self.get_setting('kavenegar_api_key') or '').strip()
                    or (self.get_setting('mediana_api_key') or '').strip())
''',
    '''    def provider_configured(self) -> bool:
        """True when at least one provider credential is securely resolvable."""
        from src.services.sms.secret_resolver import configured_sms_providers
        return bool(configured_sms_providers())
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/sms_repo.py",
    '''        row = db.execute("""SELECT COUNT(*) total,
            SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) sent,
            SUM(CASE WHEN delivery_status='Delivered' THEN 1 ELSE 0 END) delivered,
            SUM(CASE WHEN delivery_status IN ('PendingApproval','WaitingForSend','Sending','SendToOperator','Sent') THEN 1 ELSE 0 END) pending,
''',
    '''        row = db.execute("""SELECT COUNT(*) total,
            SUM(CASE WHEN status IN ('accepted','sent','delivered') THEN 1 ELSE 0 END) sent,
            SUM(CASE WHEN delivery_status='Delivered' THEN 1 ELSE 0 END) delivered,
            SUM(CASE WHEN delivery_status IN ('Accepted','Queued','Submitting','Scheduled','PendingApproval','WaitingForSend','Sending','SendToOperator','Sent') THEN 1 ELSE 0 END) pending,
''',
)

# ---------------------------------------------------------------------------
# Engagement: CARE consent replaces the legacy global boolean.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/services/engagement_service.py",
    '''from src.services.sms.compliance import sanitize
''',
    '''from src.services.sms.compliance import sanitize
from src.services.sms.governance_service import (
    SmsConsentDenied,
    SmsGovernanceService,
)
''',
)
replace_once(
    "specialist_clinic/src/services/engagement_service.py",
    '''            """SELECT id, full_name, phone_number, sms_opt_out
               FROM patient_links WHERE id=?""",
''',
    '''            """SELECT id, full_name, phone_number
               FROM patient_links WHERE id=?""",
''',
)
replace_once(
    "specialist_clinic/src/services/engagement_service.py",
    '''        opted_out = bool(patient["sms_opt_out"])
        has_phone = bool(patient["phone_number"])
''',
    '''        try:
            SmsGovernanceService().require_allowed(
                patient_link_id=patient_link_id,
                purpose="CARE",
            )
            opted_out = False
        except SmsConsentDenied:
            opted_out = True
        has_phone = bool(patient["phone_number"])
''',
)
# Approval path has a second patient query and boolean check.
replace_once(
    "specialist_clinic/src/services/engagement_service.py",
    '''            """SELECT id, full_name, phone_number, sms_opt_out
                FROM patient_links WHERE id=?""",
''',
    '''            """SELECT id, full_name, phone_number
                FROM patient_links WHERE id=?""",
''',
)
replace_once(
    "specialist_clinic/src/services/engagement_service.py",
    '''        if (
            not patient
            or not patient["phone_number"]
            or patient["sms_opt_out"]
        ):
''',
    '''        consent_denied = False
        if patient:
            try:
                SmsGovernanceService().require_allowed(
                    patient_link_id=int(approval["patient_link_id"]),
                    purpose="CARE",
                )
            except SmsConsentDenied:
                consent_denied = True
        if not patient or not patient["phone_number"] or consent_denied:
''',
)
replace_once(
    "specialist_clinic/src/services/engagement_service.py",
    '''                source_type="engagement",
                source_ref=str(approval_id),
            )
''',
    '''                source_type="engagement",
                source_ref=str(approval_id),
                purpose="CARE",
                created_by=decided_by,
            )
''',
)

# ---------------------------------------------------------------------------
# Scheduler treats messaging failures as failed jobs.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/services/scheduler.py",
    '''        for campaign in SmsRepository().due_campaigns():
            run_campaign(campaign["id"])
        return True
''',
    '''        failures = 0
        for campaign in SmsRepository().due_campaigns():
            result = run_campaign(campaign["id"])
            failures += int(bool(result.get("error")))
        if failures:
            logger.error("[scheduler] due campaigns failed=%s", failures)
            return False
        return True
''',
)
replace_once(
    "specialist_clinic/src/services/scheduler.py",
    '''        DeliveryService().reconcile()
        return True
''',
    '''        result = DeliveryService().reconcile()
        if result["errors"]:
            logger.error(
                "[scheduler] SMS delivery reconciliation errors=%s providers=%s",
                result["errors"],
                result.get("provider_errors") or {},
            )
            return False
        return True
''',
)

Path(__file__).unlink()

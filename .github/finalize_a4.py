from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A4 anchor missing in {relative}: {old[:180]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Canonical bootstrap.
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    from src.adapters.sqlite.clinical_alert_schema import (
        ensure_clinical_alert_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
''',
    '''    from src.adapters.sqlite.clinical_alert_schema import (
        ensure_clinical_alert_storage,
    )
    from src.adapters.sqlite.specialist_financial_funnel_schema import (
        ensure_specialist_financial_funnel_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    ensure_clinical_task_contract_storage(db)
    ensure_clinical_alert_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_clinical_task_contract_storage(db)
    ensure_clinical_alert_storage(db)
    ensure_specialist_financial_funnel_storage(db)
    ensure_clinical_validation_storage(db)
''',
)

# PHI-free health schema and finance completeness check.
replace_once(
    "specialist_clinic/src/api/health.py",
    '''from src.adapters.sqlite.clinical_alert_schema import (
    ensure_clinical_alert_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
''',
    '''from src.adapters.sqlite.clinical_alert_schema import (
    ensure_clinical_alert_storage,
)
from src.adapters.sqlite.specialist_financial_funnel_schema import (
    ensure_specialist_financial_funnel_storage,
)
from src.adapters.sqlite.specialist_financial_funnel_repo import (
    SpecialistFinancialFunnelRepository,
)
from src.adapters.sqlite.clinical_validation_schema import (
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "clinical_alerts",
        "clinical_alert_events",
''',
    '''        "clinical_alerts",
        "clinical_alert_events",
        "encounter_appointment_links",
        "encounter_appointment_link_events",
        "specialist_financial_observations",
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    ensure_clinical_task_contract_storage(db)
    ensure_clinical_alert_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_clinical_task_contract_storage(db)
    ensure_clinical_alert_storage(db)
    ensure_specialist_financial_funnel_storage(db)
    ensure_clinical_validation_storage(db)
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    revenue_scope_ok = SpecialistEnrollmentRepository(
        db
    ).missing_scope_count() == 0

    return {
''',
    '''    revenue_scope_ok = SpecialistEnrollmentRepository(
        db
    ).missing_scope_count() == 0
    finance_scope = SpecialistFinancialFunnelRepository(db).reconciliation_scope()
    finance_projection_ok = finance_scope["missing_observations"] == 0

    return {
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "worker": worker_ok,
        "revenue_scope": revenue_scope_ok,
''',
    '''        "worker": worker_ok,
        "revenue_scope": revenue_scope_ok,
        "finance_projection": finance_projection_ok,
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''            "worker": False,
            "revenue_scope": False,
''',
    '''            "worker": False,
            "revenue_scope": False,
            "finance_projection": False,
''',
)

# Hash checkpoint includes appointment/funnel and financial snapshots.
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    'SCOPE_VERSION = "1.5-clinical-alert-lifecycle"',
    'SCOPE_VERSION = "1.6-specialist-attendance-collection"',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''from src.adapters.sqlite.clinical_alert_schema import (
    ensure_clinical_alert_storage,
)
from src.common.utils import iran_now
''',
    '''from src.adapters.sqlite.clinical_alert_schema import (
    ensure_clinical_alert_storage,
)
from src.adapters.sqlite.specialist_financial_funnel_schema import (
    ensure_specialist_financial_funnel_storage,
)
from src.common.utils import iran_now
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''    "clinical_alerts",
    "clinical_alert_events",
    "security_permission_events",
''',
    '''    "clinical_alerts",
    "clinical_alert_events",
    "encounter_appointment_links",
    "encounter_appointment_link_events",
    "specialist_financial_observations",
    "security_permission_events",
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''        ensure_specialist_revenue_boundary_storage(db)
        ensure_clinical_alert_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
    '''        ensure_specialist_revenue_boundary_storage(db)
        ensure_clinical_alert_storage(db)
        ensure_specialist_financial_funnel_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
)

# Leased two-minute financial reconciliation.
replace_once(
    "specialist_clinic/src/services/scheduler.py",
    '''            self._run_once(
                job_name="invoice-sync",
                period_key=period,
                lease=lease,
                callback=self._sync_invoices,
            )
            self._run_once(
                job_name="due-campaigns",
''',
    '''            self._run_once(
                job_name="invoice-sync",
                period_key=period,
                lease=lease,
                callback=self._sync_invoices,
            )
            self._run_once(
                job_name="specialist-financial-reconciliation",
                period_key=period,
                lease=lease,
                callback=self._reconcile_specialist_finance,
            )
            self._run_once(
                job_name="due-campaigns",
''',
)
replace_once(
    "specialist_clinic/src/services/scheduler.py",
    '''    def _run_due_campaigns(self):
        from src.adapters.sqlite.sms_repo import SmsRepository
''',
    '''    def _reconcile_specialist_finance(self):
        from src.services.specialist_financial_reconciliation_service import (
            SpecialistFinancialReconciliationService,
        )

        result = SpecialistFinancialReconciliationService().reconcile_all()
        if result["changed"]:
            logger.info(
                "[scheduler] specialist finance snapshots changed=%s observed=%s",
                result["changed"],
                result["observed"],
            )
        if result["issues"]:
            logger.error(
                "[scheduler] specialist finance reconciliation issues=%s",
                len(result["issues"]),
            )
            return False
        return True

    def _run_due_campaigns(self):
        from src.adapters.sqlite.sms_repo import SmsRepository
''',
)

# Permanent project contract.
claude = ROOT / "specialist_clinic/CLAUDE.md"
text = claude.read_text(encoding="utf-8")
marker = "## قرارداد حضور تا وصول (A4)"
if marker not in text:
    text = text.rstrip() + '''\n\n## قرارداد حضور تا وصول (A4)\n\n- booking، attendance، service completion، invoice closure و collection پنج مرحله مستقل‌اند و نباید با یکدیگر معادل گرفته شوند.\n- appointment فقط با انتخاب صریح و validation همان بیمار/همان روز به Encounter لینک می‌شود؛ matching حدسی ممنوع است.\n- attendance از `care_encounter_events.STARTED` و service completion از latest `COMPLETED` استخراج می‌شود.\n- مشاهده مالی فقط برای invoice دارای attribution جاری و Encounter تکمیل‌شده مجاز است.\n- دیتابیس حسابداری فقط با `mode=ro` و `query_only=ON` خوانده می‌شود؛ snapshot محلی append-only است.\n- Dashboard فقط latest snapshot کامل و تازه را منتشر می‌کند؛ missing/stale/error هرگز به صفر تبدیل نمی‌شود.\n- collection از `invoice_item_payments.is_paid=1` در سطح item مشتق می‌شود؛ wallet داخلی معادل وصول حسابداری نیست.\n'''
    claude.write_text(text, encoding="utf-8")

Path(__file__).unlink()

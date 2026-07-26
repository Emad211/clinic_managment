from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A3 anchor missing in {relative}: {old[:160]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Canonical schema bootstrap.
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    from src.adapters.sqlite.clinical_task_contract_schema import (
        ensure_clinical_task_contract_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
''',
    '''    from src.adapters.sqlite.clinical_task_contract_schema import (
        ensure_clinical_task_contract_storage,
    )
    from src.adapters.sqlite.clinical_alert_schema import (
        ensure_clinical_alert_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    ensure_followup_operations_storage(db)
    ensure_clinical_task_contract_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_followup_operations_storage(db)
    ensure_clinical_task_contract_storage(db)
    ensure_clinical_alert_storage(db)
    ensure_clinical_validation_storage(db)
''',
)

# PHI-free readiness verifies the alert schema exists.
replace_once(
    "specialist_clinic/src/api/health.py",
    '''from src.adapters.sqlite.clinical_task_contract_schema import (
    ensure_clinical_task_contract_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
''',
    '''from src.adapters.sqlite.clinical_task_contract_schema import (
    ensure_clinical_task_contract_storage,
)
from src.adapters.sqlite.clinical_alert_schema import (
    ensure_clinical_alert_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "clinical_task_contracts",
        "clinical_outcome_canonical_links",
''',
    '''        "clinical_task_contracts",
        "clinical_outcome_canonical_links",
        "clinical_alerts",
        "clinical_alert_events",
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    ensure_followup_operations_storage(db)
    ensure_clinical_task_contract_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_followup_operations_storage(db)
    ensure_clinical_task_contract_storage(db)
    ensure_clinical_alert_storage(db)
    ensure_clinical_validation_storage(db)
''',
)

# Tamper-evident audit scope includes roots and lifecycle events.
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    'SCOPE_VERSION = "1.4-clinical-task-contracts"',
    'SCOPE_VERSION = "1.5-clinical-alert-lifecycle"',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''from src.adapters.sqlite.specialist_revenue_boundary_schema import (
    ensure_specialist_revenue_boundary_storage,
)
from src.common.utils import iran_now
''',
    '''from src.adapters.sqlite.specialist_revenue_boundary_schema import (
    ensure_specialist_revenue_boundary_storage,
)
from src.adapters.sqlite.clinical_alert_schema import (
    ensure_clinical_alert_storage,
)
from src.common.utils import iran_now
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''    "clinical_task_contracts",
    "clinical_outcome_canonical_links",
    "security_permission_events",
''',
    '''    "clinical_task_contracts",
    "clinical_outcome_canonical_links",
    "clinical_alerts",
    "clinical_alert_events",
    "security_permission_events",
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''        ensure_specialist_revenue_boundary_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
    '''        ensure_specialist_revenue_boundary_storage(db)
        ensure_clinical_alert_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
)

# Register the alert workspace.
replace_once(
    "specialist_clinic/src/app.py",
    '''    from src.api.clinical_reconciliation import (
        bp as clinical_reconciliation_bp,
    )
    from src.api.control_room import bp as control_room_bp
''',
    '''    from src.api.clinical_reconciliation import (
        bp as clinical_reconciliation_bp,
    )
    from src.api.clinical_alerts import bp as clinical_alerts_bp
    from src.api.control_room import bp as control_room_bp
''',
)
replace_once(
    "specialist_clinic/src/app.py",
    '''        clinical_reconciliation_bp,
        vitals_bp,
''',
    '''        clinical_reconciliation_bp,
        clinical_alerts_bp,
        vitals_bp,
''',
)

# Alert badge in the existing operational hub.
replace_once(
    "specialist_clinic/src/templates/sms/_hub_tabs.html",
    "   'campaigns' | 'messages' | 'approvals' | 'engagement' | 'worklist'. #}",
    "   'campaigns' | 'messages' | 'approvals' | 'engagement' | 'alerts' | 'worklist'. #}",
)
replace_once(
    "specialist_clinic/src/templates/sms/_hub_tabs.html",
    '''        <a class="btn btn-sm hub-nav-btn {% if hub_tab=='worklist' %}btn{% else %}btn-ghost{% endif %}"{% if hub_tab=='worklist' %} aria-current="page"{% endif %} href="{{ url_for('followups.worklist') }}"><svg class="icon icon-sm"><use href="#i-list-checks"></use></svg> ورک‌لیستِ تماس</a>
''',
    '''        {% if permissions.get('clinical.alert.view') %}
        <a class="btn btn-sm hub-nav-btn {% if hub_tab=='alerts' %}btn{% else %}btn-ghost{% endif %}"{% if hub_tab=='alerts' %} aria-current="page"{% endif %} href="{{ url_for('clinical_alerts.index') }}"><svg class="icon icon-sm"><use href="#i-alert"></use></svg> هشدارهای بالینی{% if alert_pending %} <span class="pill pill-danger">{{ alert_pending|fa_num }}</span>{% endif %}</a>
        {% endif %}
        <a class="btn btn-sm hub-nav-btn {% if hub_tab=='worklist' %}btn{% else %}btn-ghost{% endif %}"{% if hub_tab=='worklist' %} aria-current="page"{% endif %} href="{{ url_for('followups.worklist') }}"><svg class="icon icon-sm"><use href="#i-list-checks"></use></svg> ورک‌لیستِ تماس</a>
''',
)

# Worklist exposes the count and reports alert creation separately from tasks.
replace_once(
    "specialist_clinic/src/api/followups.py",
    '''from src.services.clinical_care_loop_service import (
''',
    '''from src.services.clinical_alert_service import ClinicalAlertService
from src.services.clinical_care_loop_service import (
''',
)
replace_once(
    "specialist_clinic/src/api/followups.py",
    '''        hub_pending=EngagementRepository().count_pending(),
        active_page="sms",
''',
    '''        hub_pending=EngagementRepository().count_pending(),
        alert_pending=(
            len(ClinicalAlertService().list_open())
            if has_permission(Permission.CLINICAL_ALERT_VIEW)
            else 0
        ),
        active_page="sms",
''',
)
replace_once(
    "specialist_clinic/src/api/followups.py",
    '''    flash(
        f"{total} پیگیریِ جدید ساخته شد"
        if total
        else "پیگیریِ جدیدِ سررسیده‌ای نبود",
        "success",
    )
''',
    '''    alerts_created = int(result.get("clinical_alerts") or 0)
    flash(
        f"{total} پیگیری و {alerts_created} هشدار بالینی جدید ساخته شد"
        if total or alerts_created
        else "پیگیری یا هشدار جدیدی نبود",
        "success",
    )
''',
)

# Leased scheduler discovers and escalates alerts every two-minute bucket.
replace_once(
    "specialist_clinic/src/services/scheduler.py",
    '''            period = self._bucket(now)
            self._run_once(
                job_name="administrative-engagement",
''',
    '''            period = self._bucket(now)
            self._run_once(
                job_name="clinical-alerts",
                period_key=period,
                lease=lease,
                callback=self._run_clinical_alerts,
            )
            self._run_once(
                job_name="administrative-engagement",
''',
)
replace_once(
    "specialist_clinic/src/services/scheduler.py",
    '''    def _run_engagement(self):
        from src.services.engagement_service import EngagementService
''',
    '''    def _run_clinical_alerts(self):
        from src.services.clinical_alert_service import ClinicalAlertService

        service = ClinicalAlertService()
        generated = service.generate_all()
        escalated = service.escalate_due(now=iran_now())
        if generated["created"] or escalated:
            logger.warning(
                "[scheduler] clinical alerts created=%s escalated=%s",
                generated["created"],
                len(escalated),
            )
        if generated["issues"]:
            logger.error(
                "[scheduler] clinical alerts had %s projection issue(s)",
                len(generated["issues"]),
            )
            return False
        return True

    def _run_engagement(self):
        from src.services.engagement_service import EngagementService
''',
)

# Project rule for future work.
claude = ROOT / "specialist_clinic/CLAUDE.md"
text = claude.read_text(encoding="utf-8")
marker = "## قرارداد هشدار بالینی داخلی (A3)"
if marker not in text:
    text = text.rstrip() + '''\n\n## قرارداد هشدار بالینی داخلی (A3)\n\n- خروجی `redflag` یا `safety_alert` فقط یک تعهد داخلی برای مشاهده و تصمیم انسانی ایجاد می‌کند؛ SMS، ارجاع، نوبت یا اقدام درمانی خودکار ممنوع است.\n- هر هشدار به exact current run و CREATED recommendation event متصل، immutable و دارای lifecycle افزایشی است.\n- `ACKNOWLEDGED` مسئول رسیدگی را ثبت می‌کند؛ `RESOLVED` فقط با آخرین decision event پزشک روی همان recommendation و یادداشت جمع‌بندی مجاز است.\n- Ruleهایی که نیازمند تأیید پزشک‌اند فقط پس از latest decision=`ACCEPTED` task می‌سازند و repository همان decision را دوباره داخل transaction بررسی می‌کند.\n'''
    claude.write_text(text, encoding="utf-8")

Path(__file__).unlink()

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"missing patch target: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"patch anchor missing in {relative}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if old not in text:
        if new in text:
            return
        raise AssertionError(f"patch anchor missing in {relative}: {old[:120]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def append_once(relative: str, marker: str, body: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    path.write_text(text.rstrip() + "\n\n" + body.strip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Canonical bootstrap: specialist cutover and journey storage is not optional.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    from src.adapters.sqlite.clinical_validation_schema import (
        ensure_clinical_validation_storage,
    )
''',
    '''    from src.adapters.sqlite.specialist_revenue_boundary_schema import (
        ensure_specialist_revenue_boundary_storage,
    )
    from src.adapters.sqlite.clinical_validation_schema import (
        ensure_clinical_validation_storage,
    )
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    ensure_security_permission_storage(db)
    ensure_operational_lease_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_security_permission_storage(db)
    ensure_operational_lease_storage(db)
    ensure_specialist_revenue_boundary_storage(db)
    ensure_clinical_validation_storage(db)
''',
)

# ---------------------------------------------------------------------------
# Readiness: a linked accounting patient without an immutable cutover is unsafe.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/api/health.py",
    '''from src.adapters.sqlite.operational_lease_schema import (
    ensure_operational_lease_storage,
)
''',
    '''from src.adapters.sqlite.operational_lease_schema import (
    ensure_operational_lease_storage,
)
from src.adapters.sqlite.specialist_enrollment_repo import (
    SpecialistEnrollmentRepository,
)
from src.adapters.sqlite.specialist_revenue_boundary_schema import (
    ensure_specialist_revenue_boundary_storage,
)
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "clinical_validation_reports",
        "clinical_validation_attestations",
''',
    '''        "clinical_validation_reports",
        "clinical_validation_attestations",
        "specialist_program_enrollments",
        "care_journeys",
        "care_journey_events",
        "care_encounters",
        "care_encounter_events",
        "accounting_invoice_attribution_events",
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    ensure_security_permission_storage(db)
    ensure_operational_lease_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_security_permission_storage(db)
    ensure_operational_lease_storage(db)
    ensure_specialist_revenue_boundary_storage(db)
    ensure_clinical_validation_storage(db)
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    worker_ok = stuck is None

    return {
''',
    '''    worker_ok = stuck is None
    revenue_scope_ok = SpecialistEnrollmentRepository(
        db
    ).missing_scope_count() == 0

    return {
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "audit": audit_ok,
        "worker": worker_ok,
''',
    '''        "audit": audit_ok,
        "worker": worker_ok,
        "revenue_scope": revenue_scope_ok,
''',
)
replace_all(
    "specialist_clinic/src/api/health.py",
    '''            "audit": False,
            "worker": False,
''',
    '''            "audit": False,
            "worker": False,
            "revenue_scope": False,
''',
)

# ---------------------------------------------------------------------------
# Tamper evidence covers cutover, Journey, Encounter and attribution.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    'SCOPE_VERSION = "1.1-validation-release"',
    'SCOPE_VERSION = "1.2-specialist-revenue-boundary"',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''from src.adapters.sqlite.core import get_db
''',
    '''from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.specialist_revenue_boundary_schema import (
    ensure_specialist_revenue_boundary_storage,
)
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''    "clinical_validation_attestations",
    "security_permission_events",
''',
    '''    "clinical_validation_attestations",
    "specialist_program_enrollments",
    "care_journeys",
    "care_journey_events",
    "care_encounters",
    "care_encounter_events",
    "accounting_invoice_attribution_events",
    "security_permission_events",
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''        db = self._connection or get_db()
        ensure_clinical_audit_integrity_storage(db)
''',
    '''        db = self._connection or get_db()
        ensure_specialist_revenue_boundary_storage(db)
        ensure_clinical_audit_integrity_storage(db)
''',
)

# ---------------------------------------------------------------------------
# Dashboard communicates scope and uncertainty instead of persuasive false KPIs.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/templates/dashboard.html",
    '''{% endif %}

{% if revenue.available %}
''',
    '''{% endif %}

{% if bridge_ok and not revenue.available %}
<div class="alert-banner alert-warn">
    <svg class="icon"><use href="#i-alert"></use></svg>
    <span>
        دامنهٔ مالی مطب تخصصی قابل محاسبه نیست
        {% if revenue.error_code %}(<code>{{ revenue.error_code }}</code>){% endif %}.
        هیچ عدد صفرِ حدسی نمایش داده نمی‌شود.
    </span>
</div>
{% endif %}

{% if revenue.available %}
''',
)
replace_once(
    "specialist_clinic/src/templates/dashboard.html",
    '''<svg class="icon"><use href="#i-banknote"></use></svg> درآمد بیماران مطب تخصصی
        <span class="section-sub">— از سامانه حسابداری؛ «وصول‌شده» = آیتم‌های پرداخت‌شده، «صورتحساب» = کل مبلغِ فاکتورهای بسته</span>''',
    '''<svg class="icon"><use href="#i-banknote"></use></svg> درآمد منتسب و تأییدشدهٔ مطب تخصصی
        <span class="section-sub">فقط فاکتورهای دارای Journey و Encounter تخصصی؛ مراجعات تاریخی و عمومی فقط در پرونده دیده می‌شوند و از درآمد حذف‌اند.</span>''',
)
replace_once(
    "specialist_clinic/src/templates/dashboard.html",
    '''<div class="num c-violet">{{ revenue.campaigns.attributed_total|fa_num }}</div>
            <div class="label">درآمد منتسب به کمپین‌ها (تومان)</div>''',
    '''<div class="num c-violet">{% if revenue.campaigns.safe_to_sum %}{{ revenue.campaigns.attributed_total|fa_num }}{% else %}—{% endif %}</div>
            <div class="label">درآمد کمپین <span class="muted">{% if not revenue.campaigns.safe_to_sum %}(نیازمند اتصال Journey){% endif %}</span></div>''',
)
replace_once(
    "specialist_clinic/src/templates/dashboard.html",
    '''<span class="badge badge-muted">{{ revenue.total.invoices|fa_num }} فاکتور بسته · {{ revenue.enrolled|fa_num }} بیمار متصل</span>''',
    '''<span class="badge badge-muted">{{ revenue.total.invoices|fa_num }} فاکتور منتسب · {{ revenue.enrolled|fa_num }} عضو برنامهٔ تخصصی</span>
        <span class="badge badge-info">تاریخچهٔ قبل از ورود: قابل مشاهده، خارج از درآمد</span>''',
)
replace_once(
    "specialist_clinic/src/templates/dashboard.html",
    '''<svg class="icon icon-sm"><use href="#i-bar-chart"></use></svg> روند درآمد ۳۰ روز اخیر (تومان)''',
    '''<svg class="icon icon-sm"><use href="#i-bar-chart"></use></svg> روند وصول فاکتورهای منتسب تخصصی در ۳۰ روز اخیر (تومان)''',
)
replace_once(
    "specialist_clinic/src/templates/dashboard.html",
    '''data:{ labels:rev.labels, datasets:[{ label:'درآمد', data:rev.values,''',
    '''data:{ labels:rev.labels, datasets:[{ label:'وصول تخصصی منتسب', data:rev.collected_values || rev.values,''',
)

# ---------------------------------------------------------------------------
# Mandatory project guidance; old accounting history is never specialist revenue.
# ---------------------------------------------------------------------------
append_once(
    "specialist_clinic/CLAUDE.md",
    "## مرز قطعی درآمد مطب تخصصی (A0)",
    '''## مرز قطعی درآمد مطب تخصصی (A0)

- دیتابیس و کد `webapp` منبع عملیاتی شش‌ماهه و خارج از دامنهٔ نوشتن این اپ است.
- تمام دسترسی‌های حسابداری از `specialist_clinic` باید `mode=ro` و بدون migration/write باشند.
- تاریخچهٔ مراجعهٔ بیمار پس از ورود به برنامهٔ تخصصی در پرونده قابل مشاهده است، اما صرف تاریخ، کد ملی یا enrollment هیچ درآمدی را منتسب نمی‌کند.
- درآمد تخصصی فقط از فاکتور بسته‌ای محاسبه می‌شود که آخرین event آن در `accounting_invoice_attribution_events` برابر `ATTRIBUTED` و به همان enrollment، CareJourney و CareEncounter متصل باشد.
- ثبت دستی بیمار نباید به‌طور حدسی به حسابداری لینک شود. اتصال حسابداری فقط از workflow صریح enrollment و با cutover immutable انجام می‌شود.
- کمپین، پیامک و appointment تا زمانی که به Journey و invoice صریح متصل نشده‌اند حق تولید KPI درآمدی ندارند.
- نبود schema پرداخت، نبود cutover یا قطع bridge باید `unavailable` ایجاد کند؛ تبدیل خطا به درآمد صفر ممنوع است.
''',
)

# Remove abandoned transfer artifacts and this one-shot finalizer from product history.
for relative in (
    ".github/a0_bundle.part00",
    ".github/a0_parts/part000",
    ".github/finalize_a0.py",
):
    path = ROOT / relative
    if path.exists():
        path.unlink()

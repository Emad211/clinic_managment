from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def path(relative: str) -> Path:
    return ROOT / relative


def replace_once(relative: str, old: str, new: str) -> None:
    target = path(relative)
    text = target.read_text(encoding="utf-8")
    if old in text:
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        return
    if new in text:
        return
    raise AssertionError(f"patch point missing in {relative}: {old[:160]!r}")


def append_once(relative: str, marker: str, content: str) -> None:
    target = path(relative)
    text = target.read_text(encoding="utf-8")
    if marker in text:
        return
    target.write_text(text.rstrip() + "\n\n" + content.strip() + "\n", encoding="utf-8")


def write(relative: str, content: str) -> None:
    target = path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.strip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Validation hash and freshness contracts.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/adapters/sqlite/clinical_validation_repo.py",
    '            "case_bundle_hash",\n            "case_count",',
    '            "case_bundle_hash",\n            "status",\n            "case_count",',
)

repo = path("specialist_clinic/src/adapters/sqlite/clinical_validation_repo.py")
text = repo.read_text(encoding="utf-8")
start = text.index("    def latest_passing(\n")
end = text.index("    def release_evidence(\n", start)
replacement = '''    def latest_for_identity(
        self,
        *,
        engine_version: str,
        ruleset_code: str,
        package_version: str,
        package_hash: str | None = None,
    ) -> dict | None:
        sql = """SELECT * FROM clinical_validation_reports
                 WHERE engine_version=? AND ruleset_code=?
                   AND package_version=?"""
        params: list[Any] = [
            engine_version,
            ruleset_code,
            package_version,
        ]
        if package_hash is not None:
            sql += " AND package_hash=?"
            params.append(package_hash)
        sql += " ORDER BY id DESC LIMIT 1"
        return self._decode(self._db().execute(sql, params).fetchone())

    def latest_passing(
        self,
        *,
        engine_version: str,
        ruleset_code: str,
        package_version: str,
        package_hash: str | None = None,
    ) -> dict | None:
        """Return PASS only when the newest exact-identity report is PASS.

        A newer BLOCKED report invalidates every older PASS. Release qualification may
        never search backwards through history for a convenient successful result.
        """
        latest = self.latest_for_identity(
            engine_version=engine_version,
            ruleset_code=ruleset_code,
            package_version=package_version,
            package_hash=package_hash,
        )
        return latest if latest and latest["status"] == "PASS" else None

'''
repo.write_text(text[:start] + replacement + text[end:], encoding="utf-8")

replace_once(
    "specialist_clinic/src/services/clinical_engine/validation_harness.py",
    '''        return {
            **report_body,
            "status": "PASS" if all(checks.values()) else "BLOCKED",
            "report_hash": content_hash(report_body),
        }
''',
    '''        report_body["status"] = (
            "PASS" if all(checks.values()) else "BLOCKED"
        )
        return {
            **report_body,
            "report_hash": content_hash(report_body),
        }
''',
)

service = path("specialist_clinic/src/services/clinical_engine/validation_service.py")
text = service.read_text(encoding="utf-8")
start = text.index("    def dashboard(self) -> dict:\n")
replacement = '''    def dashboard(self) -> dict:
        latest = self.repository.latest_for_identity(
            engine_version=CURRENT_ENGINE_VERSION,
            ruleset_code=RULESET_CODE,
            package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
        )
        attestations = (
            self.repository.attestations(int(latest["id"]))
            if latest and latest["status"] == "PASS"
            else {}
        )
        evidence = self.current_release_evidence()
        blockers: list[str] = []
        if not latest:
            blockers.append("هنوز گزارش اعتبارسنجی برای نسخهٔ جاری ساخته نشده است.")
        elif latest["status"] != "PASS":
            blockers.append("جدیدترین اجرای اعتبارسنجی مسدود است؛ PASS قدیمی قابل استفاده نیست.")
        if latest and latest["status"] == "PASS" and "CLINICAL" not in attestations:
            blockers.append("تأیید مستقل مسئول بالینی ثبت نشده است.")
        if latest and latest["status"] == "PASS" and "TECHNICAL" not in attestations:
            blockers.append("تأیید مستقل بازبین فنی ثبت نشده است.")
        return {
            "report": latest,
            "attestations": attestations,
            "release_evidence": evidence,
            "release_ready": bool(evidence),
            "blockers": blockers,
            "package_version": CURRENT_BUNDLED_PACKAGE_VERSION,
            "engine_version": CURRENT_ENGINE_VERSION,
            "ruleset_code": RULESET_CODE,
        }
'''
service.write_text(text[:start] + replacement, encoding="utf-8")

# ---------------------------------------------------------------------------
# Canonical migration, audit and readiness wiring.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    from src.adapters.sqlite.clinical_audit_integrity_schema import (
        ensure_clinical_audit_integrity_storage,
    )
    ensure_strict_clinical_care_loop_guards(db)
    ensure_security_permission_storage(db)
    ensure_operational_lease_storage(db)
    ensure_clinical_audit_integrity_storage(db)
''',
    '''    from src.adapters.sqlite.clinical_validation_schema import (
        ensure_clinical_validation_storage,
    )
    from src.adapters.sqlite.clinical_audit_integrity_schema import (
        ensure_clinical_audit_integrity_storage,
    )
    ensure_strict_clinical_care_loop_guards(db)
    ensure_security_permission_storage(db)
    ensure_operational_lease_storage(db)
    ensure_clinical_validation_storage(db)
    ensure_clinical_audit_integrity_storage(db)
''',
)

replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    'SCOPE_VERSION = "1.0"',
    'SCOPE_VERSION = "1.1-validation-release"',
)
replace_once(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''    "clinical_outcome_events",
    "security_permission_events",
)''',
    '''    "clinical_outcome_events",
    "clinical_validation_reports",
    "clinical_validation_attestations",
    "security_permission_events",
)''',
)

replace_once(
    "specialist_clinic/src/api/health.py",
    '''from src.adapters.sqlite.operational_lease_schema import (
    ensure_operational_lease_storage,
)
''',
    '''from src.adapters.sqlite.operational_lease_schema import (
    ensure_operational_lease_storage,
)
from src.adapters.sqlite.clinical_validation_schema import (
    ensure_clinical_validation_storage,
)
''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''        "clinical_audit_checkpoints",
    }
)''',
    '''        "clinical_audit_checkpoints",
        "clinical_validation_reports",
        "clinical_validation_attestations",
    }
)''',
)
replace_once(
    "specialist_clinic/src/api/health.py",
    '''    ensure_security_permission_storage(db)
    ensure_operational_lease_storage(db)
    ensure_clinical_audit_integrity_storage(db)
''',
    '''    ensure_security_permission_storage(db)
    ensure_operational_lease_storage(db)
    ensure_clinical_validation_storage(db)
    ensure_clinical_audit_integrity_storage(db)
''',
)

# ---------------------------------------------------------------------------
# Activation report/seal binding.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/services/clinical_engine/activation.py",
    '''from src.services.clinical_engine.fact_builder import ShadowFactCapture
''',
    '''from src.services.clinical_engine.fact_builder import ShadowFactCapture
from src.services.clinical_engine.validation_service import ClinicalValidationService
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_engine/activation.py",
    '''        ruleset = self.rules.active_ruleset("general-outpatient")
        report_ok = valid_report(report)
''',
    '''        ruleset = self.rules.active_ruleset("general-outpatient")
        validation = ClinicalValidationService().dashboard()
        report_ok = valid_report(report)
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_engine/activation.py",
    '''            "ruleset": ruleset,
            "last_rollback": self.state.get_json("last_rollback"),
''',
    '''            "ruleset": ruleset,
            "validation": validation,
            "last_rollback": self.state.get_json("last_rollback"),
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_engine/activation.py",
    '''        ruleset = self.rules.active_ruleset("general-outpatient")

        for national_id in DEMO_IDS:
''',
    '''        ruleset = self.rules.active_ruleset("general-outpatient")
        validation_evidence = ClinicalValidationService().current_release_evidence()

        for national_id in DEMO_IDS:
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_engine/activation.py",
    '''            "expected_positive_controls": (
                positive_controls_ok
                if self.enforce_positive_controls
                else True
            ),
        }
''',
    '''            "expected_positive_controls": (
                positive_controls_ok
                if self.enforce_positive_controls
                else True
            ),
            "validation_release_ready": bool(validation_evidence),
        }
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_engine/activation.py",
    '''            "cohort": list(DEMO_IDS),
            "ruleset": (
''',
    '''            "cohort": list(DEMO_IDS),
            "validation": (
                {
                    "status": "PASS",
                    "engine_version": CURRENT_ENGINE_VERSION,
                    "ruleset_code": "general-outpatient",
                    "package_version": validation_evidence.get("package_version"),
                    "validation_report_id": validation_evidence["validation_report_id"],
                    "validation_report_hash": validation_evidence["validation_report_hash"],
                    "package_hash": validation_evidence["package_hash"],
                    "case_bundle_hash": validation_evidence["case_bundle_hash"],
                }
                if validation_evidence
                else {
                    "status": "BLOCKED",
                    "engine_version": CURRENT_ENGINE_VERSION,
                    "ruleset_code": "general-outpatient",
                    "package_version": None,
                    "validation_report_id": None,
                    "validation_report_hash": None,
                    "package_hash": None,
                    "case_bundle_hash": None,
                }
            ),
            "ruleset": (
''',
)
replace_once(
    "specialist_clinic/src/services/clinical_engine/activation.py",
    '''        body = {
            "mode": mode,
            "engine_version": CURRENT_ENGINE_VERSION,
            "ruleset_id": int(current["id"]),
            "report_hash": report["report_hash"],
''',
    '''        validation = report.get("validation") or {}
        body = {
            "mode": mode,
            "engine_version": CURRENT_ENGINE_VERSION,
            "ruleset_id": int(current["id"]),
            "report_hash": report["report_hash"],
            "validation_report_id": int(validation.get("validation_report_id") or 0),
            "validation_report_hash": validation.get("validation_report_hash"),
            "validation_package_hash": validation.get("package_hash"),
            "validation_case_bundle_hash": validation.get("case_bundle_hash"),
''',
)

# ---------------------------------------------------------------------------
# Manager routes and UX.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/api/manager.py",
    '''    projection["cohort"] = DemoCohortService().summary()
    requested_step = request.args.get("step", type=int)
''',
    '''    projection["cohort"] = DemoCohortService().summary()
    from src.services.clinical_engine.validation_service import ClinicalValidationService
    projection["validation"] = ClinicalValidationService().dashboard()
    requested_step = request.args.get("step", type=int)
''',
)
replace_once(
    "specialist_clinic/src/api/manager.py",
    '''        elif action == "compare":
            if not service.rules.active_ruleset("general-outpatient"):
                raise ActivationGateError("ابتدا بستهٔ قواعد v2 باید وارد، بازبینی و فریز شود")
''',
    '''        elif action == "compare":
            if not service.rules.active_ruleset("general-outpatient"):
                raise ActivationGateError("ابتدا بستهٔ قواعد v2 باید وارد، بازبینی و فریز شود")
            from src.services.clinical_engine.validation_service import ClinicalValidationService
            if not ClinicalValidationService().current_release_evidence():
                raise ActivationGateError(
                    "ابتدا اعتبارسنجی golden-case و دو تأیید مستقل بالینی و فنی را کامل کنید"
                )
''',
)

manager = path("specialist_clinic/src/api/manager.py")
text = manager.read_text(encoding="utf-8")
anchor = '\n\n@bp.route("/settings", methods=["GET", "POST"])\n'
routes = r'''

@bp.get("/clinical-engine/validation")
@login_required
def clinical_validation():
    if not any(
        has_permission(permission)
        for permission in (
            Permission.RULE_REVIEW_CLINICAL,
            Permission.RULE_REVIEW_TECHNICAL,
            Permission.RULE_ACTIVATE,
        )
    ):
        flash("مجوز مشاهدهٔ مرکز اعتبارسنجی ثبت نشده است.", "error")
        return redirect(url_for("dashboard.index"))
    from src.services.clinical_engine.validation_service import ClinicalValidationService

    return render_template(
        "manager/clinical_validation.html",
        validation=ClinicalValidationService().dashboard(),
        active_page="clinical_engine",
    )


@bp.post("/clinical-engine/validation/<action>")
@login_required
def clinical_validation_action(action):
    from src.services.clinical_engine.validation_service import (
        ClinicalValidationError,
        ClinicalValidationService,
    )

    service = ClinicalValidationService()
    actor = str(g.user["username"] or "manager").strip()
    reviewer = (
        request.form.get("reviewer") or g.user["full_name"] or actor
    ).strip()
    note = request.form.get("note", "").strip()
    try:
        if action == "run":
            if not has_permission(Permission.RULE_REVIEW_TECHNICAL):
                raise ClinicalValidationError("مجوز اجرای اعتبارسنجی فنی ثبت نشده است")
            stored = service.run_current(created_by=actor)
            flash(
                "اعتبارسنجی با وضعیت " + stored["status"] + " ثبت شد.",
                "success" if stored["status"] == "PASS" else "warning",
            )
        elif action == "attest":
            role = request.form.get("role", "").strip().lower()
            required = (
                Permission.RULE_REVIEW_CLINICAL
                if role == "clinical"
                else Permission.RULE_REVIEW_TECHNICAL
            )
            if not has_permission(required):
                raise ClinicalValidationError("مجوز تأیید این نقش ثبت نشده است")
            if request.form.get("attestation") != "yes":
                raise ClinicalValidationError("تأیید آگاهانهٔ مسئولیت الزامی است")
            service.attest_current(
                role=role,
                reviewer=reviewer,
                note=note,
                report_hash=request.form.get("report_hash", ""),
            )
            flash("تأیید مستقل به آخرین گزارش PASS متصل شد.", "success")
        else:
            raise ClinicalValidationError("عملیات اعتبارسنجی ناشناخته است")
    except (ClinicalValidationError, ValueError, LookupError) as exc:
        flash(f"عملیات انجام نشد: {exc}", "error")
    return redirect(
        url_for("manager.clinical_validation") + "#validation-workspace"
    )
'''
if routes.strip() not in text:
    if anchor not in text:
        raise AssertionError("manager validation route insertion point missing")
    text = text.replace(anchor, routes + anchor, 1)
manager.write_text(text, encoding="utf-8")

replace_once(
    "specialist_clinic/src/templates/manager/clinical_engine.html",
    '''</section>

{% set package = engine.package %}
''',
    '''</section>

<section class="engine-validation-jump" aria-label="اعتبارسنجی نهایی موتور">
    <div>
        <span class="engine-kicker">گام ۷ · دروازهٔ انتشار</span>
        <strong>Golden-case validation و دو تأیید مستقل</strong>
        <small>
            {% if engine.validation.release_ready %}
            زنجیرهٔ اعتبارسنجی نسخهٔ جاری آمادهٔ استفاده در گزارش فعال‌سازی است.
            {% elif engine.validation.report %}
            جدیدترین اجرا {{ engine.validation.report.status }} است و {{ engine.validation.blockers|length|fa_num }} مانع باقی مانده است.
            {% else %}
            پیش از آزمون ۱۰ بیمار، بستهٔ کیس‌ها را اجرا و تأییدهای بالینی و فنی را ثبت کنید.
            {% endif %}
        </small>
    </div>
    <a class="btn btn-primary" href="{{ url_for('manager.clinical_validation') }}">
        مشاهدهٔ مرکز اعتبارسنجی
    </a>
</section>

{% set package = engine.package %}
''',
)

# ---------------------------------------------------------------------------
# Dedicated validation UI and local review runner.
# ---------------------------------------------------------------------------
write(
    "specialist_clinic/src/templates/manager/clinical_validation.html",
    r'''{% extends "base.html" %}
{% block title %}اعتبارسنجی و انتشار موتور بالینی{% endblock %}
{% block content %}
<div class="crumb"><a href="{{ url_for('manager.index') }}">مدیریت</a> / <a href="{{ url_for('manager.clinical_engine') }}">موتور بالینی</a> / اعتبارسنجی نهایی</div>

<section class="validation-hero {% if validation.release_ready %}is-ready{% elif validation.report and validation.report.status == 'BLOCKED' %}is-blocked{% endif %}">
    <div>
        <span class="engine-kicker">Clinical Engine {{ validation.engine_version }}</span>
        <h1>مرکز اعتبارسنجی و دروازهٔ انتشار</h1>
        <p>هر نتیجه به نسخهٔ موتور، بستهٔ قواعد، مجموعهٔ کیس‌ها و دو بازبین مستقل متصل است. جدیدترین گزارش تعیین‌کننده است.</p>
    </div>
    <div class="validation-state">
        <small>وضعیت انتشار</small>
        <strong>{% if validation.release_ready %}آمادهٔ اتصال به activation{% elif validation.report and validation.report.status == 'BLOCKED' %}مسدود{% else %}در انتظار تکمیل{% endif %}</strong>
        <code dir="ltr">{{ validation.package_version }}</code>
    </div>
</section>

<div id="validation-workspace" class="validation-layout">
    <main class="validation-main">
        {% if validation.blockers %}
        <section class="card validation-blockers" role="alert">
            <h2>موانع فعلی</h2>
            <ul>{% for blocker in validation.blockers %}<li>{{ blocker }}</li>{% endfor %}</ul>
        </section>
        {% endif %}

        <section class="card validation-action-card">
            <div class="validation-section-head">
                <div><span class="validation-step">۱</span><div><h2>اجرای golden cases</h2><p>بستهٔ immutable فعلی دوبار اجرا می‌شود تا نتیجه و replay hash یکسان باشند.</p></div></div>
                <form method="post" action="{{ url_for('manager.clinical_validation_action', action='run') }}" data-loading-form>
                    <button class="btn btn-primary" type="submit">اجرای اعتبارسنجی نسخهٔ جاری</button>
                </form>
            </div>
        </section>

        {% set stored = validation.report %}
        {% set report = stored.report if stored else None %}
        {% if stored %}
        <section class="card validation-report-card">
            <div class="validation-report-head">
                <div>
                    <span class="status-pill {% if stored.status == 'PASS' %}is-ok{% else %}is-danger{% endif %}">{{ stored.status }}</span>
                    <h2>گزارش #{{ stored.id|fa_num }}</h2>
                    <p>{{ stored.created_at|jalali }} · {{ stored.created_by }}</p>
                </div>
                <div class="validation-hashes">
                    <label>Report hash <code dir="ltr">{{ stored.report_hash }}</code></label>
                    <label>Package hash <code dir="ltr">{{ stored.package_hash }}</code></label>
                    <label>Case bundle <code dir="ltr">{{ stored.case_bundle_hash }}</code></label>
                </div>
            </div>

            <div class="validation-kpis">
                <div><span>کیس‌ها</span><strong>{{ stored.case_count|fa_num }}</strong></div>
                <div><span>False positive</span><strong>{{ report.totals.false_positive|fa_num }}</strong></div>
                <div><span>False negative</span><strong>{{ report.totals.false_negative|fa_num }}</strong></div>
                <div><span>ERROR</span><strong>{{ report.totals.error|fa_num }}</strong></div>
            </div>

            <div class="validation-check-grid">
                {% for key, passed in report.checks.items() %}
                <div class="validation-check {% if passed %}is-pass{% else %}is-fail{% endif %}">
                    <span>{% if passed %}✓{% else %}×{% endif %}</span><code>{{ key }}</code><b>{% if passed %}PASS{% else %}FAIL{% endif %}</b>
                </div>
                {% endfor %}
            </div>

            <div class="table-wrap validation-case-table-wrap">
                <table class="validation-case-table">
                    <thead><tr><th>کیس</th><th>دسته‌ها</th><th>نتیجه</th><th>جزئیات</th></tr></thead>
                    <tbody>
                    {% for case in report.cases %}
                    <tr data-validation-case="{{ case.case_id }}">
                        <td><b dir="ltr">{{ case.case_id }}</b><small>{{ case.title }}</small></td>
                        <td>{% for category in case.categories %}<span class="validation-tag">{{ category }}</span>{% endfor %}</td>
                        <td><span class="status-pill {% if case.passed %}is-ok{% else %}is-danger{% endif %}">{% if case.passed %}PASS{% else %}FAIL{% endif %}</span></td>
                        <td><details><summary>مشاهده</summary>{% if case.failures %}<ul>{% for failure in case.failures %}<li><code>{{ failure }}</code></li>{% endfor %}</ul>{% else %}<p>Outcome، داده‌های مفقود، suppression و replay مطابق قرارداد بودند.</p>{% endif %}<code dir="ltr">{{ case.result_hash }}</code></details></td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </section>
        {% else %}
        <section class="card empty"><h2>هنوز گزارشی ساخته نشده است</h2><p>اجرای اعتبارسنجی هیچ بیمار واقعی را تغییر نمی‌دهد و فقط artifactهای بستهٔ فعلی را ارزیابی می‌کند.</p></section>
        {% endif %}
    </main>

    <aside class="validation-side">
        {% for role, title, permission in [('CLINICAL','تأیید مسئول بالینی','rule.review.clinical'),('TECHNICAL','تأیید بازبین فنی','rule.review.technical')] %}
        {% set attestation = validation.attestations.get(role) %}
        <section class="card validation-attestation {% if attestation %}is-complete{% endif %}">
            <span class="validation-step">{{ loop.index + 1|fa_num }}</span>
            <h2>{{ title }}</h2>
            {% if attestation %}
                <div class="validation-attested"><b>{{ attestation.reviewer }}</b><small>{{ attestation.created_at|jalali }}</small><p>{{ attestation.note }}</p><code dir="ltr">{{ attestation.content_hash }}</code></div>
            {% elif stored and stored.status == 'PASS' %}
                <form method="post" action="{{ url_for('manager.clinical_validation_action', action='attest') }}" class="engine-stack-form">
                    <input type="hidden" name="role" value="{{ role|lower }}">
                    <input type="hidden" name="report_hash" value="{{ stored.report_hash }}">
                    <label><span>نام بازبین</span><input name="reviewer" required value="{{ g.user.full_name or g.user.username }}"></label>
                    <label><span>یادداشت مستند</span><textarea name="note" required rows="4" minlength="3"></textarea></label>
                    <label class="engine-attestation"><input type="checkbox" name="attestation" value="yes" required><span>گزارش، کیس‌ها و مسئولیت این نقش را بررسی کردم.</span></label>
                    <button class="btn" type="submit">ثبت {{ title }}</button>
                </form>
            {% else %}
                <p class="text-muted">فقط جدیدترین گزارش PASS قابل تأیید است.</p>
            {% endif %}
        </section>
        {% endfor %}

        <section class="card validation-release-summary {% if validation.release_ready %}is-ready{% endif %}">
            <h2>Release evidence</h2>
            {% if validation.release_ready %}
            <p>دو تأیید مستقل و تمام hashها آماده‌اند. اکنون آزمون ۱۰ بیمار و activation report می‌توانند به این evidence متصل شوند.</p>
            <code dir="ltr">{{ validation.release_evidence.validation_report_hash }}</code>
            <a class="btn btn-success" href="{{ url_for('manager.clinical_engine') }}#engine-actions">بازگشت و ادامهٔ راه‌اندازی</a>
            {% else %}
            <p>تا تکمیل همهٔ مراحل، mode مؤثر موتور fail-closed باقی می‌ماند.</p>
            {% endif %}
        </section>
    </aside>
</div>
{% endblock %}
''',
)

append_once(
    "specialist_clinic/src/static/css/app.css",
    "/* Step 7 validation release workspace */",
    r'''/* Step 7 validation release workspace */
.engine-validation-jump{display:flex;align-items:center;justify-content:space-between;gap:var(--s4);margin:0 0 var(--s5);padding:var(--s4) var(--s5);border:1px solid rgba(139,92,246,.35);border-radius:var(--r);background:linear-gradient(135deg,var(--violet-soft),var(--panel));box-shadow:var(--shadow-sm)}
.engine-validation-jump>div{display:flex;flex-direction:column;gap:4px;min-width:0}.engine-validation-jump strong{font-size:15px}.engine-validation-jump small{color:var(--muted);line-height:1.8}
.validation-hero{display:flex;align-items:center;justify-content:space-between;gap:var(--s6);margin-bottom:var(--s5);padding:var(--s6);border:1px solid var(--line-strong);border-inline-start:4px solid var(--warn);border-radius:var(--r-lg);background:linear-gradient(135deg,var(--warn-soft),var(--panel) 50%,var(--bg2))}.validation-hero.is-ready{border-inline-start-color:var(--ok);background:linear-gradient(135deg,var(--ok-soft),var(--panel) 50%,var(--bg2))}.validation-hero.is-blocked{border-inline-start-color:var(--danger);background:linear-gradient(135deg,var(--danger-soft),var(--panel) 50%,var(--bg2))}.validation-hero h1{font-size:clamp(22px,3vw,32px)}.validation-hero p{max-width:760px;margin:var(--s2) 0 0;color:var(--muted);line-height:1.9}.validation-state{display:flex;flex-direction:column;gap:5px;min-width:240px;padding:var(--s4);border:1px solid var(--line);border-radius:var(--r);background:var(--bg-elev)}.validation-state small{color:var(--muted)}.validation-state strong{font-size:16px}.validation-state code{direction:ltr;text-align:left;color:var(--info-fg)}
.validation-layout{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(300px,.75fr);gap:var(--s4);align-items:start}.validation-main,.validation-side{display:flex;flex-direction:column;gap:var(--s4);min-width:0}.validation-main>.card,.validation-side>.card{margin:0}.validation-blockers{border-color:rgba(239,68,68,.3);background:var(--danger-soft)}.validation-blockers h2{font-size:16px}.validation-blockers ul{margin:var(--s3) 0 0;padding-inline-start:22px;color:var(--danger-fg)}
.validation-section-head{display:flex;align-items:center;justify-content:space-between;gap:var(--s4)}.validation-section-head>div{display:flex;align-items:center;gap:var(--s3)}.validation-section-head h2{font-size:17px}.validation-section-head p{margin:4px 0 0;color:var(--muted)}.validation-step{display:grid;place-items:center;width:34px;height:34px;flex:0 0 auto;border-radius:50%;background:var(--violet-soft);color:var(--violet-fg);font-weight:800}
.validation-report-head{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--s4);margin-bottom:var(--s4)}.validation-report-head>div:first-child{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:var(--s2)}.validation-report-head h2{font-size:18px}.validation-report-head p{grid-column:1/-1;margin:0;color:var(--muted)}.validation-hashes{display:flex;flex-direction:column;gap:6px;max-width:55%}.validation-hashes label{display:grid;grid-template-columns:110px minmax(0,1fr);gap:var(--s2);font-size:11px;color:var(--muted)}.validation-hashes code,.validation-attested code,.validation-release-summary code{display:block;direction:ltr;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--info-fg)}
.validation-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:var(--s3);margin-bottom:var(--s4)}.validation-kpis>div{display:flex;flex-direction:column;gap:4px;padding:var(--s3);border:1px solid var(--line);border-radius:var(--r-sm);background:var(--bg2)}.validation-kpis span{color:var(--muted);font-size:11px}.validation-kpis strong{font-size:22px}.validation-check-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--s2);margin-bottom:var(--s4)}.validation-check{display:grid;grid-template-columns:26px minmax(0,1fr) auto;align-items:center;gap:var(--s2);padding:var(--s2) var(--s3);border:1px solid var(--line);border-radius:var(--r-sm);background:var(--bg2)}.validation-check.is-pass{border-color:rgba(34,197,94,.3)}.validation-check.is-pass span,.validation-check.is-pass b{color:var(--ok-fg)}.validation-check.is-fail{border-color:rgba(239,68,68,.3)}.validation-check.is-fail span,.validation-check.is-fail b{color:var(--danger-fg)}
.validation-case-table{min-width:760px}.validation-case-table td:first-child small{display:block;color:var(--muted);max-width:280px}.validation-tag{display:inline-flex;margin:2px;padding:2px 7px;border:1px solid var(--line);border-radius:var(--r-pill);font-size:10px;color:var(--muted)}.validation-case-table details summary{cursor:pointer;color:var(--primary)}.validation-case-table details p{color:var(--muted)}.validation-case-table details code{font-size:10px;overflow-wrap:anywhere}
.validation-attestation{position:relative;padding-top:var(--s5)}.validation-attestation>.validation-step{position:absolute;top:var(--s3);inset-inline-end:var(--s3)}.validation-attestation h2{font-size:16px;margin-bottom:var(--s3)}.validation-attestation.is-complete{border-color:rgba(34,197,94,.3)}.validation-attested{display:flex;flex-direction:column;gap:5px}.validation-attested small,.validation-attested p{color:var(--muted)}.validation-attested p{margin:var(--s2) 0}.validation-release-summary.is-ready{border-color:rgba(34,197,94,.35);background:linear-gradient(180deg,var(--ok-soft),var(--panel))}.validation-release-summary .btn{width:100%;margin-top:var(--s4)}
@media(max-width:1100px){.validation-layout{grid-template-columns:1fr}.validation-side{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.validation-release-summary{grid-column:1/-1}}
@media(max-width:720px){.engine-validation-jump,.validation-hero,.validation-section-head,.validation-report-head{align-items:stretch;flex-direction:column}.engine-validation-jump .btn,.validation-section-head form,.validation-section-head button{width:100%}.validation-state{min-width:0}.validation-kpis,.validation-check-grid,.validation-side{grid-template-columns:1fr}.validation-hashes{max-width:none}.validation-hashes label{grid-template-columns:1fr}.validation-release-summary{grid-column:auto}}
''',
)

write(
    "specialist_clinic/run_step7_review.py",
    r'''"""Start an isolated local review instance for the final Clinical Engine UI."""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5057)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    review_dir = root / "instance" / "step7-review"
    review_dir.mkdir(parents=True, exist_ok=True)
    database = review_dir / "clinic-step7-review.db"
    if args.reset and database.exists():
        database.unlink()

    os.environ["SPECIALIST_DB_PATH"] = str(database)
    os.environ.setdefault("SECRET_KEY", "local-step7-review-only")
    os.environ.setdefault("DEBUG", "1")

    from src.app import create_app

    app = create_app()
    print(f"Step 7 review: http://{args.host}:{args.port}/manager/clinical-engine/validation")
    print("Development login: admin / admin")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
''',
)

write(
    "specialist_clinic/docs/STEP7_LOCAL_REVIEW_FA.md",
    r'''# بررسی لوکال گام ۷

## اجرا

### PowerShell

```powershell
cd specialist_clinic
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py run_step7_review.py --reset
```

### Linux / macOS

```bash
cd specialist_clinic
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_step7_review.py --reset
```

مرورگر را در این مسیر باز کنید:

```text
http://127.0.0.1:5057/manager/clinical-engine/validation
```

ورود توسعه:

```text
admin / admin
```

دیتابیس این runner مستقل است و در `instance/step7-review` قرار می‌گیرد. گزینهٔ
`--reset` فقط همین دیتابیس بررسی را پاک می‌کند.

## ترتیب بررسی

1. اجرای golden cases
2. مشاهدهٔ checkها، metrics و نتیجهٔ تک‌تک caseها
3. ثبت تأیید بالینی
4. ثبت تأیید فنی با کاربر/نام متفاوت
5. بازگشت به صفحهٔ راه‌اندازی و اجرای cohort ده‌بیماری

هیچ‌یک از این مراحل دارو، تشخیص، نسخه یا ارجاع خارجی را خودکار اعمال نمی‌کند.
''',
)

write(
    "specialist_clinic/tests/test_clinical_validation_ui.py",
    r'''from __future__ import annotations

import json

import pytest


@pytest.fixture()
def validation_ui_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "validation-ui.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "validation-ui-test",
    })
    yield app
    core._initialized = False


def manager_client(app):
    client = app.test_client()
    response = client.post(
        "/auth/login", data={"username": "admin", "password": "admin"}
    )
    assert response.status_code in {302, 303}
    return client


def test_validation_workspace_requires_login(validation_ui_app):
    response = validation_ui_app.test_client().get(
        "/manager/clinical-engine/validation"
    )
    assert response.status_code in {302, 303}


def test_validation_workspace_run_and_dual_attestation(validation_ui_app):
    from src.services.clinical_engine.validation_service import ClinicalValidationService

    client = manager_client(validation_ui_app)
    empty = client.get("/manager/clinical-engine/validation")
    html = empty.get_data(as_text=True)
    assert "مرکز اعتبارسنجی و دروازهٔ انتشار" in html
    assert "هنوز گزارشی ساخته نشده است" in html

    ran = client.post(
        "/manager/clinical-engine/validation/run", follow_redirects=True
    )
    html = ran.get_data(as_text=True)
    assert "اعتبارسنجی با وضعیت PASS" in html
    assert "GC-POS-001" in html and "GC-CONFLICT-001" in html
    assert "False positive" in html and "False negative" in html

    with validation_ui_app.app_context():
        report = ClinicalValidationService().dashboard()["report"]
        report_hash = report["report_hash"]

    clinical = client.post(
        "/manager/clinical-engine/validation/attest",
        data={
            "role": "clinical",
            "reviewer": "doctor-a",
            "note": "Clinical outcomes and explanations reviewed.",
            "report_hash": report_hash,
            "attestation": "yes",
        },
        follow_redirects=True,
    )
    assert "تأیید مستقل" in clinical.get_data(as_text=True)

    technical = client.post(
        "/manager/clinical-engine/validation/attest",
        data={
            "role": "technical",
            "reviewer": "engineer-b",
            "note": "Determinism, hashes and failure metrics reviewed.",
            "report_hash": report_hash,
            "attestation": "yes",
        },
        follow_redirects=True,
    )
    html = technical.get_data(as_text=True)
    assert "آمادهٔ اتصال به activation" in html
    with validation_ui_app.app_context():
        assert ClinicalValidationService().current_release_evidence()


def test_newer_blocked_report_invalidates_older_pass(validation_ui_app, tmp_path):
    from src.services.clinical_engine.validation_harness import validation_bundle_path
    from src.services.clinical_engine.validation_service import ClinicalValidationService

    with validation_ui_app.app_context():
        service = ClinicalValidationService()
        passed = service.run_current(created_by="validator")
        service.attest_current(
            role="clinical", reviewer="doctor-a", note="Clinical review.",
            report_hash=passed["report_hash"],
        )
        service.attest_current(
            role="technical", reviewer="engineer-b", note="Technical review.",
            report_hash=passed["report_hash"],
        )
        assert service.current_release_evidence()

        bundle = json.loads(validation_bundle_path().read_text(encoding="utf-8"))
        bundle["cases"][0]["expected"]["outcomes"]["T2-REDFLAG-BP"] = "NOT_FIRED"
        blocked_path = tmp_path / "blocked.json"
        blocked_path.write_text(json.dumps(bundle), encoding="utf-8")
        blocked = service.run_current(created_by="validator", case_path=blocked_path)
        assert blocked["status"] == "BLOCKED"
        assert service.current_release_evidence() is None
''',
)

# Existing end-to-end manager UI must complete the new release gate before comparison.
replace_once(
    "specialist_clinic/tests/test_clinical_engine_v2_manager_ui.py",
    '''    cohort = client.post(
        "/manager/clinical-engine/prepare-demo-cohort", follow_redirects=True,
    )
''',
    '''    validation_run = client.post(
        "/manager/clinical-engine/validation/run", follow_redirects=True,
    )
    assert "اعتبارسنجی با وضعیت PASS" in validation_run.get_data(as_text=True)
    with manager_ui_app.app_context():
        from src.services.clinical_engine.validation_service import ClinicalValidationService
        validation_report = ClinicalValidationService().dashboard()["report"]
    client.post(
        "/manager/clinical-engine/validation/attest",
        data={"role": "clinical", "reviewer": "doctor-a",
              "note": "Clinical validation reviewed.",
              "report_hash": validation_report["report_hash"],
              "attestation": "yes"},
    )
    client.post(
        "/manager/clinical-engine/validation/attest",
        data={"role": "technical", "reviewer": "engineer-b",
              "note": "Technical validation reviewed.",
              "report_hash": validation_report["report_hash"],
              "attestation": "yes"},
    )

    cohort = client.post(
        "/manager/clinical-engine/prepare-demo-cohort", follow_redirects=True,
    )
''',
)

# Preserve package version in release evidence so activation can hash it explicitly.
replace_once(
    "specialist_clinic/src/adapters/sqlite/clinical_validation_repo.py",
    '''            "validation_report_hash": report["report_hash"],
            "package_hash": report["package_hash"],
''',
    '''            "validation_report_hash": report["report_hash"],
            "package_version": report["package_version"],
            "package_hash": report["package_hash"],
''',
)

# Remove the transitional finalizer from the product tree after it has run.
for relative in (
    ".github/finalize_step7.py",
    ".github/workflows/finalize-step7.yml",
):
    target = path(relative)
    if target.exists():
        target.unlink()

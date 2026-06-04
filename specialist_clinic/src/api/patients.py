from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify
from src.api.auth import login_required
from src.services.patient_service import PatientService
from src.adapters.sqlite.patients_repo import PatientRepository
from src.adapters.sqlite.vitals_repo import VitalsRepository, VITAL_TYPES
from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.services.vitals_service import VitalsService, evaluate_reading
from src.services.analytics_service import AnalyticsService, TARGETS
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.services.activity_logger import log_activity
from src.common.utils import jalali_to_gregorian_str

bp = Blueprint("patients", __name__, url_prefix="/patients")


@bp.route("/")
@login_required
def list_patients():
    q = request.args.get("q", "").strip()
    patients = PatientRepository().list_patients(q)
    return render_template("patients/list.html", patients=patients, q=q, active_page='patients')


@bp.route("/enroll", methods=["GET"])
@login_required
def enroll():
    return render_template("patients/enroll.html", active_page='patients')


@bp.route("/api/search-accounting")
@login_required
def search_accounting():
    q = request.args.get("q", "").strip()
    return jsonify({"results": PatientService().search_accounting(q)})


@bp.route("/enroll/accounting", methods=["POST"])
@login_required
def enroll_accounting():
    acc_id = request.form.get("accounting_patient_id", type=int)
    if not acc_id:
        flash("بیمار نامعتبر")
        return redirect(url_for("patients.enroll"))
    pid = PatientService().enroll_from_accounting(acc_id, g.user["username"])
    if not pid:
        flash("ثبت‌نام ناموفق بود")
        return redirect(url_for("patients.enroll"))
    log_activity("patient_enroll", "ثبت‌نام بیمار از سامانه حسابداری", patient_link_id=pid)
    flash("بیمار با موفقیت ثبت‌نام شد", "success")
    return redirect(url_for("patients.detail", pid=pid))


@bp.route("/enroll/manual", methods=["POST"])
@login_required
def enroll_manual():
    full_name = request.form.get("full_name", "").strip()
    national_id = request.form.get("national_id", "").strip() or None
    if not full_name:
        flash("نام و نام خانوادگی الزامی است")
        return redirect(url_for("patients.enroll"))
    pid = PatientService().enroll_manual(
        full_name=full_name, national_id=national_id,
        phone_number=request.form.get("phone_number", "").strip() or None,
        gender=request.form.get("gender") or None,
        birthdate=request.form.get("birthdate", "").strip() or None,
        address=request.form.get("address", "").strip() or None,
        enrolled_by=g.user["username"],
    )
    log_activity("patient_enroll", "ثبت‌نام دستی بیمار", patient_link_id=pid)
    flash("بیمار با موفقیت ثبت‌نام شد", "success")
    return redirect(url_for("patients.detail", pid=pid))


@bp.route("/<int:pid>")
@login_required
def detail(pid):
    service = PatientService()
    profile = service.get_full_profile(pid)
    if not profile:
        flash("بیمار یافت نشد")
        return redirect(url_for("patients.list_patients"))

    vitals_service = VitalsService()
    control = vitals_service.control_status(pid)
    vitals_repo = VitalsRepository()

    # Per-disease indicators (drives quick-entry inputs + value labels)
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
    from src.adapters.sqlite.flags_repo import ClinicalFlagsRepository
    rules_repo = ClinicalRulesRepository()
    flags_repo = ClinicalFlagsRepository()
    condition_codes = [c.get('condition_code') for c in profile['conditions'] if c.get('condition_code')]
    entry_indicators = [i for i in rules_repo.for_conditions(condition_codes) if i.get('is_vital')]
    indicator_labels = {i['key']: i for i in rules_repo.all_indicators(active_only=False)}

    # Clinical decision inputs (flags + drug-class catalog)
    flag_groups = flags_repo.catalog_grouped()
    patient_flags = flags_repo.get_flags(pid)
    drug_class_options = flags_repo.drug_classes()
    drug_class_map = flags_repo.drug_class_map()

    # Trend charts for the key chronic vitals
    chart_types = ['hba1c', 'fbs', 'bp_systolic', 'bp_diastolic']
    charts = {vt: vitals_service.chart_series(pid, vt) for vt in chart_types}

    recent_vitals = vitals_repo.get_readings(pid, limit=30)
    for r in recent_vitals:
        r['level'] = evaluate_reading(r['type'], r['value'])
        meta = indicator_labels.get(r['type']) or VITAL_TYPES.get(r['type'], {})
        r['type_label'] = meta.get('label', r['type'])

    # At-a-glance snapshot: latest reading per tracked indicator
    snapshot = []
    for vtype, reading in (control.get('latest') or {}).items():
        meta = indicator_labels.get(vtype) or VITAL_TYPES.get(vtype, {})
        snapshot.append({
            'label': meta.get('label', vtype),
            'unit': reading['unit'] or meta.get('unit', ''),
            'value': reading['value'],
            'level': evaluate_reading(vtype, reading['value']),
            'order': meta.get('display_order', 100),
        })
    snapshot.sort(key=lambda s: s['order'])

    labs = vitals_repo.get_labs(pid)
    appointments = AppointmentRepository().list_for_patient(pid)
    followups = FollowupRepository().list_for_patient(pid)
    condition_catalog = PatientRepository().list_condition_catalog()

    wallet_repo = WalletRepository()
    wallet_balance = wallet_repo.get_balance(pid)
    wallet_tx = wallet_repo.transactions(pid, limit=20)

    return render_template(
        "patients/detail.html",
        active_page='patients',
        patient=profile['patient'],
        conditions=profile['conditions'],
        medications=profile['medications'],
        allergies=profile['allergies'],
        visit_history=profile['visit_history'],
        control=control,
        charts=charts,
        targets=TARGETS,
        vital_types=VITAL_TYPES,
        recent_vitals=recent_vitals,
        labs=labs,
        appointments=appointments,
        followups=followups,
        condition_catalog=condition_catalog,
        entry_indicators=entry_indicators,
        snapshot=snapshot,
        flag_groups=flag_groups,
        patient_flags=patient_flags,
        drug_class_options=drug_class_options,
        drug_class_map=drug_class_map,
        medication_events=PatientRepository().get_medication_events(pid),
        wallet_balance=wallet_balance,
        wallet_tx=wallet_tx,
    )


@bp.route("/<int:pid>/analytics")
@login_required
def analytics(pid):
    data = AnalyticsService().patient_analytics(pid)
    if not data['patient']:
        flash("بیمار یافت نشد")
        return redirect(url_for("patients.list_patients"))
    # ADA rule-engine clinical support (suggestion-only)
    from src.services.rule_engine import RuleEngine
    from src.adapters.sqlite.flags_repo import ClinicalFlagsRepository
    from src.adapters.sqlite.core import get_db
    data['clinical_support'] = RuleEngine().grouped(pid)
    data['drug_class_map'] = ClinicalFlagsRepository().drug_class_map()
    rows = get_db().execute(
        "SELECT rule_code, status, acted_by FROM suggestion_log WHERE patient_link_id=?", (pid,)).fetchall()
    data['suggestion_status'] = {r['rule_code']: dict(r) for r in rows}
    return render_template("patients/analytics.html", active_page='patients', **data)


@bp.route("/<int:pid>/wallet/adjust", methods=["POST"])
@login_required
def wallet_adjust(pid):
    amount = request.form.get("amount", type=int)
    direction = request.form.get("direction", "credit")
    note = request.form.get("note", "").strip() or None
    if amount and amount > 0:
        signed = amount if direction == "credit" else -amount
        WalletRepository().adjust(pid, signed, reason="manual", note=note, created_by=g.user["username"])
        log_activity("wallet_adjust", f"تنظیم دستی کیف پول ({signed})", patient_link_id=pid)
        flash("کیف پول به‌روزرسانی شد", "success")
    return redirect(url_for("patients.detail", pid=pid) + "#wallet")


# ---- chronic profile mutations ----
@bp.route("/<int:pid>/condition/add", methods=["POST"])
@login_required
def add_condition(pid):
    cid = request.form.get("condition_id", type=int)
    if cid:
        PatientRepository().add_condition(
            pid, cid,
            stage=request.form.get("stage") or None,
            onset_date=jalali_to_gregorian_str(request.form.get("onset_date", "")),
            notes=request.form.get("notes") or None,
        )
        log_activity("condition_add", "افزودن تشخیص بیماری", patient_link_id=pid)
    return redirect(url_for("patients.detail", pid=pid))


@bp.route("/<int:pid>/condition/<int:pc_id>/remove", methods=["POST"])
@login_required
def remove_condition(pid, pc_id):
    PatientRepository().remove_condition(pc_id)
    return redirect(url_for("patients.detail", pid=pid))


@bp.route("/<int:pid>/medication/add", methods=["POST"])
@login_required
def add_medication(pid):
    name = request.form.get("drug_name", "").strip()
    if name:
        PatientRepository().add_medication(
            pid, drug_name=name,
            dose=request.form.get("dose") or None,
            schedule=request.form.get("schedule") or None,
            start_date=jalali_to_gregorian_str(request.form.get("start_date", "")),
            refill_due_date=jalali_to_gregorian_str(request.form.get("refill_due_date", "")),
            notes=request.form.get("notes") or None,
            drug_class=request.form.get("drug_class") or None,
            created_by=g.user["username"],
        )
        log_activity("medication_add", f"افزودن دارو: {name}", patient_link_id=pid)
    return redirect(url_for("patients.detail", pid=pid))


@bp.route("/<int:pid>/medication/<int:med_id>/stop", methods=["POST"])
@login_required
def stop_medication(pid, med_id):
    end_date = jalali_to_gregorian_str(request.form.get("end_date", "")) or None
    PatientRepository().stop_medication(med_id, end_date=end_date, created_by=g.user["username"])
    log_activity("medication_stop", "قطع دارو", patient_link_id=pid)
    return redirect(url_for("patients.detail", pid=pid))


@bp.route("/<int:pid>/medication/<int:med_id>/dose", methods=["POST"])
@login_required
def change_dose(pid, med_id):
    new_dose = request.form.get("dose", "").strip()
    if new_dose:
        PatientRepository().change_dose(
            med_id, new_dose,
            change_date=jalali_to_gregorian_str(request.form.get("change_date", "")) or None,
            note=request.form.get("note") or None,
            created_by=g.user["username"],
        )
        log_activity("medication_dose", f"تغییر دوز دارو به {new_dose}", patient_link_id=pid)
    return redirect(url_for("patients.detail", pid=pid))


@bp.route("/<int:pid>/medication/effect")
@login_required
def medication_effect(pid):
    """On-demand pre/post effect of a medication on a chosen indicator.

    Doctor-driven (no class guessing): returns mean of the indicator before vs
    after the medication's start, with the delta and sample counts.
    """
    med_id = request.args.get("med_id", type=int)
    indicator = request.args.get("indicator", "").strip()
    window = request.args.get("window", default=90, type=int)
    result = AnalyticsService().medication_effect(pid, med_id, indicator, window_days=window)
    return jsonify(result)


@bp.route("/<int:pid>/followups/generate", methods=["POST"])
@login_required
def generate_followups(pid):
    """Generate due ADA monitoring/screening/vaccine follow-ups for this patient."""
    from src.services.followup_engine import generate_for_patient
    n = generate_for_patient(pid)
    log_activity("followup_generate", f"تولید {n} پیگیری ADA", patient_link_id=pid)
    flash(f"{n} پیگیری ADA ساخته شد" if n else "پیگیری جدیدِ سررسیده‌ای نبود", "success")
    return redirect(url_for("patients.analytics", pid=pid))


@bp.route("/<int:pid>/suggestion/action", methods=["POST"])
@login_required
def suggestion_action(pid):
    """Record the physician's decision on an engine suggestion (accept/dismiss)."""
    from src.adapters.sqlite.core import get_db
    from src.common.utils import iran_now
    rule_code = request.form.get("rule_code", "").strip()
    status = request.form.get("status", "").strip()
    if rule_code and status in ("accepted", "dismissed"):
        db = get_db()
        now = iran_now().strftime('%Y-%m-%d %H:%M:%S')
        db.execute(
            """INSERT INTO suggestion_log (patient_link_id, rule_code, suggestion_text, evidence_level, status, acted_by, acted_at, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(patient_link_id, rule_code) DO UPDATE SET
                 status=excluded.status, acted_by=excluded.acted_by, acted_at=excluded.acted_at, note=excluded.note""",
            (pid, rule_code, request.form.get("suggestion_text"), request.form.get("evidence_level"),
             status, g.user["username"], now, request.form.get("note") or None),
        )
        db.commit()
        log_activity("suggestion_action", f"{status} پیشنهاد {rule_code}", patient_link_id=pid)
    return redirect(url_for("patients.analytics", pid=pid))


@bp.route("/<int:pid>/flags", methods=["POST"])
@login_required
def save_flags(pid):
    """Save the patient's clinical decision inputs (ADA flags)."""
    from src.adapters.sqlite.flags_repo import ClinicalFlagsRepository
    repo = ClinicalFlagsRepository()
    values = {}
    for f in repo.catalog():
        key, ftype = f['flag_key'], f['flag_type']
        if ftype == 'bool':
            values[key] = '1' if request.form.get(key) == 'on' else ''
        elif ftype == 'date':
            values[key] = jalali_to_gregorian_str(request.form.get(key, "")) or ''
        else:  # enum / text
            values[key] = request.form.get(key, "").strip()
    repo.set_flags(pid, values, recorded_by=g.user["username"])
    log_activity("flags_update", "ثبت وضعیت بالینی بیمار", patient_link_id=pid)
    flash("وضعیت بالینی ذخیره شد", "success")
    return redirect(url_for("patients.detail", pid=pid) + "#flags")


@bp.route("/<int:pid>/allergy/add", methods=["POST"])
@login_required
def add_allergy(pid):
    sub = request.form.get("substance", "").strip()
    if sub:
        PatientRepository().add_allergy(
            pid, substance=sub,
            reaction=request.form.get("reaction") or None,
            severity=request.form.get("severity") or None,
        )
    return redirect(url_for("patients.detail", pid=pid))


@bp.route("/<int:pid>/allergy/<int:allergy_id>/delete", methods=["POST"])
@login_required
def delete_allergy(pid, allergy_id):
    PatientRepository().delete_allergy(allergy_id)
    return redirect(url_for("patients.detail", pid=pid))


@bp.route("/<int:pid>/contact", methods=["POST"])
@login_required
def update_contact(pid):
    PatientRepository().update_contact(
        pid,
        phone_number=request.form.get("phone_number", "").strip() or None,
        address=request.form.get("address", "").strip() or None,
        notes=request.form.get("notes", "").strip() or None,
    )
    flash("اطلاعات تماس به‌روزرسانی شد", "success")
    return redirect(url_for("patients.detail", pid=pid))

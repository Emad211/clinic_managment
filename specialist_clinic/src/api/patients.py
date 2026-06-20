from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify
from src.api.auth import login_required
from src.services.patient_service import PatientService
from src.adapters.sqlite.patients_repo import PatientRepository
from src.adapters.sqlite.vitals_repo import VitalsRepository, VITAL_TYPES
from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.adapters.sqlite.record_repo import RecordRepository
from src.adapters.sqlite.lab_catalog_repo import LabCatalogRepository
from src.adapters.sqlite.drug_catalog_repo import DrugCatalogRepository
from src.adapters.sqlite.sms_repo import SmsRepository
from src.services.vitals_service import VitalsService, evaluate_reading
from src.services.analytics_service import AnalyticsService, TARGETS
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.services.activity_logger import log_activity
from src.common.utils import jalali_to_gregorian_str, format_jalali_date, today_str, iran_now
from datetime import timedelta

bp = Blueprint("patients", __name__, url_prefix="/patients")


@bp.route("/")
@login_required
def list_patients():
    """Patient list enriched with control status, conditions and latest key vitals;
    quick filters + uncontrolled-first ordering (physician-first)."""
    from src.adapters.sqlite.core import get_db
    q = request.args.get("q", "").strip()
    flt = request.args.get("filter", "").strip()
    db = get_db()

    where = "p.is_active=1"
    params = []
    if q:
        like = f"%{q}%"
        where += " AND (p.full_name LIKE ? OR COALESCE(p.national_id,'') LIKE ? OR COALESCE(p.phone_number,'') LIKE ?)"
        params += [like, like, like]
    rows = db.execute(
        f"""
        SELECT p.id, p.full_name, p.national_id, p.phone_number, p.accounting_patient_id,
          (SELECT v.value FROM vital_readings v WHERE v.patient_link_id=p.id AND v.type='hba1c'       ORDER BY v.measured_at DESC LIMIT 1) AS hba1c,
          (SELECT v.value FROM vital_readings v WHERE v.patient_link_id=p.id AND v.type='bp_systolic' ORDER BY v.measured_at DESC LIMIT 1) AS sys,
          (SELECT v.value FROM vital_readings v WHERE v.patient_link_id=p.id AND v.type='fbs'         ORDER BY v.measured_at DESC LIMIT 1) AS fbs,
          (SELECT MAX(v.measured_at) FROM vital_readings v WHERE v.patient_link_id=p.id) AS last_vital,
          (SELECT GROUP_CONCAT(c.code) FROM patient_conditions pc JOIN conditions c ON c.id=pc.condition_id WHERE pc.patient_link_id=p.id AND pc.is_active=1) AS cond_codes,
          (SELECT GROUP_CONCAT(c.name) FROM patient_conditions pc JOIN conditions c ON c.id=pc.condition_id WHERE pc.patient_link_id=p.id AND pc.is_active=1) AS cond_names
        FROM patient_links p WHERE {where} ORDER BY p.id DESC LIMIT 500
        """, params).fetchall()

    def _lvl(v, warn, high):
        if v is None:
            return -1
        return 2 if v >= high else (1 if v >= warn else 0)

    def control_of(hba1c, sys, fbs):
        levels = [_lvl(hba1c, 7, 8), _lvl(sys, 130, 140), _lvl(fbs, 130, 180)]
        if max(levels) < 0:
            return 'unknown'
        worst = max(levels)
        return {2: 'uncontrolled', 1: 'borderline', 0: 'controlled'}[worst]

    patients = []
    for r in rows:
        d = dict(r)
        d['control'] = control_of(d['hba1c'], d['sys'], d['fbs'])
        d['cond_list'] = [c for c in (d['cond_names'] or '').split(',') if c]
        d['codes'] = set(c for c in (d['cond_codes'] or '').split(',') if c)
        d['last_fa'] = format_jalali_date(d['last_vital']) if d['last_vital'] else None
        patients.append(d)

    counts = {
        'all': len(patients),
        'uncontrolled': sum(1 for p in patients if p['control'] == 'uncontrolled'),
    }

    catalog = PatientRepository().list_condition_catalog()
    known_codes = {c['code'] for c in catalog if c.get('code')}
    if flt == 'uncontrolled':
        patients = [p for p in patients if p['control'] == 'uncontrolled']
    elif flt in known_codes:
        patients = [p for p in patients if flt in p['codes']]

    rank = {'uncontrolled': 0, 'borderline': 1, 'controlled': 2, 'unknown': 3}
    patients.sort(key=lambda p: rank.get(p['control'], 3))

    return render_template(
        "patients/list.html", patients=patients, q=q, active_page='patients',
        counts=counts, active_filter=flt, condition_catalog=catalog,
    )


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

    from src.services.analytics_service import AnalyticsService
    from src.services.rule_engine import RuleEngine
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
    from src.adapters.sqlite.flags_repo import ClinicalFlagsRepository
    from src.adapters.sqlite.core import get_db

    # Clinical analytics powers the cockpit (indicators, per-disease panels, risk, charts, med events)
    adata = AnalyticsService().patient_analytics(pid)
    control = adata['control']

    # ADA decision support (suggestion-only) + physician action log
    clinical_support = RuleEngine().grouped(pid)
    _rows = get_db().execute(
        "SELECT rule_code, status, acted_by FROM suggestion_log WHERE patient_link_id=?", (pid,)).fetchall()
    suggestion_status = {r['rule_code']: dict(r) for r in _rows}

    vitals_repo = VitalsRepository()
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

    # Record-tab data (Phase 2): flags bucketed by record_section + the
    # descriptive record aggregates (surgery/history/notes) + lab catalog.
    record_repo = RecordRepository()
    lab_catalog_repo = LabCatalogRepository()
    flags_by_section = flags_repo.catalog_by_record_section()
    surgeries = record_repo.list_surgeries(pid)
    medical_history = record_repo.list_history(pid)
    notes_symptom = record_repo.list_notes(pid, 'symptom')
    notes_exam = record_repo.list_notes(pid, 'exam')
    notes_lifestyle = record_repo.list_notes(pid, 'lifestyle')
    lab_catalog = lab_catalog_repo.all()
    suggested_labs = lab_catalog_repo.for_conditions(condition_codes)

    # Meds tab (Phase 3): drug catalog for the class->name->doses cascade,
    # the diabetic gate for the insulin calculator, and per-disease dose
    # titration guidance for the non-diabetes conditions the patient has.
    drug_catalog = DrugCatalogRepository().all()
    is_diabetic = 'diabetes' in condition_codes
    condition_name_by_code = {
        c.get('condition_code'): c.get('condition_name')
        for c in profile['conditions'] if c.get('condition_code')
    }
    guidance_codes = [c for c in condition_codes if c != 'diabetes']
    dose_guidance = rules_repo.dosage_guidance(guidance_codes)
    for grp in dose_guidance:
        grp['condition_name'] = condition_name_by_code.get(
            grp['condition_code'], grp['condition_code'])

    wallet_repo = WalletRepository()
    wallet_balance = wallet_repo.get_balance(pid)
    wallet_tx = wallet_repo.transactions(pid, limit=20)

    # Past prescriptions (free / insurance) for the meds tab. The `items`
    # column is a JSON string; expose a simple count for the list (no template
    # JSON parsing needed).
    import json as _json
    prescriptions = record_repo.list_prescriptions(pid)
    for _rx in prescriptions:
        try:
            _parsed = _json.loads(_rx.get('items') or '[]')
            _rx['item_count'] = len(_parsed) if isinstance(_parsed, (list, dict)) else 0
        except (ValueError, TypeError):
            _rx['item_count'] = 0

    return render_template(
        "patients/detail.html",
        active_page='patients',
        patient=profile['patient'],
        conditions=profile['conditions'],
        medications=profile['medications'],
        allergies=profile['allergies'],
        visit_history=profile['visit_history'],
        control=control,
        charts=adata['charts'],
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
        flags_by_section=flags_by_section,
        patient_flags=patient_flags,
        drug_class_options=drug_class_options,
        drug_class_map=drug_class_map,
        surgeries=surgeries,
        medical_history=medical_history,
        notes_symptom=notes_symptom,
        notes_exam=notes_exam,
        notes_lifestyle=notes_lifestyle,
        lab_catalog=lab_catalog,
        suggested_labs=suggested_labs,
        drug_catalog=drug_catalog,
        is_diabetic=is_diabetic,
        dose_guidance=dose_guidance,
        medication_events=PatientRepository().get_medication_events(pid),
        wallet_balance=wallet_balance,
        wallet_tx=wallet_tx,
        indicators=adata['indicators'],
        by_category=adata['by_category'],
        med_events=adata['med_events'],
        risk=adata['risk'],
        per_disease=adata['per_disease'],
        refill_due=adata['refill_due'],
        appt_summary=adata['appointments'],
        visits_count=adata['visits_count'],
        last_visit=adata['last_visit'],
        clinical_support=clinical_support,
        suggestion_status=suggestion_status,
        prescriptions=prescriptions,
    )


@bp.route("/<int:pid>/analytics")
@login_required
def analytics(pid):
    """Merged into the unified patient cockpit; kept as a stable deep-link to the trends tab."""
    return redirect(url_for("patients.detail", pid=pid) + "#trends")


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
    # The frontend sends the chosen-or-typed generic name as a plain string.
    name = request.form.get("drug_name", "").strip()
    if name:
        # Start date is implicit: today (Gregorian). No start-date input.
        start_date = today_str()
        # Refill interval is a preset choice in days ('' = none).
        interval = (request.form.get("refill_interval") or "").strip()
        refill_due_date = None
        if interval in ("15", "30", "60", "90"):
            refill_due_date = (iran_now() + timedelta(days=int(interval))).strftime('%Y-%m-%d')
        PatientRepository().add_medication(
            pid, drug_name=name,
            dose=request.form.get("dose") or None,
            schedule=request.form.get("schedule") or None,
            start_date=start_date,
            refill_due_date=refill_due_date,
            notes=request.form.get("notes") or None,
            drug_class=request.form.get("drug_class") or None,
            created_by=g.user["username"],
        )
        log_activity("medication_add", f"افزودن دارو: {name}", patient_link_id=pid)
    return redirect(url_for("patients.detail", pid=pid) + "#meds")


@bp.route("/<int:pid>/invite", methods=["POST"])
@login_required
def invite_patient(pid):
    """Manually enqueue an SMS invite-to-appointment for physician approval.

    The actual send happens only after a physician approves it in the approval
    queue; enqueue_invite returns None if the patient opted out, has no phone,
    or one was already queued today.
    """
    from src.services.engagement_service import EngagementService
    qid = EngagementService().enqueue_invite(pid)
    flash(
        "دعوت به صفِ تأیید پیام اضافه شد؛ پس از تأییدِ پزشک ارسال می‌شود." if qid
        else "امکان دعوت نبود (انصراف از پیامک، نبودِ موبایل، یا قبلاً امروز اضافه شده).",
        "success" if qid else "",
    )
    log_activity("patient_invite", "دعوت پیامکی به نوبت", patient_link_id=pid)
    return redirect(url_for("patients.detail", pid=pid) + "#meds")


def _card_url(token):
    """Absolute card URL: the manager-set public_base_url if present (clinic LAN IP now,
    public domain later), else the current request host. Shared by the in-clinic QR and
    (later) the internet SMS link."""
    base = (SmsRepository().get_setting("public_base_url", "") or "").strip().rstrip("/")
    return f"{base}/card/{token}" if base else url_for("patient_card.view", token=token, _external=True)


def _qr_svg(url):
    """Inline SVG QR of the card URL — offline, server-side via segno. Degrades to None if
    segno is unavailable so the page still works (URL + copy button)."""
    try:
        import segno
        return segno.make(url, error="m").svg_inline(scale=4, border=2)
    except Exception:
        return None


@bp.route("/<int:pid>/card")
@login_required
def card_admin(pid):
    """Staff page to issue / revoke a patient's public-card link (ADR-0004). The public
    card surface is read-only and feature-flagged; here staff mint and revoke tokens. The
    in-clinic delivery (QR/tablet on the LAN) works today; the SMS/internet path is gated
    on VPS+WireGuard + Kavenegar KYC (see ADR-0004 §4)."""
    profile = PatientService().get_full_profile(pid)
    if not profile:
        flash("بیمار یافت نشد")
        return redirect(url_for("patients.list_patients"))
    from src.adapters.sqlite.patient_card_repo import PatientCardRepository
    active = PatientCardRepository().active_for_patient(pid)
    card_url = _card_url(active["token"]) if active else None
    qr_svg = _qr_svg(card_url) if card_url else None
    enabled = SmsRepository().get_setting("patient_card_enabled", "0") == "1"
    return render_template("patients/card_admin.html", patient=profile["patient"], pid=pid,
                           active=active, card_url=card_url, qr_svg=qr_svg, enabled=enabled)


@bp.route("/<int:pid>/card/issue", methods=["POST"])
@login_required
def card_issue(pid):
    from src.adapters.sqlite.patient_card_repo import PatientCardRepository
    PatientCardRepository().create_token(pid, issued_by=g.user["username"])
    log_activity("card_issue", "صدور لینکِ کارتِ بیمار", patient_link_id=pid)
    flash("لینکِ کارت صادر شد.", "success")
    return redirect(url_for("patients.card_admin", pid=pid))


@bp.route("/<int:pid>/card/revoke/<int:token_id>", methods=["POST"])
@login_required
def card_revoke(pid, token_id):
    from src.adapters.sqlite.patient_card_repo import PatientCardRepository
    PatientCardRepository().revoke(token_id, patient_link_id=pid)
    log_activity("card_revoke", "ابطالِ لینکِ کارتِ بیمار", patient_link_id=pid)
    flash("لینکِ کارت باطل شد.")
    return redirect(url_for("patients.card_admin", pid=pid))


@bp.route("/<int:pid>/prescription/free", methods=["GET", "POST"])
@login_required
def prescription_free(pid):
    """Generate (and on POST log) a printable free, non-insurance prescription.

    Items are the patient's currently-active medications. On POST the script is
    recorded in the prescription log (mode=free); an optional followup_task_id
    closes the originating worklist task. Renders the print-optimized page for
    both GET (preview) and POST.
    """
    profile = PatientService().get_full_profile(pid)
    if not profile:
        flash("بیمار یافت نشد")
        return redirect(url_for("patients.list_patients"))

    items = [
        {'drug_name': m['drug_name'], 'dose': m.get('dose'), 'schedule': m.get('schedule')}
        for m in profile['medications'] if m.get('is_active')
    ]

    if request.method == "POST":
        tid = request.form.get("followup_task_id", type=int)
        RecordRepository().add_prescription(
            pid, kind='free_rx', items=items, mode='free',
            prescriber_user_id=g.user['id'], followup_task_id=tid,
        )
        if tid:
            FollowupRepository().resolve(tid, 'done', call_log='نسخهٔ آزاد صادر شد')
        log_activity("prescription_free", "صدور نسخهٔ آزاد", patient_link_id=pid)

    sms = SmsRepository()
    settings = {
        'clinic_name': sms.get_setting('clinic_name', 'کلینیک تخصصی'),
        'clinic_phone': sms.get_setting('clinic_phone', ''),
        'clinic_address': sms.get_setting('clinic_address', ''),
        'prescriber_name': sms.get_setting('prescriber_name', ''),
        'prescriber_license': sms.get_setting('prescriber_license', ''),
        'rx_disclaimer': sms.get_setting(
            'rx_disclaimer',
            'این نسخه غیربیمه‌ای (آزاد/نقدی) است و توسط سامانهٔ کلینیک صادر شده است.'),
    }
    issued_jalali = format_jalali_date(iran_now().strftime('%Y-%m-%d'))
    return render_template(
        "patients/prescription_print.html",
        patient=profile['patient'], items=items, settings=settings,
        issued_jalali=issued_jalali,
    )


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
    log_activity("followup_generate", f"تولید {n} پیگیری", patient_link_id=pid)
    flash(f"{n} پیگیری ساخته شد" if n else "پیگیری جدیدِ سررسیده‌ای نبود", "success")
    return redirect(url_for("patients.detail", pid=pid) + "#cockpit")


@bp.route("/<int:pid>/suggestion/action", methods=["POST"])
@login_required
def suggestion_action(pid):
    """Record the physician's decision on an engine suggestion (accept/dismiss).

    On accept, if the suggestion carries a drug class (`rx_class`), bounce to
    the meds tab with the class as a query param so the add-med form can
    pre-fill the prescription (Phase 4 dose tool).
    """
    from src.adapters.sqlite.core import get_db
    from src.common.utils import iran_now
    from urllib.parse import quote
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
        rx_class = request.form.get("rx_class", "").strip()
        if status == "accepted" and rx_class:
            return redirect(url_for("patients.detail", pid=pid) + "?rx_class=" + quote(rx_class) + "#meds")
    return redirect(url_for("patients.detail", pid=pid) + "#cockpit")


@bp.route("/<int:pid>/flags", methods=["POST"])
@login_required
def save_flags(pid):
    """Save the patient's clinical decision inputs (ADA flags).

    PARTIAL-SAFE: a per-section record form sends a hidden `flag_keys` field
    (comma-separated keys it manages); only those keys are updated, leaving
    flags from other sections untouched. If `flag_keys` is absent we fall back
    to the legacy whole-catalog behavior (backward compat).
    """
    from src.adapters.sqlite.flags_repo import ClinicalFlagsRepository
    repo = ClinicalFlagsRepository()
    catalog_by_key = {f['flag_key']: f for f in repo.catalog()}

    raw_keys = request.form.get("flag_keys")
    if raw_keys is not None:
        managed = [k.strip() for k in raw_keys.split(",") if k.strip()]
        flags = [catalog_by_key[k] for k in managed if k in catalog_by_key]
    else:
        flags = list(catalog_by_key.values())

    values = {}
    for f in flags:
        key, ftype = f['flag_key'], f['flag_type']
        if ftype == 'bool':
            values[key] = '1' if request.form.get(key) == 'on' else ''
        elif ftype == 'date':
            # The date input re-renders empty (the stored value shows in the placeholder),
            # so a blank submission must NOT wipe a stored date — only update when a new
            # date is actually entered.
            greg = jalali_to_gregorian_str(request.form.get(key, ""))
            if greg:
                values[key] = greg
        else:  # enum / text
            values[key] = request.form.get(key, "").strip()
    repo.set_flags(pid, values, recorded_by=g.user["username"])
    log_activity("flags_update", "ثبت وضعیت بالینی بیمار", patient_link_id=pid)
    flash("وضعیت بالینی ذخیره شد", "success")
    return redirect(url_for("patients.detail", pid=pid) + "#record")


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


# ---- record tab: surgery / medical history / clinical notes ----
@bp.route("/<int:pid>/record/surgery/add", methods=["POST"])
@login_required
def record_surgery_add(pid):
    title = request.form.get("title", "").strip()
    if title:
        RecordRepository().add_surgery(
            pid, title,
            performed_on=jalali_to_gregorian_str(request.form.get("performed_on", "")) or None,
            note=request.form.get("note", "").strip() or None,
        )
        log_activity("surgery_add", f"افزودن سابقهٔ جراحی: {title}", patient_link_id=pid)
    return redirect(url_for("patients.detail", pid=pid) + "#record")


@bp.route("/<int:pid>/record/surgery/<int:sid>/delete", methods=["POST"])
@login_required
def record_surgery_delete(pid, sid):
    RecordRepository().delete_surgery(sid)
    log_activity("surgery_delete", "حذف سابقهٔ جراحی", patient_link_id=pid)
    return redirect(url_for("patients.detail", pid=pid) + "#record")


@bp.route("/<int:pid>/record/history/add", methods=["POST"])
@login_required
def record_history_add(pid):
    title = request.form.get("title", "").strip()
    if title:
        RecordRepository().add_history(
            pid, title,
            note=request.form.get("note", "").strip() or None,
            since=jalali_to_gregorian_str(request.form.get("since", "")) or None,
        )
        log_activity("history_add", f"افزودن سابقهٔ پزشکی: {title}", patient_link_id=pid)
    return redirect(url_for("patients.detail", pid=pid) + "#record")


@bp.route("/<int:pid>/record/history/<int:hid>/delete", methods=["POST"])
@login_required
def record_history_delete(pid, hid):
    RecordRepository().delete_history(hid)
    log_activity("history_delete", "حذف سابقهٔ پزشکی", patient_link_id=pid)
    return redirect(url_for("patients.detail", pid=pid) + "#record")


@bp.route("/<int:pid>/record/note/add", methods=["POST"])
@login_required
def record_note_add(pid):
    kind = request.form.get("kind", "").strip()
    body = request.form.get("body", "").strip()
    if kind in ("symptom", "exam", "lifestyle") and body:
        RecordRepository().add_note(pid, kind, body, recorded_by=g.user["username"])
        log_activity("note_add", f"افزودن یادداشت ({kind})", patient_link_id=pid)
    return redirect(url_for("patients.detail", pid=pid) + "#record")


@bp.route("/<int:pid>/record/note/<int:nid>/delete", methods=["POST"])
@login_required
def record_note_delete(pid, nid):
    RecordRepository().delete_note(nid)
    log_activity("note_delete", "حذف یادداشت", patient_link_id=pid)
    return redirect(url_for("patients.detail", pid=pid) + "#record")


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

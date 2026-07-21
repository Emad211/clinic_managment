from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from src.api.auth import login_required, manager_required
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.sms_repo import SmsRepository
from src.services.auth_service import AuthService
from src.services.protocol_service import ProtocolService
from src.services.activity_logger import log_activity
from src.adapters import accounting_bridge
from src.common.network import get_network_info
from src.config.settings import Config

bp = Blueprint("manager", __name__, url_prefix="/manager")


@bp.route("/")
@manager_required
def index():
    """Single home for configuration; operational metrics live on the dashboard."""
    return render_template("manager/index.html", active_page='manager')


@bp.route("/settings", methods=["GET", "POST"])
@manager_required
def settings():
    repo = SmsRepository()
    if request.method == "POST":
        # Active panel selector (kavenegar | mediana).
        prov = (request.form.get('sms_provider', 'kavenegar') or 'kavenegar').strip().lower()
        repo.set_setting('sms_provider', prov if prov in ('kavenegar', 'mediana') else 'kavenegar')
        # Kavenegar (primary panel).
        repo.set_setting('kavenegar_api_key', request.form.get('kavenegar_api_key', '').strip())
        repo.set_setting('kavenegar_sender', request.form.get('kavenegar_sender', '').strip())
        repo.set_setting('kavenegar_timeout', str(min(max(request.form.get('kavenegar_timeout', type=int) or 45, 10), 120)))
        # Mediana (legacy/fallback panel).
        repo.set_setting('mediana_api_key', request.form.get('mediana_api_key', '').strip())
        repo.set_setting('mediana_sending_number', request.form.get('mediana_sending_number', '').strip())
        repo.set_setting('mediana_message_type', request.form.get('mediana_message_type', 'PromotionalToCustomers').strip())
        repo.set_setting('mediana_timeout', str(min(max(request.form.get('mediana_timeout', type=int) or 45, 10), 120)))
        repo.set_setting('reminder_template', request.form.get('reminder_template', '').strip())
        # Free-prescription header / stamp settings (printed on app-issued non-insurance scripts).
        repo.set_setting('clinic_name', request.form.get('clinic_name', '').strip())
        repo.set_setting('clinic_phone', request.form.get('clinic_phone', '').strip())
        repo.set_setting('clinic_address', request.form.get('clinic_address', '').strip())
        repo.set_setting('prescriber_name', request.form.get('prescriber_name', '').strip())
        repo.set_setting('prescriber_license', request.form.get('prescriber_license', '').strip())
        repo.set_setting('rx_disclaimer', request.form.get('rx_disclaimer', '').strip())
        # Patient public-card Channel (ADR-0004) — off by default; gates the /card/<token> route.
        repo.set_setting('patient_card_enabled', '1' if request.form.get('patient_card_enabled') else '0')
        # Public base URL for card links/QR (clinic LAN IP now, public domain once the
        # internet path lands). Empty -> fall back to the request host. Shared seam for path 2.
        repo.set_setting('public_base_url', request.form.get('public_base_url', '').strip())
        flash("تنظیمات ذخیره شد", "success")
        return redirect(url_for("manager.settings"))
    data = {
        'sms_provider': repo.get_setting('sms_provider', 'kavenegar'),
        'kavenegar_api_key': repo.get_setting('kavenegar_api_key', ''),
        'kavenegar_sender': repo.get_setting('kavenegar_sender', ''),
        'kavenegar_timeout': repo.get_setting('kavenegar_timeout', '45'),
        'mediana_api_key': repo.get_setting('mediana_api_key', ''),
        'mediana_sending_number': repo.get_setting('mediana_sending_number', ''),
        'mediana_message_type': repo.get_setting('mediana_message_type', 'PromotionalToCustomers'),
        'mediana_timeout': repo.get_setting('mediana_timeout', '45'),
        'reminder_template': repo.get_setting('reminder_template',
            'سلام {name} عزیز، یادآوری نوبت شما در کلینیک تخصصی. لطفاً در زمان مقرر مراجعه فرمایید.'),
        # Free-prescription header / stamp.
        'clinic_name': repo.get_setting('clinic_name', 'کلینیک تخصصی'),
        'clinic_phone': repo.get_setting('clinic_phone', ''),
        'clinic_address': repo.get_setting('clinic_address', ''),
        'prescriber_name': repo.get_setting('prescriber_name', ''),
        'prescriber_license': repo.get_setting('prescriber_license', ''),
        'rx_disclaimer': repo.get_setting('rx_disclaimer',
            'این نسخه غیربیمه‌ای (آزاد/نقدی) است و توسط سامانهٔ کلینیک صادر شده است.'),
        'patient_card_enabled': repo.get_setting('patient_card_enabled', '0'),
        'public_base_url': repo.get_setting('public_base_url', ''),
    }
    try:
        request_port = int(request.host.rsplit(':', 1)[1])
    except (IndexError, ValueError):
        request_port = Config.PORT
    network_info = get_network_info(request_port)
    network_info['accounting_bridge_available'] = accounting_bridge.is_available()
    return render_template(
        "manager/settings.html", data=data, network_info=network_info, active_page='manager'
    )


@bp.route("/users", methods=["GET", "POST"])
@manager_required
def users():
    service = AuthService()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "staff")
        full_name = request.form.get("full_name", "").strip() or None
        if not username or not password:
            flash("نام کاربری و رمز عبور الزامی است")
        elif service.register_user(username, password, role, full_name):
            flash("کاربر ساخته شد", "success")
            log_activity("user_create", f"ساخت کاربر {username}")
        else:
            flash("کاربر تکراری است یا خطا رخ داد")
        return redirect(url_for("manager.users"))
    all_users = service.repo.get_all_users()
    return render_template("manager/users.html", users=all_users, active_page='manager')


@bp.route("/users/<int:uid>/token", methods=["POST"])
@manager_required
def user_token(uid):
    """(Re)issue the extension API token for a user — shown once after issuing."""
    token = AuthService().rotate_api_token(uid)
    flash(f'توکنِ اکستنشن صادر شد (یک‌بار نمایش): {token}', 'success')
    log_activity('user_token', f'صدور توکن برای کاربر #{uid}')
    return redirect(url_for('manager.users'))


@bp.route("/protocols")
@manager_required
def protocols():
    summary = ProtocolService().summary()
    return render_template("manager/protocols.html", summary=summary, active_page='manager')


@bp.route("/rules")
@manager_required
def rules():
    """Legacy deep-link; indicator editing now has one home per disease."""
    return redirect(url_for("manager.diseases"))


@bp.route("/rules/update", methods=["POST"])
@manager_required
def rules_update():
    """Update one clinical indicator's editable fields."""
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
    indicator_id = request.form.get("indicator_id", type=int)
    if not indicator_id:
        flash("شناسه نامعتبر")
        return redirect(url_for("manager.diseases"))

    def num(field):
        v = request.form.get(field, "").strip()
        if v == "":
            return None
        try:
            return float(v)
        except ValueError:
            return None

    fields = {
        'label': request.form.get("label", "").strip(),
        'unit': request.form.get("unit", "").strip(),
        'direction': request.form.get("direction", "high"),
        'warn': num("warn"), 'danger': num("danger"), 'target': num("target"),
        'goal_low': num("goal_low"), 'goal_high': num("goal_high"),
        'conditions': request.form.get("conditions", "all").strip() or "all",
        'risk_weight': int(num("risk_weight") or 0),
        'display_order': int(num("display_order") or 100),
        'is_active': 1 if request.form.get("is_active") == "on" else 0,
    }
    ClinicalRulesRepository().update(indicator_id, fields)
    log_activity("rules_update", f"ویرایش قاعده‌ی بالینی #{indicator_id}")
    flash("قاعده به‌روزرسانی شد", "success")
    # Return to wherever the edit came from (per-disease page or the all-indicators page)
    return redirect(request.referrer or url_for("manager.diseases"))


_RULE_CAT_LABELS = {
    'diagnosis': 'تشخیص و طبقه‌بندی', 'target': 'اهداف درمانی', 'medication': 'انتخاب دارو',
    'drug_safety': 'ایمنی و منع دارو', 'insulin': 'انسولین', 'monitoring': 'پایش',
    'screening': 'غربالگری عوارض', 'redflag': 'هشدارهای فوری', 'hypo': 'هیپوگلیسمی',
    'lifestyle': 'سبک زندگی و آموزش', 'vaccination': 'واکسیناسیون',
    'bp_rx': 'درمان فشار خون', 'lipid_rx': 'درمان چربی خون',
}
_RULE_CAT_ORDER = ['redflag', 'diagnosis', 'target', 'medication', 'bp_rx', 'lipid_rx',
                   'insulin', 'drug_safety', 'monitoring', 'screening', 'hypo',
                   'lifestyle', 'vaccination']


@bp.route("/decision-rules")
@manager_required
def decision_rules():
    """Legacy deep-link; decision rules now live on each disease page."""
    return redirect(url_for("manager.diseases"))


@bp.route("/decision-rules/update", methods=["POST"])
@manager_required
def decision_rules_update():
    rule_id = request.form.get("rule_id", type=int)
    if not rule_id:
        flash("شناسه نامعتبر")
        return redirect(url_for("manager.diseases"))
    fields = {
        'recommendation': request.form.get("recommendation", "").strip(),
        'dosage_titration': request.form.get("dosage_titration", "").strip() or None,
        'monitoring': request.form.get("monitoring", "").strip() or None,
        'contraindications': request.form.get("contraindications", "").strip() or None,
        'evidence_level': request.form.get("evidence_level", "").strip() or None,
        'severity': request.form.get("severity", "info"),
        'priority': request.form.get("priority", type=int) or 100,
        'is_active': 1 if request.form.get("is_active") == "on" else 0,
    }
    sets = ', '.join(f"{k}=?" for k in fields)
    get_db().execute(f"UPDATE clinical_rules SET {sets} WHERE id=?",
                     (*fields.values(), rule_id))
    get_db().commit()
    log_activity("decision_rule_update", f"ویرایش قاعدهٔ تصمیم #{rule_id}")
    flash("قاعده به‌روزرسانی شد", "success")
    base = (request.referrer or url_for("manager.diseases")).split('#')[0]
    return redirect(base + f"#rule-{rule_id}")


@bp.route("/diseases")
@manager_required
def diseases():
    """Per-disease module hub — each chronic condition is its own protocol page."""
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
    db = get_db()
    repo = ClinicalRulesRepository()
    active_inds = repo.all_indicators(active_only=True)
    rows = db.execute(
        "SELECT * FROM conditions WHERE is_active=1 AND COALESCE(is_chronic,1)=1 "
        "ORDER BY display_order, id").fetchall()
    modules = []
    for c in rows:
        c = dict(c)
        code = c.get('code')
        c['ind_count'] = sum(1 for i in active_inds if _indicator_applies(i, code))
        c['rule_count'] = db.execute(
            "SELECT COUNT(*) n FROM clinical_rules WHERE condition_code IN (?, 'all')",
            (code,)).fetchone()['n']
        c['pat_count'] = db.execute(
            "SELECT COUNT(DISTINCT pc.patient_link_id) n FROM patient_conditions pc "
            "JOIN patient_links p ON p.id=pc.patient_link_id AND p.is_active=1 "
            "WHERE pc.is_active=1 AND pc.condition_id=?", (c['id'],)).fetchone()['n']
        modules.append(c)
    return render_template("manager/diseases.html", active_page='manager', modules=modules)


def _indicator_applies(ind: dict, code: str) -> bool:
    """True if an indicator's `conditions` field ('all' or a CSV of codes) covers `code`."""
    conds = (ind.get('conditions') or 'all').strip()
    if conds == 'all':
        return True
    return code in [x.strip() for x in conds.split(',') if x.strip()]


@bp.route("/diseases/<code>")
@manager_required
def disease_detail(code):
    """One disease in one page: its indicators/targets + decision rules + monitoring."""
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository, CATEGORY_LABELS
    db = get_db()
    cond = db.execute("SELECT * FROM conditions WHERE code=?", (code,)).fetchone()
    if not cond:
        flash("بیماری یافت نشد")
        return redirect(url_for("manager.diseases"))
    repo = ClinicalRulesRepository()

    # Indicators (active + inactive) that apply to this disease, grouped by category
    inds = [i for i in repo.all_indicators(active_only=False) if _indicator_applies(i, code)]
    ig = {}
    for i in inds:
        ig.setdefault(i['category'], []).append(i)
    ind_groups = [(cc, CATEGORY_LABELS.get(cc, cc), ig[cc])
                  for cc in ['glycemic', 'bp', 'lipid', 'kidney', 'anthro', 'other'] if cc in ig]

    # Decision rules for this module (+ cross-disease 'all'), grouped by category
    rules = [dict(r) for r in db.execute(
        "SELECT * FROM clinical_rules WHERE condition_code IN (?, 'all') ORDER BY priority, id",
        (code,)).fetchall()]
    rg = {}
    for r in rules:
        rg.setdefault(r['category'], []).append(r)
    rule_groups = [(cc, _RULE_CAT_LABELS.get(cc, cc), rg[cc]) for cc in _RULE_CAT_ORDER if cc in rg]
    rule_groups += [(cc, _RULE_CAT_LABELS.get(cc, cc), g) for cc, g in rg.items() if cc not in _RULE_CAT_ORDER]

    # Monitoring schedule (care protocols) for this condition
    protocols = [dict(p) for p in db.execute(
        "SELECT * FROM care_protocols WHERE condition_id=? AND is_active=1 ORDER BY interval_months",
        (cond['id'],)).fetchall()]

    return render_template(
        "manager/disease_detail.html", active_page='manager', cond=dict(cond),
        ind_groups=ind_groups, rule_groups=rule_groups, protocols=protocols,
        rules_active=sum(1 for r in rules if r['is_active']), rules_total=len(rules))


@bp.route("/rules/add", methods=["POST"])
@manager_required
def rules_add():
    """Add a brand-new clinical indicator (manager has a free hand)."""
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository

    def num(field):
        v = request.form.get(field, "").strip()
        try:
            return float(v) if v != "" else None
        except ValueError:
            return None

    key = request.form.get("key", "").strip().lower().replace(" ", "_")
    label = request.form.get("label", "").strip()
    if not key or not label:
        flash("کلید و عنوان الزامی است")
        return redirect(request.referrer or url_for("manager.diseases"))
    ClinicalRulesRepository().create({
        'key': key, 'label': label, 'unit': request.form.get("unit", "").strip(),
        'category': request.form.get("category", "other"),
        'direction': request.form.get("direction", "high"),
        'warn': num("warn"), 'danger': num("danger"), 'target': num("target"),
        'conditions': request.form.get("conditions", "all").strip() or "all",
        'risk_weight': int(num("risk_weight") or 1),
        'display_order': int(num("display_order") or 100),
    })
    log_activity("rules_add", f"افزودن شاخص بالینی: {label}")
    flash("شاخص جدید اضافه شد", "success")
    return redirect(request.referrer or url_for("manager.diseases"))


@bp.route("/protocols/followup", methods=["POST"])
@manager_required
def protocol_followup():
    """Create follow-up tasks for all patients due for a given protocol."""
    from src.adapters.sqlite.followups_repo import FollowupRepository
    protocol_id = request.form.get("protocol_id", type=int)
    summary = ProtocolService().summary()
    target = next((p for p in summary if p['id'] == protocol_id), None)
    if not target:
        flash("پروتکل یافت نشد")
        return redirect(url_for("manager.protocols"))
    repo = FollowupRepository()
    created = 0
    for pat in target['due_patients']:
        if not repo.exists_open(pat['id'], 'visit_due'):
            repo.create(pat['id'], reason='visit_due',
                        detail=f"موعد: {target['name']}")
            created += 1
    flash(f"{created} پیگیری برای «{target['name']}» ساخته شد", "success")
    return redirect(url_for("manager.protocols"))


# ============================== Engagement engine ==============================
@bp.route("/engagement")
@manager_required
def engagement():
    """Live operations view for the event-to-channel automation."""
    import json
    from src.adapters.sqlite.engagement_repo import EngagementRepository, CHANNELS
    repo = EngagementRepository()
    sms = SmsRepository()
    settings = {
        'quiet_start': sms.get_setting('engagement_quiet_start', '08:00'),
        'quiet_end': sms.get_setting('engagement_quiet_end', '21:00'),
        'daily_cap': sms.get_setting('engagement_daily_cap', '1'),
    }
    last_result = {}
    try:
        last_result = json.loads(sms.get_setting('engagement_last_result', '{}') or '{}')
    except (TypeError, ValueError):
        pass
    runtime = {
        'last_run_at': sms.get_setting('engagement_last_run_at'),
        'last_error': sms.get_setting('engagement_last_error'),
        'last_result': last_result,
        'provider_ready': sms.provider_configured(),
    }
    return render_template("manager/engagement.html", active_page='sms',
                           events=repo.all_events(), channels=CHANNELS, settings=settings,
                           summary=repo.operational_summary(), runtime=runtime,
                           hub_pending=repo.count_pending())


@bp.route("/engagement/update", methods=["POST"])
@manager_required
def engagement_update():
    from src.adapters.sqlite.engagement_repo import EngagementRepository
    event_id = request.form.get("event_id", type=int)
    if not event_id:
        flash("شناسه نامعتبر")
        return redirect(url_for("manager.engagement"))
    fields = {
        'channel': request.form.get("channel", "off"),
        'sms_template': request.form.get("sms_template", "").strip() or None,
        'lead_days': request.form.get("lead_days", type=int) or 0,
        'cooldown_days': request.form.get("cooldown_days", type=int) or 0,
        'is_active': 1 if request.form.get("is_active") == "on" else 0,
    }
    EngagementRepository().update_event(event_id, fields)
    log_activity("engagement_update", f"ویرایش رویداد تعامل #{event_id}")
    flash("رویداد به‌روزرسانی شد", "success")
    return redirect(url_for("manager.engagement") + f"#ev-{event_id}")


@bp.route("/engagement/settings", methods=["POST"])
@manager_required
def engagement_settings():
    sms = SmsRepository()
    sms.set_setting('engagement_quiet_start', request.form.get("quiet_start", "08:00").strip() or "08:00")
    sms.set_setting('engagement_quiet_end', request.form.get("quiet_end", "21:00").strip() or "21:00")
    sms.set_setting('engagement_daily_cap', str(request.form.get("daily_cap", type=int) or 1))
    flash("تنظیمات گاردریل ذخیره شد", "success")
    return redirect(url_for("manager.engagement"))

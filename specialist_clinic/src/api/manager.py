from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from src.api.auth import login_required, manager_required
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.sms_repo import SmsRepository
from src.services.auth_service import AuthService
from src.services.activity_logger import log_activity
from src.adapters import accounting_bridge
from src.common.network import get_network_info
from src.config.settings import Config
from src.common.utils import iran_now
from src.services.clinical_engine.activation import (
    ActivationGateError, ClinicalEngineActivationService,
)

bp = Blueprint("manager", __name__, url_prefix="/manager")


@bp.route("/")
@manager_required
def index():
    """Single home for configuration; operational metrics live on the dashboard."""
    return render_template("manager/index.html", active_page='manager')


@bp.route("/clinical-engine")
@manager_required
def clinical_engine():
    projection = ClinicalEngineActivationService().dashboard()
    from src.services.clinical_engine.package_service import ClinicalRulePackageService
    from src.services.clinical_engine.demo_cohort import DemoCohortService
    projection["package"] = ClinicalRulePackageService().projection()
    projection["cohort"] = DemoCohortService().summary()
    requested_step = request.args.get("step", type=int)
    return render_template(
        "manager/clinical_engine.html", engine=projection,
        requested_step=requested_step, active_page="clinical_engine",
    )


@bp.route("/clinical-engine/<action>", methods=["POST"])
@manager_required
def clinical_engine_action(action):
    """One guarded manager seam; the service remains the sole policy owner."""
    service = ClinicalEngineActivationService()
    actor = str(g.user["username"] or "manager")
    reviewer = (request.form.get("reviewer") or g.user["full_name"] or actor).strip()
    note = request.form.get("note", "").strip()
    try:
        if action == "prepare-rules":
            from src.services.clinical_engine.package_service import ClinicalRulePackageService
            package = ClinicalRulePackageService().prepare(actor=actor)
            flash(
                f"بستهٔ اولیه با {len(package['members'])} قاعده آماده شد؛ اکنون متن هر قاعده را بررسی کنید.",
                "success",
            )
        elif action == "approve-rules":
            from src.services.clinical_engine.package_service import ClinicalRulePackageService
            package = ClinicalRulePackageService().approve_and_freeze(
                request.form.get("ruleset_id", type=int),
                reviewer=reviewer,
                attested_codes=request.form.getlist("attested_rule"),
                note=note,
            )
            flash(
                f"هر {len(package['members'])} قاعده تأیید و برای آزمون ایمنی فریز شد.",
                "success",
            )
        elif action == "compare":
            if not service.rules.active_ruleset("general-outpatient"):
                raise ActivationGateError("ابتدا بستهٔ قواعد v2 باید وارد، بازبینی و فریز شود")
            from src.services.clinical_engine.demo_cohort import DemoCohortService
            cohort_service = DemoCohortService()
            cohort = cohort_service.ensure(actor=actor)
            report = service.build_report(
                as_of_at=cohort_service.reference_at(), created_by=actor,
            )
            if report["status"] == "PASS":
                prefix = "پرونده‌های نمونه بازسازی شدند و " if cohort["rebuilt"] else ""
                flash(prefix + "آزمون هر ۱۰ بیمار با موفقیت انجام شد.", "success")
            else:
                flash("گزارش ساخته شد، اما فعال‌سازی همچنان مسدود است. موارد قرمز را بررسی کنید.", "warning")
        elif action == "prepare-demo-cohort":
            from src.services.clinical_engine.demo_cohort import DemoCohortService
            cohort = DemoCohortService().ensure(actor=actor)
            totals = cohort["totals"]
            flash(
                f"۱۰ پروندهٔ طولی آماده شد: {totals['vitals']} مشاهده، "
                f"{totals['labs']} آزمایش و {totals['medication_events']} رویداد دارویی.",
                "success",
            )
        elif action == "approve":
            if request.form.get("attestation") != "yes":
                raise ActivationGateError("تأیید مسئولیت و بازبینی کامل گزارش الزامی است")
            service.approve(
                request.form.get("role", ""), reviewer=reviewer,
                report_hash=request.form.get("report_hash", ""), note=note,
            )
            flash("تأیید به گزارش فعلی متصل و ثبت شد.", "success")
        elif action == "activate-selected":
            service.activate("on_selected", activated_by=actor)
            flash("انتشار محدود موتور v2 فعال شد.", "success")
        elif action == "verify-selected":
            service.verify_selected_rollout(reviewer=reviewer, note=note)
            flash("نتیجهٔ پایش انتشار محدود ثبت شد.", "success")
        elif action == "promote-ruleset":
            service.promote_compared_ruleset(promoted_by=actor)
            flash("مجموعه‌قواعد بررسی‌شده به ACTIVE ارتقا یافت.", "success")
        elif action == "activate-global":
            service.activate("on", activated_by=actor)
            flash("موتور v2 برای همهٔ بیماران فعال شد.", "success")
        elif action == "rollback":
            service.rollback(rolled_back_by=actor, reason=note)
            flash("موتور فوراً خاموش شد؛ تاریخچهٔ ممیزی حفظ شده است.", "success")
        elif action == "reset-workflow":
            if request.form.get("confirm_reset") != "yes":
                raise ActivationGateError("تأیید آگاهانهٔ ریست الزامی است")
            from src.services.clinical_engine.package_service import ClinicalRulePackageService
            ClinicalRulePackageService().reset(actor=actor, reason=note)
            flash(
                "پیشرفت راه‌اندازی ریست شد. موتور خاموش است و تاریخچهٔ ممیزی حذف نشده است.",
                "success",
            )
        else:
            raise ActivationGateError("عملیات ناشناخته است")
    except (ActivationGateError, ValueError, LookupError) as exc:
        flash(f"عملیات انجام نشد: {exc}", "error")
    return redirect(url_for("manager.clinical_engine") + "#engine-actions")


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
    """Retired deep-link for the pre-v2 periodic-care heuristic."""
    flash(
        "پایش‌های بالینی دوره‌ای فقط از بسته‌های govern‌شدهٔ Clinical Engine v2 منتشر می‌شوند.",
        "warning",
    )
    return redirect(url_for("manager.clinical_engine"))


@bp.route("/rules")
@manager_required
def rules():
    """Legacy deep-link; indicator editing now has one home per disease."""
    return redirect(url_for("manager.clinical_engine"))


@bp.route("/rules/update", methods=["POST"])
@manager_required
def rules_update():
    """Update descriptive observation-catalog metadata only."""
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository

    indicator_id = request.form.get("indicator_id", type=int)
    if not indicator_id:
        flash("شناسه نامعتبر")
        return redirect(url_for("manager.diseases"))

    try:
        display_order = int(request.form.get("display_order") or 100)
    except ValueError:
        display_order = 100
    fields = {
        "label": request.form.get("label", "").strip(),
        "unit": request.form.get("unit", "").strip(),
        "category": request.form.get("category", "other").strip() or "other",
        "conditions": request.form.get("conditions", "all").strip() or "all",
        "is_vital": 1 if request.form.get("is_vital") == "on" else 0,
        "display_order": display_order,
        "is_active": 1 if request.form.get("is_active") == "on" else 0,
    }
    ClinicalRulesRepository().update(indicator_id, fields)
    log_activity("indicator_metadata_update", f"ویرایش فراداده شاخص #{indicator_id}")
    flash("فرادادهٔ نمایشی شاخص به‌روزرسانی شد", "success")
    return redirect(request.referrer or url_for("manager.diseases"))



@bp.route("/decision-rules")
@manager_required
def decision_rules():
    """Legacy deep-link; decision rules now live on each disease page."""
    return redirect(url_for("manager.clinical_engine"))


@bp.route("/decision-rules/update", methods=["POST"])
@manager_required
def decision_rules_update():
    flash("ویرایش قواعد موتور قدیمی متوقف شده است؛ قواعد تصمیم فقط از مسیر v2 منتشر می‌شوند.", "warning")
    return redirect(url_for("manager.clinical_engine"))


@bp.route("/diseases")
@manager_required
def diseases():
    """Per-disease descriptive catalog hub; executable logic remains in v2."""
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
    from src.adapters.sqlite.clinical_engine_rules_repo import (
        ClinicalEngineRulesRepository,
    )

    db = get_db()
    repo = ClinicalRulesRepository()
    active_inds = repo.all_indicators(active_only=True)
    rule_counts = ClinicalEngineRulesRepository().condition_rule_counts()
    cross_disease_rules = int(rule_counts.get("all", 0))
    rows = db.execute(
        "SELECT * FROM conditions WHERE is_active=1 AND COALESCE(is_chronic,1)=1 "
        "ORDER BY display_order, id").fetchall()
    modules = []
    for c in rows:
        c = dict(c)
        code = c.get('code')
        c['ind_count'] = sum(1 for i in active_inds if _indicator_applies(i, code))
        c['rule_count'] = (
            int(rule_counts.get(code, 0)) + cross_disease_rules
        )
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
    """One disease page: descriptive measurement catalog and monitoring schedule."""
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

    return render_template(
        "manager/disease_detail.html",
        active_page="manager",
        cond=dict(cond),
        ind_groups=ind_groups,
    )


@bp.route("/rules/add", methods=["POST"])
@manager_required
def rules_add():
    """Add descriptive observation metadata; never a clinical threshold rule."""
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository

    key = request.form.get("key", "").strip().lower().replace(" ", "_")
    label = request.form.get("label", "").strip()
    if not key or not label:
        flash("کلید و عنوان الزامی است")
        return redirect(request.referrer or url_for("manager.diseases"))
    try:
        display_order = int(request.form.get("display_order") or 100)
    except ValueError:
        display_order = 100
    ClinicalRulesRepository().create({
        "key": key,
        "label": label,
        "unit": request.form.get("unit", "").strip(),
        "category": request.form.get("category", "other"),
        "conditions": request.form.get("conditions", "all").strip() or "all",
        "is_vital": 1 if request.form.get("is_vital") == "on" else 0,
        "display_order": display_order,
        "is_active": 1,
    })
    log_activity("indicator_metadata_add", f"افزودن فراداده شاخص: {label}")
    flash("شاخص نمایشی اضافه شد؛ هیچ آستانه یا هدف درمانی ایجاد نشد", "success")
    return redirect(request.referrer or url_for("manager.diseases"))


@bp.route("/protocols/followup", methods=["POST"])
@manager_required
def protocol_followup():
    """Fail closed for the retired pre-v2 care-protocol action."""
    flash(
        "ساخت پیگیری از پروتکل قدیمی متوقف شده است؛ از recommendation audit‌شدهٔ v2 استفاده کنید.",
        "warning",
    )
    return redirect(url_for("manager.clinical_engine"))


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

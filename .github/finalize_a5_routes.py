from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A5 route target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A5 route anchor missing in {relative}: {old[:180]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# SMS hub permissions.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/api/sms.py",
    '''from src.api.auth import login_required
''',
    '''from src.api.auth import login_required
from src.security.permissions import Permission, permission_required
''',
)
route_permissions = {
    '''@bp.route("/")
@login_required
def campaigns():''': '''@bp.route("/")
@permission_required(Permission.SMS_VIEW)
def campaigns():''',
    '''@bp.route("/api/check", methods=["POST"])
@login_required
def api_check():''': '''@bp.route("/api/check", methods=["POST"])
@permission_required(Permission.SMS_CAMPAIGN_CREATE)
def api_check():''',
    '''@bp.route("/api/recipients")
@login_required
def api_recipients():''': '''@bp.route("/api/recipients")
@permission_required(Permission.SMS_CAMPAIGN_CREATE)
def api_recipients():''',
    '''@bp.route("/campaign/new", methods=["POST"])
@login_required
def new_campaign():''': '''@bp.route("/campaign/new", methods=["POST"])
@permission_required(Permission.SMS_CAMPAIGN_CREATE)
def new_campaign():''',
    '''@bp.route("/campaign/<int:cid>")
@login_required
def campaign_detail(cid):''': '''@bp.route("/campaign/<int:cid>")
@permission_required(Permission.SMS_VIEW)
def campaign_detail(cid):''',
    '''@bp.route("/messages")
@login_required
def messages_report():''': '''@bp.route("/messages")
@permission_required(Permission.SMS_VIEW)
def messages_report():''',
    '''@bp.route("/messages/reconcile", methods=["POST"])
@login_required
def reconcile_messages():''': '''@bp.route("/messages/reconcile", methods=["POST"])
@permission_required(Permission.SMS_DELIVERY_RECONCILE)
def reconcile_messages():''',
    '''@bp.route("/campaign/<int:cid>/send", methods=["POST"])
@login_required
def send_campaign(cid):''': '''@bp.route("/campaign/<int:cid>/send", methods=["POST"])
@permission_required(Permission.SMS_CAMPAIGN_SEND)
def send_campaign(cid):''',
    '''@bp.route("/approvals")
@login_required
def approvals():''': '''@bp.route("/approvals")
@permission_required(Permission.SMS_VIEW)
def approvals():''',
    '''@bp.route("/approvals/<int:aid>/approve", methods=["POST"])
@login_required
def approval_approve(aid):''': '''@bp.route("/approvals/<int:aid>/approve", methods=["POST"])
@permission_required(Permission.SMS_APPROVAL_REVIEW)
def approval_approve(aid):''',
    '''@bp.route("/approvals/<int:aid>/reject", methods=["POST"])
@login_required
def approval_reject(aid):''': '''@bp.route("/approvals/<int:aid>/reject", methods=["POST"])
@permission_required(Permission.SMS_APPROVAL_REVIEW)
def approval_reject(aid):''',
    '''@bp.route("/templates/add", methods=["POST"])
@login_required
def add_template():''': '''@bp.route("/templates/add", methods=["POST"])
@permission_required(Permission.SMS_TEMPLATE_MANAGE)
def add_template():''',
}
for old, new in route_permissions.items():
    replace_once("specialist_clinic/src/api/sms.py", old, new)

replace_once(
    "specialist_clinic/src/api/sms.py",
    '''    recipients = resolve_segment(segment) if segment in SEGMENTS else []
''',
    '''    campaign_type = str(data.get("campaign_type") or "info")
    purpose = "CARE" if campaign_type == "reminder" else "MARKETING"
    recipients = (
        resolve_segment(segment, purpose=purpose)
        if segment in SEGMENTS else []
    )
''',
)
# The recipient endpoint is a marketing campaign planning endpoint.
replace_once(
    "specialist_clinic/src/api/sms.py",
    '''    recipients = resolve_segment(segment) if segment in SEGMENTS else []
    return jsonify({"count": len(recipients), "items": recipients[:200]})
''',
    '''    purpose = str(request.args.get("purpose") or "MARKETING").upper()
    if purpose not in {"CARE", "MARKETING"}:
        purpose = "MARKETING"
    recipients = (
        resolve_segment(segment, purpose=purpose)
        if segment in SEGMENTS else []
    )
    return jsonify({"count": len(recipients), "items": recipients[:200]})
''',
)
replace_once(
    "specialist_clinic/src/api/sms.py",
    '''    recipients = resolve_segment(campaign['segment'])
''',
    '''    purpose = "CARE" if campaign.get("campaign_type") == "reminder" else "MARKETING"
    recipients = resolve_segment(campaign['segment'], purpose=purpose)
''',
)
replace_once(
    "specialist_clinic/src/api/sms.py",
    '''        msg = f"ارسال شد — موفق: {result['sent']}"
''',
    '''        msg = f"پنل پذیرفت: {result.get('accepted', result.get('sent', 0))}"
''',
)
replace_once(
    "specialist_clinic/src/api/sms.py",
    '''    flash(f"وضعیت {result['updated']} پیام به‌روزرسانی شد", "success")
''',
    '''    if result["errors"]:
        flash(
            f"{result['updated']} پیام به‌روزرسانی شد؛ "
            f"استعلام {result['errors']} پیام خطا داشت.",
            "warning",
        )
    else:
        flash(f"وضعیت {result['updated']} پیام به‌روزرسانی شد", "success")
''',
)
replace_once(
    "specialist_clinic/src/api/sms.py",
    '''        flash("پیام تأیید و ارسال شد", "success")
''',
    '''        flash("پیام توسط پنل پذیرفته شد؛ تحویل واقعی جداگانه استعلام می‌شود.", "success")
''',
)

# ---------------------------------------------------------------------------
# Manager settings: permission + masked secrets + explicit clear semantics.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/api/manager.py",
    '''from src.security.permissions import Permission, has_permission
''',
    '''from src.security.permissions import Permission, has_permission, permission_required
''',
)
replace_once(
    "specialist_clinic/src/api/manager.py",
    '''@bp.route("/settings", methods=["GET", "POST"])
@manager_required
def settings():
''',
    '''@bp.route("/settings", methods=["GET", "POST"])
@manager_required
@permission_required(Permission.SMS_SETTINGS_MANAGE)
def settings():
''',
)
replace_once(
    "specialist_clinic/src/api/manager.py",
    '''        # Active panel selector (kavenegar | mediana).
''',
    '''        def _update_sms_secret(setting_key: str, form_key: str) -> None:
            clear = request.form.get(f"clear_{form_key}") == "1"
            supplied = str(request.form.get(form_key) or "").strip()
            if clear:
                repo.set_setting(setting_key, "")
            elif supplied:
                repo.set_setting(setting_key, supplied)

        # Active panel selector (kavenegar | mediana).
''',
)
replace_once(
    "specialist_clinic/src/api/manager.py",
    '''        repo.set_setting('kavenegar_api_key', request.form.get('kavenegar_api_key', '').strip())
''',
    '''        _update_sms_secret('kavenegar_api_key', 'kavenegar_api_key')
''',
)
replace_once(
    "specialist_clinic/src/api/manager.py",
    '''        repo.set_setting('mediana_api_key', request.form.get('mediana_api_key', '').strip())
''',
    '''        _update_sms_secret('mediana_api_key', 'mediana_api_key')
''',
)
replace_once(
    "specialist_clinic/src/api/manager.py",
    '''    data = {
        'sms_provider': repo.get_setting('sms_provider', 'kavenegar'),
        'kavenegar_api_key': repo.get_setting('kavenegar_api_key', ''),
''',
    '''    from src.services.sms.secret_resolver import masked_secret
    data = {
        'sms_provider': repo.get_setting('sms_provider', 'kavenegar'),
        'kavenegar_api_key_set': bool(masked_secret('kavenegar')),
        'kavenegar_api_key_masked': masked_secret('kavenegar'),
''',
)
replace_once(
    "specialist_clinic/src/api/manager.py",
    '''        'mediana_api_key': repo.get_setting('mediana_api_key', ''),
''',
    '''        'mediana_api_key_set': bool(masked_secret('mediana')),
        'mediana_api_key_masked': masked_secret('mediana'),
''',
)

# ---------------------------------------------------------------------------
# Patient consent read/write surface.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/api/patients.py",
    '''from src.api.auth import login_required
''',
    '''from src.api.auth import login_required
from src.security.permissions import Permission, permission_required
''',
)
replace_once(
    "specialist_clinic/src/api/patients.py",
    '''    wallet_repo = WalletRepository()
''',
    '''    from src.services.sms.governance_service import SmsGovernanceService
    sms_consent = SmsGovernanceService().summary(pid)

    wallet_repo = WalletRepository()
''',
)
replace_once(
    "specialist_clinic/src/api/patients.py",
    '''        care_timeline=care_timeline,
    )
''',
    '''        care_timeline=care_timeline,
        sms_consent=sms_consent,
    )
''',
)
patients_path = target("specialist_clinic/src/api/patients.py")
patients = patients_path.read_text(encoding="utf-8")
route_marker = '''

@bp.route("/<int:pid>/wallet/adjust", methods=["POST"])
'''
consent_route = '''

@bp.post("/<int:pid>/sms-consent")
@permission_required(Permission.SMS_CONSENT_MANAGE)
def sms_consent_update(pid: int):
    import uuid
    from src.services.sms.governance_service import (
        SmsGovernanceConflict,
        SmsGovernanceService,
        SmsGovernanceValidationError,
    )

    purpose = str(request.form.get("purpose") or "").strip().upper()
    decision = str(request.form.get("decision") or "").strip().upper()
    expected = request.form.get("expected_current_event_id", type=int)
    try:
        event = SmsGovernanceService().record(
            patient_link_id=pid,
            purpose=purpose,
            decision=decision,
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            source_code="CLINIC_STAFF_RECORDED",
            idempotency_key=(
                request.form.get("idempotency_key")
                or f"sms-consent:{pid}:{purpose}:{uuid.uuid4().hex}"
            ),
            reason_code=request.form.get("reason_code") or "PATIENT_REQUEST",
            note=request.form.get("note"),
            expected_current_event_id=expected,
        )
    except (LookupError, SmsGovernanceConflict, SmsGovernanceValidationError) as exc:
        flash(f"تغییر رضایت پیامک ثبت نشد: {exc}", "error")
    else:
        log_activity(
            "sms_consent_record",
            f"purpose={purpose} decision={decision} event={event['id']}",
            patient_link_id=pid,
        )
        flash("وضعیت رضایت پیامک به‌صورت افزایشی ثبت شد.", "success")
    return redirect(url_for("patients.detail", pid=pid) + "#sms-consent")
'''
if consent_route.strip() not in patients:
    if route_marker not in patients:
        raise AssertionError("patient consent route insertion anchor missing")
    patients = patients.replace(route_marker, consent_route + route_marker, 1)
    patients_path.write_text(patients, encoding="utf-8")

Path(__file__).unlink()

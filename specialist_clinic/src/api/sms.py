from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify
from src.api.auth import login_required
from src.security.permissions import Permission, permission_required
from src.adapters.sqlite.sms_repo import SmsRepository
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.services.sms.campaign_service import (
    SEGMENTS, resolve_segment, run_campaign, personalize,
)
from src.services.sms.compliance import find_banned, sanitize
from src.services.sms.provider import get_provider
from src.services.activity_logger import log_activity
from src.common.utils import jalali_to_gregorian_str

bp = Blueprint("sms", __name__, url_prefix="/sms")

CAMPAIGN_TYPES = {
    'info': 'اطلاع‌رسانی / آموزشی',
    'wallet_credit': 'اعتبار کیف پول (پیشنهاد ویژه)',
    'reminder': 'یادآوری',
}


def _group_pending_by_patient(pending: list[dict]) -> list[dict]:
    """Group approval rows for presentation while preserving queue priority."""
    patient_groups = []
    groups_by_patient = {}
    for item in pending:
        patient_id = item['patient_link_id']
        group = groups_by_patient.get(patient_id)
        if group is None:
            group = {
                'patient_link_id': patient_id,
                'patient_name': item['patient_name'],
                'national_id': item.get('national_id'),
                'phone_number': item.get('phone_number'),
                'messages': [],
            }
            groups_by_patient[patient_id] = group
            patient_groups.append(group)
        group['messages'].append(item)
    return patient_groups


def _pending_count() -> int:
    from src.adapters.sqlite.engagement_repo import EngagementRepository
    return EngagementRepository().count_pending()


@bp.route("/")
@permission_required(Permission.SMS_VIEW)
def campaigns():
    repo = SmsRepository()
    campaigns = repo.list_campaigns()
    templates = repo.list_templates()
    seg_sizes = {key: len(resolve_segment(key)) for key in SEGMENTS}
    return render_template("sms/campaigns.html", campaigns=campaigns, templates=templates,
                           segments=SEGMENTS, seg_sizes=seg_sizes, campaign_types=CAMPAIGN_TYPES,
                           provider_ready=repo.provider_configured(),
                           hub_pending=_pending_count(),
                           active_page='sms')


@bp.route("/api/check", methods=["POST"])
@permission_required(Permission.SMS_CAMPAIGN_CREATE)
def api_check():
    """Live compliance check + preview for the campaign composer."""
    data = request.get_json(silent=True) or {}
    body = data.get("body", "")
    segment = data.get("segment", "all")
    credit = int(data.get("credit_amount") or 0)
    banned = find_banned(body)
    campaign_type = str(data.get("campaign_type") or "info")
    purpose = "CARE" if campaign_type == "reminder" else "MARKETING"
    recipients = (
        resolve_segment(segment, purpose=purpose)
        if segment in SEGMENTS else []
    )
    sample_name = recipients[0]['full_name'] if recipients else 'محمد محمدی'
    preview = sanitize(personalize(body, name=sample_name, credit=credit, balance=credit))
    return jsonify({
        "banned": banned,
        "suggested": sanitize(body) if banned else body,
        "preview": preview,
        "recipients": len(recipients),
        "char_count": len(preview),
        "sms_parts": max(1, -(-len(preview) // 70)),  # 70 chars per Persian SMS part
    })


@bp.route("/api/recipients")
@permission_required(Permission.SMS_CAMPAIGN_CREATE)
def api_recipients():
    segment = request.args.get("segment", "all")
    purpose = str(request.args.get("purpose") or "MARKETING").upper()
    if purpose not in {"CARE", "MARKETING"}:
        purpose = "MARKETING"
    recipients = (
        resolve_segment(segment, purpose=purpose)
        if segment in SEGMENTS else []
    )
    return jsonify({"count": len(recipients), "items": recipients[:200]})


@bp.route("/campaign/new", methods=["POST"])
@permission_required(Permission.SMS_CAMPAIGN_CREATE)
def new_campaign():
    repo = SmsRepository()
    name = request.form.get("name", "").strip()
    body = request.form.get("body", "").strip()
    segment = request.form.get("segment")
    campaign_type = request.form.get("campaign_type", "info")
    credit_amount = request.form.get("credit_amount", type=int) or 0
    credit_expires_days = request.form.get("credit_expires_days", type=int) or None
    holdout_percent = min(max(request.form.get("holdout_percent", type=int) or 0, 0), 50)

    if not name or not body or segment not in SEGMENTS:
        flash("نام، متن و گروه هدف الزامی است")
        return redirect(url_for("sms.campaigns"))

    # Auto-sanitize banned words so the panel doesn't reject the message.
    body = sanitize(body)

    sched = jalali_to_gregorian_str(request.form.get("scheduled_date", ""))
    scheduled_at = f"{sched} {request.form.get('scheduled_time','09:00')}:00" if sched else None
    cid = repo.create_campaign(name=name, body=body, segment=segment,
                               campaign_type=campaign_type, credit_amount=credit_amount,
                               credit_expires_days=credit_expires_days,
                               holdout_percent=holdout_percent,
                               scheduled_at=scheduled_at, created_by=g.user["username"])
    log_activity("campaign_create", f"ساخت کمپین: {name}")
    flash("کمپین ساخته شد" + (" و زمان‌بندی شد" if scheduled_at else ""), "success")
    return redirect(url_for("sms.campaign_detail", cid=cid))


@bp.route("/campaign/<int:cid>")
@permission_required(Permission.SMS_VIEW)
def campaign_detail(cid):
    repo = SmsRepository()
    campaign = repo.get_campaign(cid)
    if not campaign:
        flash("کمپین یافت نشد")
        return redirect(url_for("sms.campaigns"))
    messages = repo.list_messages(cid)
    purpose = "CARE" if campaign.get("campaign_type") == "reminder" else "MARKETING"
    recipients = resolve_segment(campaign['segment'], purpose=purpose)
    total_credit = (campaign.get('credit_amount') or 0) * len(recipients) if campaign.get('campaign_type') == 'wallet_credit' else 0
    from src.services.revenue_service import RevenueService
    incrementality = RevenueService().campaign_incrementality(cid)
    from src.services.sms.delivery_service import status_label
    return render_template("sms/campaign_detail.html", campaign=campaign, messages=messages,
                           segments=SEGMENTS, campaign_types=CAMPAIGN_TYPES,
                           recipients_count=len(recipients), total_credit=total_credit,
                           incrementality=incrementality,
                           provider_ready=repo.provider_configured(),
                           hub_pending=_pending_count(),
                           status_label=status_label,
                           active_page='sms')


@bp.route("/messages")
@permission_required(Permission.SMS_VIEW)
def messages_report():
    repo = SmsRepository()
    rows = repo.list_messages_filtered(
        campaign_id=request.args.get('campaign_id', type=int),
        delivery_status=request.args.get('delivery_status') or None,
        provider=request.args.get('provider') or None,
        source_type=request.args.get('source_type') or None)
    from src.services.sms.delivery_service import STATUS_LABELS, status_label, delivery_summary
    return render_template("sms/messages.html", messages=rows, campaigns=repo.list_campaigns(),
                           statuses=STATUS_LABELS, status_label=status_label,
                           summary=delivery_summary(rows), hub_pending=_pending_count(),
                           active_page='sms')


@bp.route("/messages/reconcile", methods=["POST"])
@permission_required(Permission.SMS_DELIVERY_RECONCILE)
def reconcile_messages():
    from src.services.sms.delivery_service import DeliveryService
    result = DeliveryService().reconcile(
        message_ids=[request.form.get('message_id', type=int)] if request.form.get('message_id') else None,
        campaign_id=request.form.get('campaign_id', type=int))
    log_activity("sms_delivery_reconcile", f"استعلام دستی پیامک: {result}")
    if result["errors"]:
        flash(
            f"{result['updated']} پیام به‌روزرسانی شد؛ "
            f"استعلام {result['errors']} پیام خطا داشت.",
            "warning",
        )
    else:
        flash(f"وضعیت {result['updated']} پیام به‌روزرسانی شد", "success")
    return redirect(request.referrer or url_for('sms.messages_report'))


@bp.route("/campaign/<int:cid>/send", methods=["POST"])
@permission_required(Permission.SMS_CAMPAIGN_SEND)
def send_campaign(cid):
    result = run_campaign(cid)
    if 'error' in result:
        flash("پنل پیامک فعال تنظیم نشده است" if result.get('reason') == 'provider_unconfigured'
              else "خطا در ارسال کمپین")
    else:
        msg = f"پنل پذیرفت: {result.get('accepted', result.get('sent', 0))}"
        if result.get('pending'):
            msg += f"، در انتظار تأیید پنل: {result['pending']}"
        flash(msg + f"، ناموفق: {result['failed']} از {result['total']}", "success")
    log_activity("campaign_send", f"ارسال کمپین #{cid}")
    return redirect(url_for("sms.campaign_detail", cid=cid))


@bp.route("/approvals")
@permission_required(Permission.SMS_VIEW)
def approvals():
    from src.adapters.sqlite.engagement_repo import EngagementRepository
    from src.services.engagement_service import EngagementService
    repo = EngagementRepository()
    pending = repo.list_pending()
    for item in pending:
        if item.get('event_key') == 'control_room_invite':
            item['event_label'] = 'دعوت از اتاق کنترل'
    patient_groups = _group_pending_by_patient(pending)
    return render_template("sms/approvals.html", pending=pending,
                           patient_groups=patient_groups, hub_pending=len(pending),
                           quiet_now=EngagementService()._quiet_now(),
                           provider_ready=SmsRepository().provider_configured(),
                           active_page='sms')


@bp.route("/approvals/<int:aid>/approve", methods=["POST"])
@permission_required(Permission.SMS_APPROVAL_REVIEW)
def approval_approve(aid):
    from src.services.engagement_service import EngagementService
    msg = request.form.get("message", "").strip() or None
    override = request.form.get("override") == "1"
    r = EngagementService().approve(aid, g.user["username"], message=msg, override=override)
    if r.get('ok'):
        flash("پیام توسط پنل پذیرفته شد؛ تحویل واقعی جداگانه استعلام می‌شود.", "success")
    elif r.get('reason') == 'quiet':
        flash("خارج از ساعتِ مجازِ ارسال (پیش‌فرض ۸ تا ۲۱)؛ پیام در صف ماند. "
              "برای ارسالِ فوری دکمهٔ «ارسالِ فوری» را بزنید.")
    else:
        flash("ارسال نشد: " + {
            'not_pending': 'قبلاً تعیین‌تکلیف شده',
            'opt_out': 'بیمار انصراف داده یا موبایل ندارد',
            'empty': 'متن خالی است',
            'daily_cap': 'سقف پیامک روزانه این بیمار تکمیل شده؛ پیام در صف ماند',
            'provider_unconfigured': 'پنل پیامک فعال تنظیم نشده است',
            'retryable_failure': r.get('error') or 'خطای موقت پنل؛ پیام در صف ماند',
            'provider_rejected': r.get('error') or 'پیام توسط پنل رد شد',
            'submission_unknown': 'نتیجه ارسال نامشخص است؛ برای جلوگیری از تکرار دوباره ارسال نشد',
            'provider_error': r.get('error') or 'خطا در ارتباط با پنل',
        }.get(r.get('reason'), r.get('error') or 'خطا'))
    log_activity("approval_approve", f"تأیید پیام #{aid}")
    return redirect(url_for("sms.approvals"))


@bp.route("/approvals/<int:aid>/reject", methods=["POST"])
@permission_required(Permission.SMS_APPROVAL_REVIEW)
def approval_reject(aid):
    from src.services.engagement_service import EngagementService
    EngagementService().reject(aid, g.user["username"])
    flash("پیام رد شد", "success")
    log_activity("approval_reject", f"رد پیام #{aid}")
    return redirect(url_for("sms.approvals"))


@bp.route("/templates/add", methods=["POST"])
@permission_required(Permission.SMS_TEMPLATE_MANAGE)
def add_template():
    name = request.form.get("name", "").strip()
    body = request.form.get("body", "").strip()
    if name and body:
        SmsRepository().add_template(sanitize(name), sanitize(body))
        flash("قالب ذخیره شد", "success")
    return redirect(url_for("sms.campaigns"))

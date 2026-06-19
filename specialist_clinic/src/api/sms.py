from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify
from src.api.auth import login_required
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


@bp.route("/")
@login_required
def campaigns():
    repo = SmsRepository()
    campaigns = repo.list_campaigns()
    templates = repo.list_templates()
    seg_sizes = {key: len(resolve_segment(key)) for key in SEGMENTS}
    return render_template("sms/campaigns.html", campaigns=campaigns, templates=templates,
                           segments=SEGMENTS, seg_sizes=seg_sizes, campaign_types=CAMPAIGN_TYPES,
                           provider_ready=repo.provider_configured(),
                           active_page='sms')


@bp.route("/api/check", methods=["POST"])
@login_required
def api_check():
    """Live compliance check + preview for the campaign composer."""
    data = request.get_json(silent=True) or {}
    body = data.get("body", "")
    segment = data.get("segment", "all")
    credit = int(data.get("credit_amount") or 0)
    banned = find_banned(body)
    recipients = resolve_segment(segment) if segment in SEGMENTS else []
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
@login_required
def api_recipients():
    segment = request.args.get("segment", "all")
    recipients = resolve_segment(segment) if segment in SEGMENTS else []
    return jsonify({"count": len(recipients), "items": recipients[:200]})


@bp.route("/campaign/new", methods=["POST"])
@login_required
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
@login_required
def campaign_detail(cid):
    repo = SmsRepository()
    campaign = repo.get_campaign(cid)
    if not campaign:
        flash("کمپین یافت نشد")
        return redirect(url_for("sms.campaigns"))
    messages = repo.list_messages(cid)
    recipients = resolve_segment(campaign['segment'])
    total_credit = (campaign.get('credit_amount') or 0) * len(recipients) if campaign.get('campaign_type') == 'wallet_credit' else 0
    from src.services.revenue_service import RevenueService
    incrementality = RevenueService().campaign_incrementality(cid)
    return render_template("sms/campaign_detail.html", campaign=campaign, messages=messages,
                           segments=SEGMENTS, campaign_types=CAMPAIGN_TYPES,
                           recipients_count=len(recipients), total_credit=total_credit,
                           incrementality=incrementality,
                           provider_ready=repo.provider_configured(),
                           active_page='sms')


@bp.route("/campaign/<int:cid>/send", methods=["POST"])
@login_required
def send_campaign(cid):
    result = run_campaign(cid)
    if 'error' in result:
        flash("خطا در ارسال کمپین")
    else:
        msg = f"ارسال شد — موفق: {result['sent']}"
        if result.get('pending'):
            msg += f"، در انتظار تأیید پنل: {result['pending']}"
        flash(msg + f"، ناموفق: {result['failed']} از {result['total']}", "success")
    log_activity("campaign_send", f"ارسال کمپین #{cid}")
    return redirect(url_for("sms.campaign_detail", cid=cid))


@bp.route("/approvals")
@login_required
def approvals():
    from src.adapters.sqlite.engagement_repo import EngagementRepository
    repo = EngagementRepository()
    pending = repo.list_pending()
    return render_template("sms/approvals.html", pending=pending, hub_pending=len(pending),
                           provider_ready=SmsRepository().provider_configured(),
                           active_page='sms')


@bp.route("/approvals/<int:aid>/approve", methods=["POST"])
@login_required
def approval_approve(aid):
    from src.services.engagement_service import EngagementService
    msg = request.form.get("message", "").strip() or None
    r = EngagementService().approve(aid, g.user["username"], message=msg)
    if r.get('ok'):
        flash("پیام تأیید و ارسال شد", "success")
    else:
        flash("ارسال نشد: " + {
            'not_pending': 'قبلاً تعیین‌تکلیف شده',
            'opt_out': 'بیمار انصراف داده یا موبایل ندارد',
            'empty': 'متن خالی است',
        }.get(r.get('reason'), 'خطا'))
    log_activity("approval_approve", f"تأیید پیام #{aid}")
    return redirect(url_for("sms.approvals"))


@bp.route("/approvals/<int:aid>/reject", methods=["POST"])
@login_required
def approval_reject(aid):
    from src.services.engagement_service import EngagementService
    EngagementService().reject(aid, g.user["username"])
    flash("پیام رد شد", "success")
    log_activity("approval_reject", f"رد پیام #{aid}")
    return redirect(url_for("sms.approvals"))


@bp.route("/templates/add", methods=["POST"])
@login_required
def add_template():
    name = request.form.get("name", "").strip()
    body = request.form.get("body", "").strip()
    if name and body:
        SmsRepository().add_template(sanitize(name), sanitize(body))
        flash("قالب ذخیره شد", "success")
    return redirect(url_for("sms.campaigns"))

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A6 route target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A6 route anchor missing in {relative}: {old[:220]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Campaign creation, projection, patient responses and attribution correction.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/api/sms.py",
    '''    cid = repo.create_campaign(name=name, body=body, segment=segment,
                               campaign_type=campaign_type, credit_amount=credit_amount,
                               credit_expires_days=credit_expires_days,
                               holdout_percent=holdout_percent,
                               scheduled_at=scheduled_at, created_by=g.user["username"])
''',
    '''    from src.services.campaign_management_service import (
        CampaignManagementService,
    )
    cid = CampaignManagementService().create(
        name=name,
        body=body,
        segment=segment,
        campaign_type=campaign_type,
        credit_amount=credit_amount,
        credit_expires_days=credit_expires_days,
        holdout_percent=holdout_percent,
        scheduled_at=scheduled_at,
        created_by=g.user["username"],
    )
''',
)
replace_once(
    "specialist_clinic/src/api/sms.py",
    '''    messages = repo.list_messages(cid)
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
''',
    '''    from src.adapters.sqlite.campaign_economics_repo import (
        CampaignEconomicsRepository,
    )
    from src.services.campaign_economics_service import (
        CampaignEconomicsService,
    )
    economics_repo = CampaignEconomicsRepository()
    economics = CampaignEconomicsService(repository=economics_repo)
    projection = economics.projection(cid)
    messages = economics_repo.campaign_messages(cid)
    audience_members = economics_repo.audience_members(cid)
    purpose = economics.purpose_for_campaign(campaign)
    dynamic_recipients = (
        resolve_segment(campaign['segment'], purpose=purpose)
        if not projection["audience"]["frozen"] else []
    )
    recipients_count = (
        int(projection["audience"]["eligible_count"])
        if projection["audience"]["frozen"] else len(dynamic_recipients)
    )
    treated_count = (
        int(projection["audience"]["treated_count"])
        if projection["audience"]["frozen"] else recipients_count
    )
    total_credit = (
        int(campaign.get('credit_amount') or 0) * treated_count
        if campaign.get('campaign_type') == 'wallet_credit' else 0
    )
    from src.services.sms.delivery_service import status_label
    return render_template(
        "sms/campaign_detail.html",
        campaign=campaign,
        messages=messages,
        audience_members=audience_members,
        economics=projection,
        segments=SEGMENTS,
        campaign_types=CAMPAIGN_TYPES,
        recipients_count=recipients_count,
        total_credit=total_credit,
        incrementality=None,
        provider_ready=repo.provider_configured(),
        hub_pending=_pending_count(),
        status_label=status_label,
        active_page='sms',
    )
''',
)

sms_path = target("specialist_clinic/src/api/sms.py")
sms = sms_path.read_text(encoding="utf-8")
anchor = '''

@bp.route("/messages")
'''
routes = '''

@bp.post("/campaign/<int:cid>/response")
@permission_required(Permission.SMS_CAMPAIGN_RESPONSE_RECORD)
def campaign_response(cid: int):
    import uuid
    from src.adapters.sqlite.campaign_economics_repo import (
        CampaignEconomicsConflict,
        CampaignEconomicsValidationError,
    )
    from src.services.campaign_economics_service import CampaignEconomicsService

    patient_id = request.form.get("patient_link_id", type=int)
    if not patient_id:
        flash("بیمار پاسخ‌دهنده مشخص نیست.", "error")
        return redirect(url_for("sms.campaign_detail", cid=cid))
    try:
        event = CampaignEconomicsService().record_response(
            campaign_id=cid,
            patient_link_id=patient_id,
            response_type=request.form.get("response_type") or "",
            evidence_type=request.form.get("evidence_type") or "",
            actor_username=g.user["username"],
            idempotency_key=(
                request.form.get("idempotency_key")
                or f"campaign-response:{cid}:{patient_id}:{uuid.uuid4().hex}"
            ),
            message_id=request.form.get("message_id", type=int),
            evidence_ref=request.form.get("evidence_ref"),
            note=request.form.get("note"),
            expected_current_event_id=request.form.get(
                "expected_current_event_id", type=int
            ),
        )
    except (LookupError, CampaignEconomicsConflict,
            CampaignEconomicsValidationError, ValueError) as exc:
        flash(f"پاسخ کمپین ثبت نشد: {exc}", "error")
    else:
        log_activity(
            "campaign_response_record",
            f"campaign={cid} patient={patient_id} response={event['response_type']}",
            patient_link_id=patient_id,
        )
        flash("پاسخ بیمار به‌صورت افزایشی ثبت شد.", "success")
    return redirect(url_for("sms.campaign_detail", cid=cid) + "#campaign-responses")


@bp.post("/campaign/<int:cid>/cancel")
@permission_required(Permission.SMS_CAMPAIGN_SEND)
def cancel_campaign(cid: int):
    from src.adapters.sqlite.campaign_economics_repo import (
        CampaignEconomicsConflict,
        CampaignEconomicsValidationError,
    )
    from src.services.campaign_management_service import CampaignManagementService

    try:
        CampaignManagementService().cancel(
            cid,
            actor_username=g.user["username"],
            note=request.form.get("note") or "Campaign cancelled by operator.",
            expected_current_event_id=request.form.get(
                "expected_current_event_id", type=int
            ),
        )
    except (LookupError, CampaignEconomicsConflict,
            CampaignEconomicsValidationError, ValueError) as exc:
        flash(f"کمپین لغو نشد: {exc}", "error")
    else:
        log_activity("campaign_cancel", f"لغو کمپین #{cid}")
        flash("کمپین به‌صورت ممیزی‌شده لغو شد.", "success")
    return redirect(url_for("sms.campaign_detail", cid=cid))


@bp.post("/campaign/<int:cid>/attribution/<path:journey_id>/revoke")
@permission_required(Permission.SMS_CAMPAIGN_ATTRIBUTION_CORRECT)
def revoke_campaign_attribution(cid: int, journey_id: str):
    import uuid
    from src.adapters.sqlite.campaign_economics_repo import (
        CampaignEconomicsConflict,
        CampaignEconomicsRepository,
        CampaignEconomicsValidationError,
    )

    try:
        CampaignEconomicsRepository().revoke_journey_attribution(
            journey_id=journey_id,
            actor_username=g.user["username"],
            idempotency_key=(
                request.form.get("idempotency_key")
                or f"campaign-attribution-revoke:{journey_id}:{uuid.uuid4().hex}"
            ),
            note=request.form.get("note") or "",
            expected_current_event_id=request.form.get(
                "expected_current_event_id", type=int
            ),
        )
    except (LookupError, CampaignEconomicsConflict,
            CampaignEconomicsValidationError, ValueError) as exc:
        flash(f"اصلاح attribution انجام نشد: {exc}", "error")
    else:
        log_activity("campaign_attribution_revoke", f"journey={journey_id}")
        flash("انتساب Journey لغو شد؛ تاریخچه حفظ شد.", "success")
    return redirect(url_for("sms.campaign_detail", cid=cid) + "#campaign-economics")
'''
if routes.strip() not in sms:
    if anchor not in sms:
        raise AssertionError("A6 SMS route insertion anchor missing")
    sms = sms.replace(anchor, routes + anchor, 1)
    sms_path.write_text(sms, encoding="utf-8")

# ---------------------------------------------------------------------------
# Doctor queue: optional explicit positive-response linkage in the attendance transaction.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/services/doctor_queue_service.py",
    '''        appointments = AppointmentRepository()
        funnel = SpecialistFinancialFunnelRepository()
''',
    '''        appointments = AppointmentRepository()
        funnel = SpecialistFinancialFunnelRepository()
        from src.services.campaign_economics_service import CampaignEconomicsService
        campaign_economics = CampaignEconomicsService()
''',
)
replace_once(
    "specialist_clinic/src/services/doctor_queue_service.py",
    '''                "linked_appointment_id": (
                    int(link["appointment_id"]) if link else None
                ),
            }
''',
    '''                "linked_appointment_id": (
                    int(link["appointment_id"]) if link else None
                ),
                "campaign_response_options": (
                    campaign_economics.positive_response_options(patient_link_id)
                    if patient_link_id else []
                ),
            }
''',
)
replace_once(
    "specialist_clinic/src/services/doctor_queue_service.py",
    '''        actor_username: str | None = None,
        appointment_id: int | None = None,
    ) -> dict:
''',
    '''        actor_username: str | None = None,
        appointment_id: int | None = None,
        campaign_response_event_id: int | None = None,
    ) -> dict:
''',
)
replace_once(
    "specialist_clinic/src/services/doctor_queue_service.py",
    '''            DoctorQueueRepository(db).start(
                **self._repo_snapshot(canonical), commit=False
            )
            db.commit()
''',
    '''            if campaign_response_event_id is not None:
                from src.services.campaign_economics_service import (
                    CampaignEconomicsService,
                )
                CampaignEconomicsService(db=db).attribute_response_to_journey(
                    response_event_id=int(campaign_response_event_id),
                    journey_id=encounter["journey_id"],
                    actor_username=actor,
                    idempotency_key=(
                        f"doctor-queue-campaign-attribution:"
                        f"{encounter['journey_id']}:"
                        f"{int(campaign_response_event_id)}"
                    ),
                    commit=False,
                )
            DoctorQueueRepository(db).start(
                **self._repo_snapshot(canonical), commit=False
            )
            db.commit()
''',
)
replace_once(
    "specialist_clinic/src/services/doctor_queue_service.py",
    '''            canonical["appointment_id"] = appointment_id
            return canonical
''',
    '''            canonical["appointment_id"] = appointment_id
            canonical["campaign_response_event_id"] = campaign_response_event_id
            return canonical
''',
)

replace_once(
    "specialist_clinic/src/api/doctor_queue.py",
    '''from src.api.auth import login_required
''',
    '''from src.api.auth import login_required
from src.security.permissions import Permission, has_permission
''',
)
replace_once(
    "specialist_clinic/src/api/doctor_queue.py",
    '''        "APPOINTMENT_ALREADY_LINKED_TO_ANOTHER_ENCOUNTER": "این نوبت قبلاً به Encounter دیگری متصل شده است.",
''',
    '''        "APPOINTMENT_ALREADY_LINKED_TO_ANOTHER_ENCOUNTER": "این نوبت قبلاً به Encounter دیگری متصل شده است.",
        "journey attribution requires a positive response event": "پاسخ انتخاب‌شده مثبت و معتبر نیست.",
        "journey attribution requires the latest campaign response": "پاسخ انتخاب‌شده آخرین پاسخ بیمار نیست.",
        "campaign journey patient mismatch": "پاسخ کمپین متعلق به این بیمار نیست.",
        "campaign response is already attributed to another journey": "این پاسخ قبلاً به Journey دیگری متصل شده است.",
''',
)
replace_once(
    "specialist_clinic/src/api/doctor_queue.py",
    '''    try:
        visit = DoctorQueueService().start(
            _snapshot(invoice_id),
            actor_username=g.user["username"],
            appointment_id=request.form.get("appointment_id", type=int),
        )
''',
    '''    try:
        response_event_id = request.form.get(
            "campaign_response_event_id", type=int
        )
        if response_event_id and not has_permission(
            Permission.SMS_CAMPAIGN_ATTRIBUTION_RECORD
        ):
            raise DoctorQueueIdentityError(
                "مجوز ثبت انتساب کمپین برای این کاربر وجود ندارد."
            )
        visit = DoctorQueueService().start(
            _snapshot(invoice_id),
            actor_username=g.user["username"],
            appointment_id=request.form.get("appointment_id", type=int),
            campaign_response_event_id=response_event_id,
        )
''',
)
replace_once(
    "specialist_clinic/src/api/doctor_queue.py",
    '''        log_activity(
            "visit_start",
            f"شروع ویزیت فاکتور #{invoice_id}{appointment_text}",
            patient_link_id=visit.get("patient_link_id"),
        )
''',
    '''        response_text = (
            f" campaign_response={visit['campaign_response_event_id']}"
            if visit.get("campaign_response_event_id") else ""
        )
        log_activity(
            "visit_start",
            f"شروع ویزیت فاکتور #{invoice_id}{appointment_text}{response_text}",
            patient_link_id=visit.get("patient_link_id"),
        )
''',
)

Path(__file__).unlink()

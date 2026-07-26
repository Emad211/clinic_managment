from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "specialist_clinic/src/api/followups.py"
TEMPLATE = ROOT / "specialist_clinic/src/templates/followups/worklist.html"

text = API.read_text(encoding="utf-8")
if "from src.services.followup_booking_service import" not in text:
    anchor = "from src.services.followup_service import FollowupService, REASON_LABELS\n"
    replacement = anchor + "from src.services.followup_booking_service import (\n    FollowupBookingError,\n    FollowupBookingService,\n)\n"
    if anchor not in text:
        raise AssertionError("followup booking import anchor missing")
    text = text.replace(anchor, replacement, 1)

start_marker = '@bp.route("/patient/<int:pid>/to-visit", methods=["POST"])\n'
end_marker = '\n\n@bp.route("/add", methods=["POST"])\n'
start = text.find(start_marker)
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise AssertionError("followup booking route boundaries missing")
route = '''@bp.route("/patient/<int:pid>/to-visit", methods=["POST"])
@login_required
def patient_to_visit(pid):
    """Atomically record BOOKED without falsely completing any follow-up."""
    scheduled_date = jalali_to_gregorian_str(
        request.form.get("scheduled_date", "")
    )
    if not scheduled_date:
        flash("تاریخ ویزیت الزامی است", "error")
        return redirect(request.referrer or url_for("followups.worklist"))
    scheduled_time = (request.form.get("scheduled_time") or "09:00").strip()
    scheduled_at = f"{scheduled_date} {scheduled_time}:00"
    task_ids = sorted(
        {int(value) for value in request.form.getlist("task_ids") if str(value).isdigit()}
    )
    if not task_ids:
        flash("پیگیری بازی برای این بیمار انتخاب نشده است", "error")
        return redirect(request.referrer or url_for("followups.worklist"))

    marks = ",".join("?" for _ in task_ids)
    rows = get_db().execute(
        f"SELECT id, source_engine FROM followup_tasks WHERE id IN ({marks})",
        task_ids,
    ).fetchall()
    if len(rows) != len(task_ids):
        flash("یکی از پیگیری‌ها دیگر وجود ندارد.", "error")
        return redirect(request.referrer or url_for("followups.worklist"))
    if any(row["source_engine"] == "clinical_v2" for row in rows) and not has_permission(
        Permission.CLINICAL_TASK_TRANSITION
    ):
        flash("مجوز زمان‌بندی پیگیری بالینی ثبت نشده است.", "error")
        return redirect(request.referrer or url_for("followups.worklist"))

    try:
        result = FollowupBookingService().book(
            patient_link_id=pid,
            task_ids=task_ids,
            scheduled_at=scheduled_at,
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            idempotency_key=request.form.get("booking_idempotency_key") or "",
        )
    except (FollowupBookingError, ValueError, LookupError, sqlite3.IntegrityError) as exc:
        flash(f"رزرو نوبت انجام نشد: {exc}", "error")
    else:
        log_activity(
            "followup_to_visit",
            (
                f"appointment={result['appointment_id']} "
                f"admin_booked={result['admin_booked']} "
                f"clinical_scheduled={result['clinical_scheduled']} "
                f"duplicate={result['duplicate']} patient={pid}"
            ),
            patient_link_id=pid,
        )
        flash(
            (
                f"نوبت #{result['appointment_id']} ثبت شد؛ "
                "پیگیری‌ها تا حضور یا ثبت نتیجه باز می‌مانند."
            ),
            "success",
        )
    return redirect(url_for("followups.worklist"))
'''
text = text[:start] + route + text[end:]
API.write_text(text, encoding="utf-8")

template = TEMPLATE.read_text(encoding="utf-8")
anchor = '''            <form method="post" action="{{ url_for('followups.patient_to_visit', pid=pg.patient_link_id) }}" class="card card-soft" style="margin-top:var(--s3);">
'''
replacement = anchor + '''                <input type="hidden" name="booking_idempotency_key" value="booking:{{ pg.tasks[0].contact_form_token }}">
'''
if replacement not in template:
    if anchor not in template:
        raise AssertionError("booking form anchor missing")
    template = template.replace(anchor, replacement, 1)
TEMPLATE.write_text(template, encoding="utf-8")

Path(__file__).unlink()

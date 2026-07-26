from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A1 patch anchor missing in {relative}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Bootstrap, readiness and tamper scope.
patch(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    from src.adapters.sqlite.specialist_revenue_boundary_schema import (
        ensure_specialist_revenue_boundary_storage,
    )
''',
    '''    from src.adapters.sqlite.specialist_revenue_boundary_schema import (
        ensure_specialist_revenue_boundary_storage,
    )
    from src.adapters.sqlite.followup_operations_schema import (
        ensure_followup_operations_storage,
    )
''',
)
patch(
    "specialist_clinic/src/adapters/sqlite/core.py",
    '''    ensure_specialist_revenue_boundary_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_specialist_revenue_boundary_storage(db)
    ensure_followup_operations_storage(db)
    ensure_clinical_validation_storage(db)
''',
)
patch(
    "specialist_clinic/src/api/health.py",
    '''from src.adapters.sqlite.specialist_revenue_boundary_schema import (
    ensure_specialist_revenue_boundary_storage,
)
''',
    '''from src.adapters.sqlite.specialist_revenue_boundary_schema import (
    ensure_specialist_revenue_boundary_storage,
)
from src.adapters.sqlite.followup_operations_schema import (
    ensure_followup_operations_storage,
)
''',
)
patch(
    "specialist_clinic/src/api/health.py",
    '''        "accounting_invoice_attribution_events",
''',
    '''        "accounting_invoice_attribution_events",
        "followup_contact_events",
''',
)
patch(
    "specialist_clinic/src/api/health.py",
    '''    ensure_specialist_revenue_boundary_storage(db)
    ensure_clinical_validation_storage(db)
''',
    '''    ensure_specialist_revenue_boundary_storage(db)
    ensure_followup_operations_storage(db)
    ensure_clinical_validation_storage(db)
''',
)
patch(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    'SCOPE_VERSION = "1.2-specialist-revenue-boundary"',
    'SCOPE_VERSION = "1.3-followup-contacts"',
)
patch(
    "specialist_clinic/src/services/clinical_audit_integrity.py",
    '''    "accounting_invoice_attribution_events",
    "security_permission_events",
''',
    '''    "accounting_invoice_attribution_events",
    "followup_contact_events",
    "security_permission_events",
''',
)

# Permission vocabulary: contact work is not a clinical-decision transition.
patch(
    "specialist_clinic/src/security/permissions.py",
    '''    CLINICAL_TASK_VIEW = "clinical.task.view"
    CLINICAL_TASK_TRANSITION = "clinical.task.transition"
''',
    '''    CLINICAL_TASK_VIEW = "clinical.task.view"
    FOLLOWUP_CONTACT_RECORD = "followup.contact.record"
    CLINICAL_TASK_TRANSITION = "clinical.task.transition"
''',
)
patch(
    "specialist_clinic/src/security/permissions.py",
    '''            Permission.CLINICAL_TASK_VIEW,
        }
''',
    '''            Permission.CLINICAL_TASK_VIEW,
            Permission.FOLLOWUP_CONTACT_RECORD,
        }
''',
)

# Follow-up routes use one projection and append-only contact recording.
patch(
    "specialist_clinic/src/api/followups.py",
    '''from src.services.followup_service import FollowupService, REASON_LABELS
''',
    '''from src.services.followup_service import FollowupService, REASON_LABELS
from src.services.followup_projection_service import FollowupProjectionService
from src.services.followup_contact_service import (
    CHANNEL_LABELS as CONTACT_CHANNEL_LABELS,
    OUTCOME_LABELS as CONTACT_OUTCOME_LABELS,
    FollowupContactConflict,
    FollowupContactService,
    FollowupContactValidationError,
)
''',
)
patch(
    "specialist_clinic/src/api/followups.py",
    '''    repo = FollowupRepository()
    tasks = repo.search_open(q) if q else repo.list_open(reason)
''',
    '''    repo = FollowupRepository()
    projection = FollowupProjectionService(tasks=repo)
    tasks = projection.open_tasks(query=q or None, reason=reason)
''',
)
patch(
    "specialist_clinic/src/api/followups.py",
    '''        disposition_labels=DISPOSITION_LABELS,
        active_reason=reason,
''',
    '''        disposition_labels=DISPOSITION_LABELS,
        contact_channel_labels=CONTACT_CHANNEL_LABELS,
        contact_outcome_labels=CONTACT_OUTCOME_LABELS,
        active_reason=reason,
''',
)
contact_route = '''

@bp.post("/<int:task_id>/contact")
@permission_required(Permission.FOLLOWUP_CONTACT_RECORD)
def record_contact(task_id: int):
    raw_next = (request.form.get("next_contact_at") or "").strip()
    next_contact = None
    if raw_next:
        parsed = jalali_to_gregorian_str(raw_next) or raw_next
        next_contact = f"{parsed} 09:00:00" if len(parsed) == 10 else parsed
    try:
        event = FollowupContactService().record(
            task_id=task_id,
            channel=request.form.get("channel") or "PHONE",
            outcome=request.form.get("outcome") or "OTHER",
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            idempotency_key=request.form.get("idempotency_key") or "",
            note=request.form.get("note"),
            next_contact_at=next_contact,
        )
    except (LookupError, ValueError, FollowupContactConflict,
            FollowupContactValidationError, sqlite3.IntegrityError) as exc:
        flash(f"ثبت تماس انجام نشد: {exc}", "error")
    else:
        log_activity(
            "followup_contact_record",
            f"task={task_id} contact={event['id']} outcome={event['outcome']}",
            patient_link_id=int(event["patient_link_id"]),
        )
        flash("نتیجهٔ تماس به‌صورت افزایشی ثبت شد.", "success")
    return redirect(request.referrer or url_for("followups.worklist"))
'''
patch(
    "specialist_clinic/src/api/followups.py",
    '''

@bp.route("/<int:task_id>/resolve", methods=["POST"])
''',
    contact_route + '''

@bp.route("/<int:task_id>/resolve", methods=["POST"])
''',
)
patch(
    "specialist_clinic/src/api/followups.py",
    '''    repo = FollowupRepository()
    available = {
        int(task["id"]): task
        for task in repo.list_for_patient(pid)
        if task.get("status") == "open"
    }
''',
    '''    repo = FollowupRepository()
    available = {
        int(task["id"]): task
        for task in FollowupProjectionService(tasks=repo).patient_tasks(
            pid, include_terminal=False
        )
        if task.get("is_open")
    }
''',
)
patch(
    "specialist_clinic/src/api/followups.py",
    '''    admin_ids = [task_id for task_id in task_ids if task_id not in clinical_ids]
    if admin_ids:
        repo.assign_appointment_bulk(admin_ids, appointment_id)
        for task_id in admin_ids:
            repo.resolve(task_id, "done")

    scheduled = 0
''',
    '''    admin_ids = [task_id for task_id in task_ids if task_id not in clinical_ids]
    if admin_ids:
        # Booking is an intermediate funnel stage, not task completion.
        repo.assign_appointment_bulk(admin_ids, appointment_id)

    contacts = FollowupContactService()
    for task_id in task_ids:
        contacts.record(
            task_id=task_id,
            channel="SYSTEM",
            outcome="BOOKED",
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            idempotency_key=f"booking:{appointment_id}:task:{task_id}",
            note=f"نوبت #{appointment_id} از ورک‌لیست رزرو شد؛ task باز می‌ماند.",
        )

    scheduled = 0
''',
)
patch(
    "specialist_clinic/src/api/followups.py",
    '''        f"admin_closed={len(admin_ids)} clinical_scheduled={scheduled} patient={pid}",
''',
    '''        f"admin_booked={len(admin_ids)} clinical_scheduled={scheduled} patient={pid}",
''',
)
patch(
    "specialist_clinic/src/api/followups.py",
    '''        f"{len(admin_ids)} پیگیری اداری بسته و {scheduled} پیگیری بالینی زمان‌بندی شد.",
''',
    '''        f"برای {len(admin_ids)} پیگیری اداری نوبت ثبت شد و {scheduled} پیگیری بالینی زمان‌بندی شد؛ taskها تا حضور/نتیجه باز می‌مانند.",
''',
)

# Control Room receives event-derived open counts.
patch(
    "specialist_clinic/src/services/control_room_service.py",
    '''from src.services.revenue_service import RevenueService
''',
    '''from src.services.revenue_service import RevenueService
from src.services.followup_projection_service import FollowupProjectionService
''',
) if False else None
# A0 control room has no RevenueService import; anchor on common utils.
patch(
    "specialist_clinic/src/services/control_room_service.py",
    '''from src.common.utils import format_jalali_date, iran_now
''',
    '''from src.common.utils import format_jalali_date, iran_now
from src.services.followup_projection_service import FollowupProjectionService
''',
)
patch(
    "specialist_clinic/src/services/control_room_service.py",
    '''        patients: list[dict] = []
        summary = {
''',
    '''        open_followup_counts = FollowupProjectionService().open_counts_by_patient()
        patients: list[dict] = []
        summary = {
''',
)
patch(
    "specialist_clinic/src/services/control_room_service.py",
    '''            open_followups = int(row["open_fu"] or 0)
''',
    '''            open_followups = int(open_followup_counts.get(patient_id, 0))
''',
)

# Engagement health summary no longer reads stale legacy task status.
patch(
    "specialist_clinic/src/adapters/sqlite/engagement_repo.py",
    '''        worklist = db.execute("""SELECT
            SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) open,
            SUM(CASE WHEN status='open' AND due_date <= date('now','+3 hours','+30 minutes')
                     THEN 1 ELSE 0 END) due
            FROM followup_tasks""").fetchone()
''',
    '''        from src.services.followup_projection_service import FollowupProjectionService
        worklist = FollowupProjectionService().summary(as_of=iran_now())
''',
)
patch(
    "specialist_clinic/src/adapters/sqlite/engagement_repo.py",
    '''            'open_worklist': worklist['open'] or 0,
            'due_worklist': worklist['due'] or 0,
''',
    '''            'open_worklist': worklist['open_tasks'],
            'due_worklist': worklist['due_tasks'],
            'due_callbacks': worklist['due_callbacks'],
''',
)

# Extension pending list is also projection-based; only admin remote tasks are exposed.
patch(
    "specialist_clinic/src/api/ext.py",
    '''    db = get_db()
    rows = db.execute(
        """SELECT f.id AS followup_id, p.id AS patient_link_id,
                  p.national_id, p.full_name
           FROM followup_tasks f
           JOIN patient_links p ON p.id=f.patient_link_id
           WHERE f.status='open' AND f.fulfillment='remote'
             AND COALESCE(f.source_engine,'')<>'clinical_v2'
           ORDER BY f.due_date IS NULL, f.due_date
           LIMIT 200"""
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
''',
    '''    db = get_db()
    from src.services.followup_projection_service import FollowupProjectionService
    rows = [
        task for task in FollowupProjectionService().open_tasks()
        if task.get("fulfillment") == "remote"
        and task.get("source_engine") != "clinical_v2"
    ][:200]
    items = []
    for row in rows:
        item = dict(row)
        item["followup_id"] = int(item["id"])
        item["full_name"] = item.get("patient_name")
''',
)

# Worklist: surface contact history and collect structured outcomes.
patch(
    "specialist_clinic/src/templates/followups/worklist.html",
    '''                            <td>
                                {% if t.source_engine != 'clinical_v2' %}
''',
    '''                            <td>
                                {% if t.contact_count %}
                                <div class="text-xs muted" style="margin-bottom:var(--s2);">
                                    آخرین تماس: {{ contact_outcome_labels.get(t.last_contact_outcome, t.last_contact_outcome) }}
                                    · {{ t.last_contact_at|jalali if t.last_contact_at else '—' }}
                                    · {{ t.contact_count|fa_num }} تلاش
                                    {% if t.next_contact_at %} · تماس بعدی: {{ t.next_contact_at|jalali }}{% endif %}
                                </div>
                                {% endif %}
                                {% if permissions.get('followup.contact.record') %}
                                <details style="margin-bottom:var(--s2);">
                                    <summary class="btn btn-sm btn-ghost">ثبت نتیجهٔ تماس</summary>
                                    <form method="post" action="{{ url_for('followups.record_contact', task_id=t.id) }}" class="card card-soft" style="min-width:340px;margin-top:var(--s2);">
                                        <input type="hidden" name="idempotency_key" value="{{ t.contact_form_token }}">
                                        <div class="row">
                                            <div class="fld"><label>کانال</label><select name="channel">{% for key,label in contact_channel_labels.items() %}<option value="{{ key }}">{{ label }}</option>{% endfor %}</select></div>
                                            <div class="fld"><label>نتیجه</label><select name="outcome">{% for key,label in contact_outcome_labels.items() %}<option value="{{ key }}">{{ label }}</option>{% endfor %}</select></div>
                                        </div>
                                        <div class="row">
                                            <div class="fld"><label>تماس بعدی</label><input class="jdate" name="next_contact_at" placeholder="در صورت نیاز"></div>
                                            <div class="fld"><label>توضیح</label><input name="note"></div>
                                        </div>
                                        <button class="btn btn-sm" type="submit">ثبت رویداد تماس</button>
                                    </form>
                                </details>
                                {% endif %}
                                {% if t.source_engine != 'clinical_v2' %}
''',
)
patch(
    "specialist_clinic/src/templates/followups/worklist.html",
    '''<div class="section-sub">پیگیری اداری بسته می‌شود؛ پیگیری بالینی فقط SCHEDULED می‌شود و تا ثبت outcome باز می‌ماند.</div>''',
    '''<div class="section-sub">رزرو نوبت فقط مرحلهٔ BOOKED است؛ پیگیری اداری و بالینی تا حضور یا ثبت نتیجه باز می‌مانند.</div>''',
)
patch(
    "specialist_clinic/src/templates/followups/worklist.html",
    '''{% if t.source_engine == 'clinical_v2' %}<span class="badge badge-info">بالینی ـ فقط زمان‌بندی</span>{% endif %}''',
    '''{% if t.source_engine == 'clinical_v2' %}<span class="badge badge-info">بالینی ـ زمان‌بندی</span>{% else %}<span class="badge badge-muted">اداری ـ باز تا نتیجه</span>{% endif %}''',
)

# Mandatory project guidance.
path = ROOT / "specialist_clinic/CLAUDE.md"
text = path.read_text(encoding="utf-8")
marker = "## وضعیت واحد پیگیری و رویداد تماس (A1)"
if marker not in text:
    text += '''

## وضعیت واحد پیگیری و رویداد تماس (A1)

- هر surface باید وضعیت task را از `FollowupProjectionService` یا repository event-aware بخواند؛ query مستقیم `followup_tasks.status='open'` برای شمارش عمومی ممنوع است.
- وضعیت clinical task از `clinical_task_events` و وضعیت administrative task فعلاً از workflow خودش خوانده می‌شود، ولی خروجی نهایی یک قرارداد normalized دارد.
- هر تماس، پیام، پاسخ، عدم پاسخ، درخواست callback و booking باید در `followup_contact_events` به‌صورت append-only ثبت شود.
- BOOKED معادل COMPLETED یا درآمد نیست. رزرو appointment نباید task اداری را ببندد.
- تماس تلفنی و disposition اداری از تصمیم بالینی جدا هستند؛ permission `followup.contact.record` برای این کار استفاده می‌شود.
'''
    path.write_text(text, encoding="utf-8")

Path(__file__).unlink()

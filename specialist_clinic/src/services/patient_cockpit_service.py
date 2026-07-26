"""Presentation-ready care priorities and a unified patient activity timeline.

This service only composes already-authoritative domain data. It performs no SQL and keeps
patient-page prioritisation out of the Flask route/template. A8 service events are shown
only from current COMPLETE specialist service manifests; broad accounting visits are
suppressed only when the exact same accounting invoice has a governed VISIT line.
"""
from __future__ import annotations


APPOINTMENT_STATUS = {
    "scheduled": ("نوبت برنامه‌ریزی‌شده", "info"),
    "done": ("نوبت انجام‌شده", "ok"),
    "no_show": ("عدم مراجعه به نوبت", "warn"),
    "cancelled": ("نوبت لغوشده", "muted"),
}

FOLLOWUP_REASON = {
    "refill": "تجدید نسخه",
    "uncontrolled": "پیگیری قدیمی",
    "lapsed": "وقفه در مراجعه",
    "visit_due": "ویزیت سررسیده",
    "manual": "پیگیری دستی",
}

MEDICATION_EVENT = {
    "start": "شروع دارو",
    "stop": "قطع دارو",
    "dose_change": "تغییر دوز",
}

SERVICE_EVENT = {
    "VISIT": ("ویزیت تخصصی انجام‌شده", "stethoscope", "ok"),
    "INJECTION": ("تزریق انجام‌شده", "syringe", "info"),
    "PROCEDURE": ("خدمت عملی انجام‌شده", "clipboard", "info"),
}

DOCUMENT_OUTCOME = {
    "STABLE_CONTINUE": "پایدار؛ ادامه برنامه فعلی",
    "PLAN_CHANGED": "برنامه درمانی تغییر کرد",
    "FOLLOWUP_REQUIRED": "پیگیری لازم است",
    "REFERRED": "ارجاع انجام شد",
    "URGENT_ESCALATION": "اقدام یا ارجاع فوری",
    "OTHER": "سایر",
}


def _date(value) -> str:
    """Return a sortable ISO-like value without inventing a timestamp."""
    return str(value or "").strip()


class PatientCockpitService:
    @staticmethod
    def next_action(*, followups, refill_due, appointments, indicators,
                    clinical_v2=None, **_retired_inputs) -> dict:
        v2_groups = (clinical_v2 or {}).get("groups") or []
        v2_redflags = sum(
            len(group.get("items") or [])
            for group in v2_groups if group.get("action_type") == "redflag"
        )
        v2_actions = sum(
            1
            for group in v2_groups
            if group.get("action_type") in {"safety_alert", "suggest_med"}
            for item in (group.get("items") or [])
            if not item.get("current_decision")
            or item["current_decision"].get("decision") == "DEFERRED"
        )
        redflags = v2_redflags
        clinical_actions = v2_actions
        open_followups = [f for f in (followups or []) if f.get("status") == "open"]
        scheduled = [a for a in (appointments or []) if a.get("status") == "scheduled"]
        scheduled.sort(key=lambda a: _date(a.get("scheduled_at")))
        has_data = any(i.get("latest") is not None for i in (indicators or []))

        if redflags:
            return {
                "tone": "danger", "icon": "alert", "target": "cockpit",
                "title": "بررسی هشدار فوری",
                "detail": f"{redflags} هشدار بالینی نیازمند تصمیم پزشک است.",
            }
        if clinical_actions:
            return {
                "tone": "warn", "icon": "stethoscope", "target": "cockpit",
                "title": "مرور اقدام‌های بالینی",
                "detail": f"{clinical_actions} پیشنهاد درمانی یا ایمنی هنوز بررسی نشده است.",
            }
        if open_followups:
            due = sorted(open_followups, key=lambda f: (
                not bool(f.get("due_date")), _date(f.get("due_date"))))[0]
            return {
                "tone": "warn", "icon": "phone", "target": "worklist",
                "title": "رسیدگی به پیگیری باز",
                "detail": FOLLOWUP_REASON.get(due.get("reason"), due.get("reason") or "پیگیری بیمار"),
                "date": due.get("due_date"),
            }
        if refill_due:
            return {
                "tone": "warn", "icon": "pill", "target": "meds",
                "title": "بررسی تجدید نسخه",
                "detail": f"{refill_due} دارو در بازه تجدید نسخه قرار دارد.",
            }
        if not has_data:
            return {
                "tone": "info", "icon": "activity", "target": "cockpit",
                "title": "ثبت اولین اندازه‌گیری",
                "detail": "برای تکمیل روند دادهٔ پرونده، یک اندازه‌گیری پایه ثبت کنید.",
            }
        if scheduled:
            return {
                "tone": "ok", "icon": "calendar", "target": "record",
                "title": "آماده‌سازی ویزیت بعدی",
                "detail": scheduled[0].get("appt_type") or "نوبت ثبت‌شده",
                "date": scheduled[0].get("scheduled_at"),
            }
        return {
            "tone": "ok", "icon": "check", "target": "appointment",
            "title": "کار اداری باز ثبت نشده",
            "detail": "در صورت نیاز می‌توانید نوبت بعدی را برنامه‌ریزی کنید.",
        }

    @staticmethod
    def timeline(*, appointments, visits, labs, followups, medication_events,
                 service_lines=None, encounter_documents=None,
                 limit: int = 24) -> list[dict]:
        events: list[dict] = []
        exact_lines = list(service_lines or [])
        exact_visit_invoice_ids = {
            int(line["accounting_invoice_id"])
            for line in exact_lines
            if str(line.get("item_type") or "").upper() == "VISIT"
            and line.get("accounting_invoice_id") is not None
        }
        visit_days = {_date(v.get("visit_date"))[:10] for v in (visits or [])}

        for document in encounter_documents or []:
            assessment = str(document.get("assessment") or "").strip()
            if len(assessment) > 140:
                assessment = assessment[:137].rstrip() + "…"
            outcome = DOCUMENT_OUTCOME.get(
                document.get("outcome_code"),
                document.get("outcome_code") or "سند امضاشده",
            )
            detail = outcome
            if assessment:
                detail = f"{outcome} · {assessment}"
            events.append({
                "sort_at": _date(document.get("authored_at")),
                "date": document.get("authored_at"),
                "kind": "encounter_document",
                "icon": "clipboard",
                "tone": (
                    "danger"
                    if document.get("outcome_code") == "URGENT_ESCALATION"
                    else "warn"
                    if document.get("outcome_code") in {"REFERRED", "FOLLOWUP_REQUIRED"}
                    else "ok"
                ),
                "title": "سند ویزیت امضاشده",
                "detail": detail,
                "document_invoice_id": document.get("accounting_invoice_id"),
                "encounter_id": document.get("encounter_id"),
                "lineage": "SIGNED_ENCOUNTER_DOCUMENT_V1",
            })

        for line in exact_lines:
            item_type = str(line.get("item_type") or "").upper()
            title, icon, tone = SERVICE_EVENT.get(
                item_type, ("خدمت تخصصی انجام‌شده", "clipboard", "info")
            )
            detail_parts = [str(line.get("description") or "").strip()]
            performer = str(line.get("performer_name") or "").strip()
            if performer:
                detail_parts.append(performer)
            when = line.get("performed_at") or line.get("work_date")
            events.append({
                "sort_at": _date(when),
                "date": when,
                "kind": f"service_{item_type.lower()}",
                "icon": icon,
                "tone": tone,
                "title": title,
                "detail": " · ".join(part for part in detail_parts if part),
                "accounting_invoice_id": line.get("accounting_invoice_id"),
                "encounter_id": line.get("encounter_id"),
                "lineage": "ACCOUNTING_SERVICE_LINES_V1",
            })

        for visit in visits or []:
            invoice_id = visit.get("invoice_id")
            if invoice_id is not None and int(invoice_id) in exact_visit_invoice_ids:
                continue
            events.append({
                "sort_at": _date(visit.get("visit_date")),
                "date": visit.get("visit_date"),
                "kind": "visit", "icon": "building", "tone": "ok",
                "title": "ویزیت ثبت‌شده در حسابداری",
                "detail": visit.get("doctor_name") or "جزئیات خدمت هنوز وارد lineage تخصصی نشده است",
                "accounting_invoice_id": invoice_id,
            })

        for appointment in appointments or []:
            when = _date(appointment.get("scheduled_at"))
            status = appointment.get("status") or "scheduled"
            if status == "done" and when[:10] in visit_days:
                continue
            title, tone = APPOINTMENT_STATUS.get(status, ("نوبت", "muted"))
            detail = appointment.get("appt_type") or appointment.get("notes") or ""
            events.append({
                "sort_at": when, "date": appointment.get("scheduled_at"),
                "kind": "appointment", "icon": "calendar", "tone": tone,
                "title": title, "detail": detail,
            })

        for lab in labs or []:
            value = lab.get("value")
            measured = "" if value is None else str(value)
            unit = lab.get("unit") or ""
            events.append({
                "sort_at": _date(lab.get("taken_at")), "date": lab.get("taken_at"),
                "kind": "lab", "icon": "flask", "tone": "info",
                "title": lab.get("test_name") or "نتیجه آزمایش",
                "detail": " ".join(part for part in (measured, unit) if part),
            })

        for task in followups or []:
            status = task.get("status") or "open"
            when = task.get("resolved_at") if status != "open" else (
                task.get("due_date") or task.get("created_at"))
            events.append({
                "sort_at": _date(when), "date": when,
                "kind": "followup", "icon": "phone",
                "tone": "warn" if status == "open" else "ok" if status == "done" else "muted",
                "title": "پیگیری باز" if status == "open" else "پیگیری انجام‌شده" if status == "done" else "پیگیری بسته‌شده",
                "detail": task.get("detail") or FOLLOWUP_REASON.get(task.get("reason"), task.get("reason") or ""),
            })

        for event in medication_events or []:
            event_type = event.get("event_type") or "start"
            detail = event.get("drug_name") or ""
            if event.get("dose"):
                detail = f"{detail} · {event['dose']}" if detail else str(event["dose"])
            events.append({
                "sort_at": _date(event.get("event_date") or event.get("created_at")),
                "date": event.get("event_date") or event.get("created_at"),
                "kind": "medication", "icon": "pill",
                "tone": "warn" if event_type == "stop" else "info",
                "title": MEDICATION_EVENT.get(event_type, "رویداد دارویی"),
                "detail": detail,
            })

        events = [event for event in events if event["sort_at"]]
        events.sort(key=lambda event: event["sort_at"], reverse=True)
        return events[:max(1, int(limit))]

"""Presentation-ready care priorities and a unified patient activity timeline.

This service only composes already-authoritative domain data.  It performs no
SQL and keeps patient-page prioritisation out of the Flask route/template.
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
    "uncontrolled": "کنترل نامطلوب",
    "lapsed": "وقفه در مراجعه",
    "visit_due": "ویزیت سررسیده",
    "manual": "پیگیری دستی",
}

MEDICATION_EVENT = {
    "start": "شروع دارو",
    "stop": "قطع دارو",
    "dose_change": "تغییر دوز",
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
            # ACCEPTED/DISMISSED are completed reviews.  DEFERRED deliberately
            # stays actionable, because the clinician asked to revisit it.
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
                "title": "ثبت اولین شاخص بالینی",
                "detail": "برای ارزیابی کنترل بیماری، اندازه‌گیری پایه را ثبت کنید.",
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
            "title": "مورد فوری ثبت نشده",
            "detail": "برای حفظ تداوم مراقبت می‌توانید نوبت بعدی را برنامه‌ریزی کنید.",
        }

    @staticmethod
    def timeline(*, appointments, visits, labs, followups, medication_events,
                 limit: int = 16) -> list[dict]:
        events: list[dict] = []
        visit_days = {_date(v.get("visit_date"))[:10] for v in (visits or [])}

        for visit in visits or []:
            events.append({
                "sort_at": _date(visit.get("visit_date")),
                "date": visit.get("visit_date"),
                "kind": "visit", "icon": "building", "tone": "ok",
                "title": "ویزیت انجام‌شده",
                "detail": visit.get("doctor_name") or "ویزیت ثبت‌شده در حسابداری",
            })

        for appointment in appointments or []:
            when = _date(appointment.get("scheduled_at"))
            status = appointment.get("status") or "scheduled"
            # A completed local appointment on the same day as the accounting
            # visit is one real-world event, not two timeline entries.
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

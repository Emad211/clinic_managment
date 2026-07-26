from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A9 timeline target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A9 timeline anchor missing in {relative}: {old[:220]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "specialist_clinic/src/services/patient_cockpit_service.py",
    '''SERVICE_EVENT = {
    "VISIT": ("ویزیت تخصصی انجام‌شده", "stethoscope", "ok"),
    "INJECTION": ("تزریق انجام‌شده", "syringe", "info"),
    "PROCEDURE": ("خدمت عملی انجام‌شده", "clipboard", "info"),
}
''',
    '''SERVICE_EVENT = {
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
''',
)
replace_once(
    "specialist_clinic/src/services/patient_cockpit_service.py",
    '''    def timeline(*, appointments, visits, labs, followups, medication_events,
                 service_lines=None, limit: int = 24) -> list[dict]:
''',
    '''    def timeline(*, appointments, visits, labs, followups, medication_events,
                 service_lines=None, encounter_documents=None,
                 limit: int = 24) -> list[dict]:
''',
)
replace_once(
    "specialist_clinic/src/services/patient_cockpit_service.py",
    '''        visit_days = {_date(v.get("visit_date"))[:10] for v in (visits or [])}

        for line in exact_lines:
''',
    '''        visit_days = {_date(v.get("visit_date"))[:10] for v in (visits or [])}

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
''',
)

replace_once(
    "specialist_clinic/src/api/patients.py",
    '''    care_timeline = cockpit_service.timeline(
        appointments=appointments,
''',
    '''    from src.adapters.sqlite.encounter_documentation_repo import (
        EncounterDocumentationRepository,
    )
    encounter_documents = (
        EncounterDocumentationRepository().current_signed_documents_for_patient(
            pid, limit=50
        )
    )
    care_timeline = cockpit_service.timeline(
        appointments=appointments,
''',
)
replace_once(
    "specialist_clinic/src/api/patients.py",
    '''        medication_events=medication_events,
        service_lines=service_lines,
    )
''',
    '''        medication_events=medication_events,
        service_lines=service_lines,
        encounter_documents=encounter_documents,
    )
''',
)
replace_once(
    "specialist_clinic/src/api/patients.py",
    '''        care_timeline=care_timeline,
        service_line_summary=service_line_summary,
''',
    '''        care_timeline=care_timeline,
        encounter_documents=encounter_documents,
        service_line_summary=service_line_summary,
''',
)

replace_once(
    "specialist_clinic/src/templates/patients/detail.html",
    '''                    <strong>{{ event.title }}{% if event.lineage %} <span class="badge badge-info text-xs">متصل به Encounter</span>{% endif %}</strong>
                    {% if event.detail %}<span>{{ event.detail }}</span>{% endif %}
''',
    '''                    <strong>{% if event.document_invoice_id %}<a href="{{ url_for('doctor_queue.document_detail', invoice_id=event.document_invoice_id) }}">{{ event.title }}</a>{% else %}{{ event.title }}{% endif %}{% if event.lineage %} <span class="badge badge-info text-xs">متصل به Encounter</span>{% endif %}</strong>
                    {% if event.detail %}<span>{{ event.detail }}</span>{% endif %}
''',
)

Path(__file__).unlink()

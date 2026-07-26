from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A8 UI target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A8 UI anchor missing in {relative}: {old[:220]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "specialist_clinic/src/api/patients.py",
    '''    cockpit_service = PatientCockpitService()
    next_action = cockpit_service.next_action(
''',
    '''    from src.adapters.sqlite.specialist_service_lineage_repo import (
        SpecialistServiceLineageRepository,
    )
    cockpit_service = PatientCockpitService()
    service_lines = SpecialistServiceLineageRepository().current_lines_for_patient(
        pid, limit=200
    )
    service_line_summary = {
        "total": len(service_lines),
        "visits": sum(1 for row in service_lines if row.get("item_type") == "VISIT"),
        "injections": sum(
            1 for row in service_lines if row.get("item_type") == "INJECTION"
        ),
        "procedures": sum(
            1 for row in service_lines if row.get("item_type") == "PROCEDURE"
        ),
    }
    next_action = cockpit_service.next_action(
''',
)
replace_once(
    "specialist_clinic/src/api/patients.py",
    '''        followups=all_followups,
        medication_events=medication_events,
    )
''',
    '''        followups=all_followups,
        medication_events=medication_events,
        service_lines=service_lines,
    )
''',
)
replace_once(
    "specialist_clinic/src/api/patients.py",
    '''        care_timeline=care_timeline,
        sms_consent=sms_consent,
''',
    '''        care_timeline=care_timeline,
        service_line_summary=service_line_summary,
        sms_consent=sms_consent,
''',
)

replace_once(
    "specialist_clinic/src/templates/patients/detail.html",
    '''        <div class="section-title"><svg class="icon"><use href="#i-activity"></use></svg> تاریخچه مراقبت <span class="section-sub">ویزیت، آزمایش، نوبت، دارو و پیگیری در یک مسیر زمانی</span></div>
        {% if care_timeline %}
''',
    '''        <div class="section-title"><svg class="icon"><use href="#i-activity"></use></svg> تاریخچه مراقبت <span class="section-sub">ویزیت، تزریق، خدمت عملی، آزمایش، نوبت، دارو و پیگیری در یک مسیر زمانی</span></div>
        {% if service_line_summary.total %}
        <div class="legend" style="margin-bottom:var(--s3);">
            <span class="chip">خدمات دقیق: {{ service_line_summary.total|fa_num }}</span>
            <span class="chip"><span class="dot dot-ok"></span> ویزیت: {{ service_line_summary.visits|fa_num }}</span>
            <span class="chip"><span class="dot dot-info"></span> تزریق: {{ service_line_summary.injections|fa_num }}</span>
            <span class="chip">خدمت عملی: {{ service_line_summary.procedures|fa_num }}</span>
        </div>
        {% endif %}
        {% if care_timeline %}
''',
)
replace_once(
    "specialist_clinic/src/templates/patients/detail.html",
    '''                    <strong>{{ event.title }}</strong>
                    {% if event.detail %}<span>{{ event.detail }}</span>{% endif %}
''',
    '''                    <strong>{{ event.title }}{% if event.lineage %} <span class="badge badge-info text-xs">متصل به Encounter</span>{% endif %}</strong>
                    {% if event.detail %}<span>{{ event.detail }}</span>{% endif %}
''',
)

Path(__file__).unlink()

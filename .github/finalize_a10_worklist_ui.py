from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A10 UI target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A10 UI anchor missing in {relative}: {old[:220]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "specialist_clinic/src/templates/followups/worklist.html",
    '''                                {% elif t.fulfillment == 'remote' %}
                                    <span class="badge badge-info">اداری ـ از راه دور</span>
''',
    '''                                {% elif t.source_engine == 'encounter_plan' %}
                                    <span class="badge badge-violet">تعهد طرح Encounter</span>
                                    <span class="badge badge-muted">{{ t.status_fa or t.current_status }}</span>
                                    {% if t.is_overdue %}<span class="badge badge-danger">{{ t.overdue_days|fa_num }} روز تأخیر</span>{% endif %}
                                {% elif t.fulfillment == 'remote' %}
                                    <span class="badge badge-info">اداری ـ از راه دور</span>
''',
)
replace_once(
    "specialist_clinic/src/templates/followups/worklist.html",
    '''                                {% if t.source_engine == 'clinical_v2' %}
                                    <div class="text-xs" style="margin-top:var(--s1);">
''',
    '''                                {% if t.source_engine == 'encounter_plan' %}
                                    <div class="text-xs" style="margin-top:var(--s1);">
                                        <span class="badge badge-info">{{ plan_commitment_labels.get(t.commitment_type, t.commitment_type) }}</span>
                                        · سند #{{ t.document_event_id|fa_num }}
                                        · Encounter <code dir="ltr">{{ t.encounter_id }}</code>
                                        {% if t.current_assigned_to %} · مسئول: {{ t.current_assigned_to }}{% endif %}
                                    </div>
                                {% elif t.source_engine == 'clinical_v2' %}
                                    <div class="text-xs" style="margin-top:var(--s1);">
''',
)
replace_once(
    "specialist_clinic/src/templates/followups/worklist.html",
    '''                                {% if t.source_engine != 'clinical_v2' %}
''',
    '''                                {% if t.source_engine not in ['clinical_v2','encounter_plan'] %}
''',
)
# Insert Plan lifecycle UI before clinical lifecycle branch.
replace_once(
    "specialist_clinic/src/templates/followups/worklist.html",
    '''                                {% elif permissions.get('clinical.task.transition') or permissions.get('clinical.outcome.record') %}
                                    <details>
                                        <summary class="btn btn-sm btn-ghost">ثبت lifecycle / نتیجه</summary>
''',
    '''                                {% elif t.source_engine == 'encounter_plan' and permissions.get('followup.plan.transition') %}
                                    <details>
                                        <summary class="btn btn-sm btn-ghost">مدیریت تعهد طرح</summary>
                                        <div class="card card-soft" style="min-width:390px;margin-top:var(--s2);">
                                            <div class="text-sm"><b>{{ plan_commitment_labels.get(t.commitment_type, t.commitment_type) }}</b></div>
                                            <div class="muted text-xs">{{ t.instruction }}</div>
                                            <div class="flex gap-2 wrap" style="margin-top:var(--s2);">
                                                {% if t.current_status in ['OPEN','SCHEDULED'] %}
                                                <form method="post" action="{{ url_for('followups.plan_transition', task_id=t.id) }}">
                                                    <input type="hidden" name="expected_current_event_id" value="{{ t.current_event_id }}">
                                                    <input type="hidden" name="idempotency_key" value="plan-start-{{ t.current_event_id }}-{{ t.contact_form_token }}">
                                                    <input type="hidden" name="transition" value="start">
                                                    <button class="btn btn-sm" type="submit">شروع انجام</button>
                                                </form>
                                                {% endif %}
                                            </div>
                                            <form method="post" action="{{ url_for('followups.plan_transition', task_id=t.id) }}" class="row" style="margin-top:var(--s2);">
                                                <input type="hidden" name="expected_current_event_id" value="{{ t.current_event_id }}">
                                                <input type="hidden" name="idempotency_key" value="plan-assign-{{ t.current_event_id }}-{{ t.contact_form_token }}">
                                                <input type="hidden" name="transition" value="assign">
                                                <div class="fld"><label>واگذاری به</label><input name="assigned_to" value="{{ t.current_assigned_to or '' }}" required></div>
                                                <button class="btn btn-sm" type="submit">ثبت واگذاری</button>
                                            </form>
                                            <form method="post" action="{{ url_for('followups.plan_transition', task_id=t.id) }}" class="row" style="margin-top:var(--s2);">
                                                <input type="hidden" name="expected_current_event_id" value="{{ t.current_event_id }}">
                                                <input type="hidden" name="idempotency_key" value="plan-reschedule-{{ t.current_event_id }}-{{ t.contact_form_token }}">
                                                <input type="hidden" name="transition" value="reschedule">
                                                <div class="fld"><label>موعد جدید</label><input class="jdate" name="due_at" required></div>
                                                <div class="fld"><label>ساعت</label><input type="time" name="due_time" value="09:00"></div>
                                                <button class="btn btn-sm" type="submit">تعویق تاریخچه‌دار</button>
                                            </form>
                                            <hr>
                                            <form method="post" action="{{ url_for('followups.plan_transition', task_id=t.id) }}" class="flex" style="flex-direction:column;gap:var(--s2);">
                                                <input type="hidden" name="expected_current_event_id" value="{{ t.current_event_id }}">
                                                <input type="hidden" name="idempotency_key" value="plan-complete-{{ t.current_event_id }}-{{ t.contact_form_token }}">
                                                <input type="hidden" name="transition" value="complete">
                                                <div class="row">
                                                    <div class="fld"><label>نوع شاهد</label><select name="evidence_type">{% for key,label in plan_evidence_labels.items() %}<option value="{{ key }}">{{ label }}</option>{% endfor %}</select></div>
                                                    <div class="fld"><label>شناسه شاهد</label><input name="evidence_ref" required></div>
                                                    <div class="fld"><label>نتیجه</label><select name="outcome_code">{% for key,label in plan_outcome_labels.items() %}<option value="{{ key }}">{{ label }}</option>{% endfor %}</select></div>
                                                </div>
                                                <div class="fld"><label>توضیح/مستند دستی</label><input name="note"></div>
                                                <button class="btn btn-sm btn-ok" type="submit">تکمیل با شاهد</button>
                                            </form>
                                            <form method="post" action="{{ url_for('followups.plan_transition', task_id=t.id) }}" class="row" style="margin-top:var(--s2);">
                                                <input type="hidden" name="expected_current_event_id" value="{{ t.current_event_id }}">
                                                <input type="hidden" name="idempotency_key" value="plan-cancel-{{ t.current_event_id }}-{{ t.contact_form_token }}">
                                                <input type="hidden" name="transition" value="cancel">
                                                <div class="fld" style="flex:1;"><label>دلیل لغو</label><input name="note" required></div>
                                                <button class="btn btn-sm btn-ghost" type="submit">لغو تاریخچه‌دار</button>
                                            </form>
                                        </div>
                                    </details>
                                {% elif permissions.get('clinical.task.transition') or permissions.get('clinical.outcome.record') %}
                                    <details>
                                        <summary class="btn btn-sm btn-ghost">ثبت lifecycle / نتیجه</summary>
''',
)

# Document page displays immutable signed commitments.
document = target("specialist_clinic/src/templates/doctor_queue/document_detail.html")
text = document.read_text(encoding="utf-8")
section = '''
{% if current.commitments %}
<div class="card">
  <div class="section-title"><svg class="icon"><use href="#i-list-checks"></use></svg> تعهدهای اجرایی نسخه امضاشده</div>
  {% for item in current.commitments %}
  <div class="list-row">
    <div><b>{{ item.instruction }}</b><div class="muted text-xs">{{ item.commitment_type }} · {{ item.fulfillment }}{% if item.assigned_to %} · {{ item.assigned_to }}{% endif %}</div></div>
    <span class="badge badge-info">{{ item.due_at|jalali }}</span>
  </div>
  {% endfor %}
  <div class="help">این مجموعه بخشی از سند امضاشده است. تغییر عملیاتی موعد، مسئول یا وضعیت فقط در Worklist و به‌صورت event ثبت می‌شود.</div>
</div>
{% endif %}
'''
if section.strip() not in text:
    marker = "{% endblock %}"
    if marker not in text:
        raise AssertionError("A10 document UI endblock anchor missing")
    text = text.replace(marker, section + "\n" + marker, 1)
    document.write_text(text, encoding="utf-8")

Path(__file__).unlink()

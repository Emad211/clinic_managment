from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A9 UI target missing: {relative}")
    return path


# ---------------------------------------------------------------------------
# Doctor queue: no direct completion; active visits continue to documentation.
# ---------------------------------------------------------------------------
queue = target("specialist_clinic/src/templates/doctor_queue/queue.html")
queue.write_text('''{% extends "base.html" %}
{% block title %}صف پزشک{% endblock %}
{% block content %}
<div class="topbar">
    <div>
        <h1><svg class="icon icon-lg"><use href="#i-stethoscope"></use></svg> صف پزشک <span class="muted text-sm">{{ work_date|jalali_date }}</span></h1>
        <div class="muted text-sm">شروع ویزیت، حضور واقعی Encounter را ثبت می‌کند. پایان ویزیت فقط پس از امضای سند Encounter ممکن است.</div>
    </div>
    <a class="btn btn-ghost" href="{{ url_for('doctor_queue.index') }}">تازه‌سازی</a>
</div>
<p class="page-intro">
    بیماران دارای فاکتور ویزیت باز امروز، زنده و فقط‌خواندنی از پذیرش. نوبت و پاسخ کمپین فقط با انتخاب صریح متصل می‌شوند؛
    <b>فاکتور حسابداری در این صفحه تغییر نمی‌کند.</b>
</p>

<div class="card">
    <div class="section-title"><svg class="icon"><use href="#i-list-checks"></use></svg> در نوبت <span class="badge badge-warn">{{ waiting|length|fa_num }}</span></div>
    {% if waiting %}
    <div class="table-wrap"><table>
        <thead><tr><th>بیمار</th><th>زمان پذیرش</th><th>نوبت تخصصی</th><th>پاسخ مثبت کمپین</th><th>اقدام بعدی</th></tr></thead>
        <tbody>
        {% for p in waiting %}
        <tr>
            <td>
                <strong>{{ p.full_name }}</strong>
                <div class="muted text-xs nums">{{ p.national_id|fa_num }}</div>
                {% if p.enrolled %}<span class="badge badge-info text-xs">عضو برنامه تخصصی</span>{% else %}<span class="badge badge-muted text-xs">ثبت‌نشده</span>{% endif %}
                {% if p.status=='in_progress' %}<span class="badge badge-violet text-xs">در حال ویزیت</span>{% endif %}
            </td>
            <td class="nums">{{ p.opened_at|jalali }}</td>
            <td>
                {% if p.linked_appointment_id %}
                    <span class="badge badge-ok">متصل به نوبت #{{ p.linked_appointment_id|fa_num }}</span>
                {% elif p.appointment_options %}
                    <div class="muted text-xs">هنگام شروع، نوبت واقعی را انتخاب کنید.</div>
                    {% for appointment in p.appointment_options %}
                        <div class="text-sm nums">#{{ appointment.id|fa_num }} · {{ appointment.scheduled_at|jalali }}</div>
                    {% endfor %}
                {% else %}<span class="badge badge-muted">Walk-in / بدون نوبت همان روز</span>{% endif %}
            </td>
            <td>
                {% if p.campaign_response_options %}
                <div class="muted text-xs">فقط آخرین پاسخ مثبت صریح قابل انتخاب است.</div>
                {% for response in p.campaign_response_options %}
                <div class="text-sm">{{ response.campaign_name }} · پاسخ #{{ response.id|fa_num }} · {{ response.recorded_at|jalali }}</div>
                {% endfor %}
                {% else %}<span class="badge badge-muted">بدون پاسخ مثبت قابل انتساب</span>{% endif %}
            </td>
            <td>
                {% if not p.enrolled %}
                    <span class="muted text-xs">ابتدا بیمار را وارد برنامه تخصصی کنید.</span>
                {% elif p.status=='in_progress' %}
                    <a class="btn btn-sm" href="{{ url_for('doctor_queue.visit', invoice_id=p.invoice_id) }}"><svg class="icon icon-sm"><use href="#i-edit"></use></svg> ادامه مستندسازی</a>
                {% else %}
                    <form class="m-0 flex items-center gap-2 wrap" method="post" action="{{ url_for('doctor_queue.start', invoice_id=p.invoice_id) }}">
                        {% if not p.linked_appointment_id and p.appointment_options %}
                        <select name="appointment_id" aria-label="نوبت مرتبط">
                            <option value="">Walk-in / بدون اتصال نوبت</option>
                            {% for appointment in p.appointment_options %}
                            <option value="{{ appointment.id }}">نوبت #{{ appointment.id|fa_num }} — {{ appointment.scheduled_at|jalali }}</option>
                            {% endfor %}
                        </select>
                        {% endif %}
                        {% if p.campaign_response_options and permissions.get('sms.campaign.attribution.record') %}
                        <select name="campaign_response_event_id" aria-label="پاسخ کمپین مرتبط">
                            <option value="">بدون انتساب کمپین</option>
                            {% for response in p.campaign_response_options %}
                            <option value="{{ response.id }}">{{ response.campaign_name }} — پاسخ #{{ response.id|fa_num }}</option>
                            {% endfor %}
                        </select>
                        {% endif %}
                        <button class="btn btn-sm btn-ok" type="submit"><svg class="icon icon-sm"><use href="#i-stethoscope"></use></svg> شروع و ثبت حضور</button>
                    </form>
                {% endif %}
            </td>
        </tr>
        {% endfor %}
        </tbody>
    </table></div>
    {% else %}<div class="empty"><svg class="icon"><use href="#i-check"></use></svg><div>صف خالی است — فاکتور ویزیت بازی نیست.</div></div>{% endif %}
</div>

<div class="card">
    <div class="section-title"><svg class="icon"><use href="#i-check"></use></svg> انجام‌شده امروز <span class="badge badge-ok">{{ done|length|fa_num }}</span></div>
    {% if done %}
    <div class="table-wrap"><table>
        <thead><tr><th>بیمار</th><th>اتصال نوبت</th><th>توسط</th><th>سند Encounter</th></tr></thead>
        <tbody>
        {% for p in done %}
        <tr>
            <td>{{ p.full_name }} <span class="muted text-xs nums">{{ p.national_id|fa_num }}</span></td>
            <td>{% if p.linked_appointment_id %}<span class="badge badge-ok">#{{ p.linked_appointment_id|fa_num }}</span>{% else %}<span class="muted">Walk-in</span>{% endif %}</td>
            <td class="muted text-sm">{{ p.done_by or '—' }}</td>
            <td><a class="btn btn-sm btn-ghost" href="{{ url_for('doctor_queue.document_detail', invoice_id=p.invoice_id) }}"><svg class="icon icon-sm"><use href="#i-clipboard"></use></svg> مشاهده سند</a></td>
        </tr>
        {% endfor %}
        </tbody>
    </table></div>
    {% else %}<div class="empty"><div>هنوز ویزیتی انجام نشده است.</div></div>{% endif %}
</div>
{% endblock %}
''', encoding="utf-8")

# ---------------------------------------------------------------------------
# Structured active-visit documentation form.
# ---------------------------------------------------------------------------
visit = target("specialist_clinic/src/templates/doctor_queue/visit_quick.html")
visit.write_text('''{% extends "base.html" %}
{% block title %}ویزیت — {{ patient.full_name }}{% endblock %}
{% block content %}
<div class="crumb"><a href="{{ url_for('doctor_queue.index') }}">صف پزشک</a> / مستندسازی Encounter</div>
<div class="topbar">
    <div>
      <h1><svg class="icon icon-lg"><use href="#i-stethoscope"></use></svg> {{ patient.full_name }} <span class="muted text-sm nums">{{ patient.national_id|fa_num }}</span></h1>
      <div class="muted text-sm">Encounter <code dir="ltr">{{ encounter_id }}</code> · {% if current_document %}نسخه جاری #{{ current_document.id|fa_num }} — {{ 'امضاشده' if current_document.document_status=='SIGNED' else 'پیش‌نویس' }}{% else %}هنوز پیش‌نویسی ثبت نشده است{% endif %}</div>
    </div>
    <a class="btn btn-ghost" href="{{ url_for('patients.detail', pid=pid) }}"><svg class="icon"><use href="#i-clipboard"></use></svg> پرونده کامل</a>
</div>

{% if allergies %}<div class="alert-banner alert-warn"><svg class="icon"><use href="#i-alert"></use></svg><span><b>حساسیت:</b> {% for a in allergies %}{{ a.substance }}{% if not loop.last %}، {% endif %}{% endfor %}</span></div>{% endif %}
<div class="alert-banner alert-info"><svg class="icon"><use href="#i-info"></use></svg><span>ذخیره پیش‌نویس Encounter را باز نگه می‌دارد. «امضا و پایان ویزیت» نسخه را قفل و Encounter را در همان تراکنش تکمیل می‌کند. اصلاح بعدی فقط با Amendment تاریخچه‌دار ممکن است.</span></div>

<form method="post" action="{{ url_for('doctor_queue.save', invoice_id=invoice_id) }}" class="stack">
  <input type="hidden" name="document_request_id" value="{{ document_request_id }}">
  <input type="hidden" name="expected_current_event_id" value="{{ current_document.id if current_document else '' }}">

  <div class="grid" style="grid-template-columns:minmax(280px,.8fr) minmax(420px,1.2fr);gap:var(--s3);align-items:start;">
    <div class="card">
      <div class="section-title"><svg class="icon"><use href="#i-activity"></use></svg> زمینه و داده امروز</div>
      <div class="fld"><label>بیماری‌های ثبت‌شده</label><div class="flex items-center gap-2 wrap">{% for c in conditions %}<span class="badge badge-info">{{ c.condition_name or c.name }}</span>{% else %}<span class="muted">—</span>{% endfor %}</div></div>
      <div class="fld"><label>داروهای فعال</label><div class="flex items-center gap-2 wrap">{% for m in medications if m.is_active %}<span class="chip">{{ m.drug_name }}{% if m.dose %} · {{ m.dose }}{% endif %}</span>{% else %}<span class="muted">—</span>{% endfor %}</div></div>
      <div class="fld"><label>آخرین شاخص‌ها</label>{% if recent_vitals %}<div class="flex items-center gap-2 wrap">{% for v in recent_vitals %}<span class="chip">{{ v.type_label }}: <b>{{ v.value|fa_num }}</b> <span class="muted text-xs">{{ v.measured_at|jalali_date }}</span></span>{% endfor %}</div>{% else %}<span class="muted">شاخصی ثبت نشده</span>{% endif %}</div>
      {% if last_note %}<div class="fld"><label>یادداشت قدیمی معاینه <span class="badge badge-muted text-xs">خارج از lineage Encounter</span></label><div class="muted" style="white-space:pre-wrap;">{{ last_note.body }}</div></div>{% endif %}
      {% if open_followups %}<div class="help"><svg class="icon icon-sm"><use href="#i-bell"></use></svg> {{ open_followups|length|fa_num }} پیگیری باز</div>{% endif %}
      <hr class="sep">
      <div class="section-title"><svg class="icon"><use href="#i-activity"></use></svg> شاخص‌های امروز</div>
      <div class="grid grid-2">
        {% for i in entry_indicators %}<div class="fld"><label>{{ i.label }}</label><input type="number" step="any" name="{{ i.key }}" placeholder="{{ i.unit or '' }}"></div>{% else %}<div class="empty-mini" style="grid-column:1/-1;">شاخص تخصصی تعریف نشده است.</div>{% endfor %}
      </div>
      <div class="fld"><label>تاریخ اندازه‌گیری</label><input type="text" class="jdate" name="measured_date" placeholder="امروز"></div>
    </div>

    <div class="card" id="encounter-document">
      <div class="section-title"><svg class="icon"><use href="#i-clipboard"></use></svg> سند ساختاریافته Encounter</div>
      <div class="fld"><label>شکایت اصلی / دلیل مراجعه</label><textarea name="chief_complaint" rows="2" placeholder="با بیان بیمار و بدون استنتاج از فاکتور">{{ current_document.chief_complaint if current_document else '' }}</textarea></div>
      <div class="fld"><label>یافته‌های عینی و معاینه</label><textarea name="objective_findings" rows="3" placeholder="یافته‌های مشاهده‌شده یا اندازه‌گیری‌شده">{{ current_document.objective_findings if current_document else '' }}</textarea></div>
      <div class="fld"><label>مشکلات / مسائل فعال <span class="muted text-xs">هر مورد یک خط؛ ورودی صریح پزشک</span></label><textarea name="problems" rows="3" placeholder="مثال: کنترل نامناسب فشار خون">{% if current_document %}{{ current_document.problems|join('\n') }}{% endif %}</textarea></div>
      <div class="fld"><label>ارزیابی پزشک <span class="c-danger">*</span></label><textarea name="assessment" rows="4" placeholder="جمع‌بندی بالینی؛ برای امضا الزامی">{{ current_document.assessment if current_document else '' }}</textarea></div>
      <div class="fld"><label>طرح / برنامه <span class="c-danger">*</span></label><textarea name="plan" rows="4" placeholder="اقدام، درمان، آزمایش یا ارجاع؛ برای امضا الزامی">{{ current_document.plan if current_document else '' }}</textarea></div>
      <div class="fld"><label>دستور پیگیری برای تیم/بیمار</label><textarea name="followup_instructions" rows="2">{{ current_document.followup_instructions if current_document else '' }}</textarea></div>
      <div class="fld"><label>Outcome ویزیت <span class="c-danger">*</span></label><select name="outcome_code"><option value="">برای امضا انتخاب کنید</option>{% for code,label in outcome_labels.items() %}<option value="{{ code }}" {% if current_document and current_document.outcome_code==code %}selected{% endif %}>{{ label }}</option>{% endfor %}</select></div>
      <div class="flex items-center gap-2 wrap" style="margin-top:var(--s3);">
        <button class="btn btn-ghost" type="submit" name="action" value="draft"><svg class="icon"><use href="#i-save"></use></svg> ذخیره پیش‌نویس و شاخص‌ها</button>
        <button class="btn btn-ok" type="submit" name="action" value="sign" onclick="return confirm('سند امضا و Encounter تکمیل شود؟ اصلاح بعدی فقط با Amendment ثبت خواهد شد.');"><svg class="icon"><use href="#i-check"></use></svg> امضا و پایان ویزیت</button>
      </div>
    </div>
  </div>
</form>

<div class="card">
  <div class="section-title"><svg class="icon"><use href="#i-list-checks"></use></svg> اقدامات مکمل <span class="section-sub">Encounter را تکمیل نمی‌کنند</span></div>
  <div class="flex items-center gap-2 wrap">
    <a class="btn btn-ghost" href="{{ url_for('appointments.new_appointment', patient_link_id=pid) }}"><svg class="icon"><use href="#i-calendar"></use></svg> نوبت بعدی</a>
    <form class="m-0" method="post" action="{{ url_for('followups.add_manual') }}"><input type="hidden" name="patient_link_id" value="{{ pid }}"><input type="hidden" name="detail" value="پیگیری پس از ویزیت"><button class="btn btn-ghost" type="submit"><svg class="icon"><use href="#i-list-checks"></use></svg> ثبت پیگیری</button></form>
    <form class="m-0" method="post" action="{{ url_for('patients.prescription_free', pid=pid) }}" target="_blank"><button class="btn btn-ghost" type="submit"><svg class="icon"><use href="#i-clipboard"></use></svg> نسخه آزاد</button></form>
    <form method="post" action="{{ url_for('doctor_queue.invite', invoice_id=invoice_id) }}" class="visit-message-action"><select name="event_key" aria-label="نوع پیام پیگیری"><option value="lab_consult_invite">دعوت آزمایش و مشاوره</option><option value="bp_glucose_invite">یادآوری قند و فشار</option></select><button class="btn btn-ghost" type="submit"><svg class="icon"><use href="#i-megaphone"></use></svg> افزودن پیام به صف تأیید</button></form>
  </div>
</div>
{% endblock %}
''', encoding="utf-8")

# ---------------------------------------------------------------------------
# Signed document + append-only amendment page.
# ---------------------------------------------------------------------------
detail = ROOT / "specialist_clinic/src/templates/doctor_queue/document_detail.html"
detail.parent.mkdir(parents=True, exist_ok=True)
detail.write_text('''{% extends "base.html" %}
{% block title %}سند Encounter{% endblock %}
{% block content %}
<div class="crumb"><a href="{{ url_for('doctor_queue.index') }}">صف پزشک</a> / سند Encounter</div>
<div class="topbar"><div><h1><svg class="icon icon-lg"><use href="#i-clipboard"></use></svg> سند Encounter</h1><div class="muted text-sm">فاکتور #{{ invoice_id|fa_num }} · <code dir="ltr">{{ encounter.encounter_id }}</code> · نسخه جاری #{{ document.id|fa_num }}</div></div><a class="btn btn-ghost" href="{{ url_for('patients.detail', pid=encounter.patient_link_id) }}">پرونده بیمار</a></div>
<div class="alert-banner alert-info"><svg class="icon"><use href="#i-shield"></use></svg><span>نسخه‌های امضاشده overwrite نمی‌شوند. هر اصلاح، سند کامل جدید همراه دلیل و زنجیره supersede ثبت می‌کند.</span></div>

<div class="grid" style="grid-template-columns:minmax(0,1.3fr) minmax(280px,.7fr);gap:var(--s3);align-items:start;">
  <div class="card">
    <div class="section-title"><svg class="icon"><use href="#i-clipboard"></use></svg> نسخه جاری <span class="badge badge-ok">امضاشده</span></div>
    <dl class="record-dl">
      <dt>شکایت اصلی</dt><dd>{{ document.chief_complaint or '—' }}</dd>
      <dt>یافته‌های عینی</dt><dd style="white-space:pre-wrap;">{{ document.objective_findings or '—' }}</dd>
      <dt>مسائل فعال</dt><dd>{% for problem in document.problems %}<span class="chip">{{ problem }}</span>{% else %}—{% endfor %}</dd>
      <dt>ارزیابی</dt><dd style="white-space:pre-wrap;">{{ document.assessment }}</dd>
      <dt>طرح</dt><dd style="white-space:pre-wrap;">{{ document.plan }}</dd>
      <dt>دستور پیگیری</dt><dd style="white-space:pre-wrap;">{{ document.followup_instructions or '—' }}</dd>
      <dt>Outcome</dt><dd>{{ outcome_labels.get(document.outcome_code, document.outcome_code) }}</dd>
      <dt>نویسنده / زمان</dt><dd>{{ document.actor_username }} · {{ document.authored_at|jalali }}</dd>
      {% if document.amendment_reason %}<dt>دلیل اصلاحیه</dt><dd>{{ document.amendment_reason }}</dd>{% endif %}
    </dl>
  </div>
  <div class="card">
    <div class="section-title"><svg class="icon"><use href="#i-list-checks"></use></svg> تاریخچه نسخه‌ها</div>
    {% for item in history|reverse %}<div class="timeline-row"><span class="badge {% if item.document_status=='SIGNED' %}badge-ok{% else %}badge-muted{% endif %}">#{{ item.id|fa_num }}</span><div><b>{{ item.event_type }}</b><div class="muted text-xs">{{ item.actor_username }} · {{ item.recorded_at|jalali }}</div></div></div>{% endfor %}
  </div>
</div>

{% if permissions.get('clinical.document.amend') %}
<div class="card" id="amend-document">
  <div class="section-title"><svg class="icon"><use href="#i-edit"></use></svg> ثبت اصلاحیه</div>
  <form method="post" action="{{ url_for('doctor_queue.amend_document', invoice_id=invoice_id) }}">
    <input type="hidden" name="expected_current_event_id" value="{{ document.id }}">
    <div class="grid grid-2">
      <div class="fld"><label>شکایت اصلی</label><textarea name="chief_complaint" rows="2">{{ document.chief_complaint or '' }}</textarea></div>
      <div class="fld"><label>یافته‌های عینی</label><textarea name="objective_findings" rows="2">{{ document.objective_findings or '' }}</textarea></div>
    </div>
    <div class="fld"><label>مسائل فعال؛ هر خط یک مورد</label><textarea name="problems" rows="3">{{ document.problems|join('\n') }}</textarea></div>
    <div class="grid grid-2"><div class="fld"><label>ارزیابی *</label><textarea name="assessment" rows="4">{{ document.assessment }}</textarea></div><div class="fld"><label>طرح *</label><textarea name="plan" rows="4">{{ document.plan }}</textarea></div></div>
    <div class="grid grid-2"><div class="fld"><label>دستور پیگیری</label><textarea name="followup_instructions" rows="2">{{ document.followup_instructions or '' }}</textarea></div><div class="fld"><label>Outcome *</label><select name="outcome_code">{% for code,label in outcome_labels.items() %}<option value="{{ code }}" {% if document.outcome_code==code %}selected{% endif %}>{{ label }}</option>{% endfor %}</select></div></div>
    <div class="fld"><label>دلیل اصلاحیه *</label><textarea name="amendment_reason" rows="2" required placeholder="چه چیزی و چرا اصلاح شد؟"></textarea></div>
    <button class="btn" type="submit" onclick="return confirm('اصلاحیه به‌صورت نسخه جدید ثبت شود؟');"><svg class="icon"><use href="#i-save"></use></svg> ثبت نسخه اصلاح‌شده</button>
  </form>
</div>
{% endif %}
{% endblock %}
''', encoding="utf-8")

Path(__file__).unlink()

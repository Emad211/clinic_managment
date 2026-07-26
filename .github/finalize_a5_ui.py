from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A5 UI target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A5 UI anchor missing in {relative}: {old[:180]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Settings: never render raw secrets and never imply silent provider fallback.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/templates/manager/settings.html",
    '''            <div class="help">پیام‌ها از این پنل ارسال می‌شوند. اگر کلید پنل انتخاب‌شده خالی باشد، پنل دارای کلید معتبر استفاده می‌شود؛ بدون هیچ کلیدی ارسال متوقف می‌ماند.</div>
''',
    '''            <div class="help">پیام‌ها فقط از همین پنل ارسال می‌شوند. تغییر پنل روی استعلام پیام‌های قبلی اثر ندارد؛ هر پیام با سرویس‌دهندهٔ ثبت‌شدهٔ خودش بررسی می‌شود.</div>
''',
)
replace_once(
    "specialist_clinic/src/templates/manager/settings.html",
    '''            <input type="text" name="kavenegar_api_key" value="{{ data.kavenegar_api_key }}" placeholder="کلید API پنل کاوه‌نگار (در مسیرِ URL ارسال می‌شود)">
            <div class="help">کلیدِ دسترسیِ پنل کاوه‌نگار. در کاوه‌نگار کلید بخشی از مسیرِ آدرس است (نه هدر).</div>
''',
    '''            <input type="password" name="kavenegar_api_key" value="" autocomplete="new-password" placeholder="{% if data.kavenegar_api_key_set %}تنظیم شده — برای حفظ، خالی بگذارید{% else %}کلید API پنل کاوه‌نگار{% endif %}">
            <div class="help">
                {% if data.kavenegar_api_key_set %}<span class="badge badge-ok">تنظیم شده</span> <code dir="ltr">{{ data.kavenegar_api_key_masked }}</code>{% else %}<span class="badge badge-warn">تنظیم نشده</span>{% endif %}
                · در production از متغیر <code>CLINIC_KAVENEGAR_API_KEY</code> خوانده می‌شود و مقدار خام هرگز در صفحه نمایش داده نمی‌شود.
            </div>
            <label class="flex items-center gap-2 text-sm"><input type="checkbox" name="clear_kavenegar_api_key" value="1"> پاک‌کردن کلید ذخیره‌شدهٔ development</label>
''',
)
replace_once(
    "specialist_clinic/src/templates/manager/settings.html",
    '''            <input type="text" name="mediana_api_key" value="{{ data.mediana_api_key }}" placeholder="کلید API پنل مدیانا (هدر X-API-KEY)">
''',
    '''            <input type="password" name="mediana_api_key" value="" autocomplete="new-password" placeholder="{% if data.mediana_api_key_set %}تنظیم شده — برای حفظ، خالی بگذارید{% else %}کلید API پنل مدیانا{% endif %}">
            <div class="help">
                {% if data.mediana_api_key_set %}<span class="badge badge-ok">تنظیم شده</span> <code dir="ltr">{{ data.mediana_api_key_masked }}</code>{% else %}<span class="badge badge-warn">تنظیم نشده</span>{% endif %}
                · در production از <code>CLINIC_MEDIANA_API_KEY</code> خوانده می‌شود.
            </div>
            <label class="flex items-center gap-2 text-sm"><input type="checkbox" name="clear_mediana_api_key" value="1"> پاک‌کردن کلید ذخیره‌شدهٔ development</label>
''',
)

# ---------------------------------------------------------------------------
# Patient consent card: CARE and MARKETING are explicit independent streams.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/templates/patients/detail.html",
    '''{% if allergies %}
<div class="alert-banner alert-warn"><svg class="icon"><use href="#i-alert"></use></svg> آلرژی‌ها: {% for a in allergies %}{{ a.substance }}{% if a.severity %} ({{ a.severity }}){% endif %}{% if not loop.last %} · {% endif %}{% endfor %}</div>
{% endif %}

<!-- ============ TAB BAR ============ -->
''',
    '''{% if allergies %}
<div class="alert-banner alert-warn"><svg class="icon"><use href="#i-alert"></use></svg> آلرژی‌ها: {% for a in allergies %}{{ a.substance }}{% if a.severity %} ({{ a.severity }}){% endif %}{% if not loop.last %} · {% endif %}{% endfor %}</div>
{% endif %}

<section class="card card-soft" id="sms-consent" aria-labelledby="sms-consent-title">
    <div class="section-title">
        <svg class="icon"><use href="#i-bell"></use></svg>
        <div>
            <div id="sms-consent-title">رضایت پیامک</div>
            <div class="section-sub">پیام مراقبتی و پیام بازاریابی دو تصمیم مستقل و تاریخچه‌دار هستند.</div>
        </div>
    </div>
    <div class="grid grid-2 gap-3">
        {% for purpose in ['CARE','MARKETING'] %}
        {% set consent = sms_consent.get(purpose) %}
        <div class="card" style="margin:0;">
            <div class="flex items-center gap-2 wrap" style="justify-content:space-between;">
                <div>
                    <b>{{ consent.label }}</b>
                    <div class="muted text-xs">آخرین تغییر: {{ consent.recorded_at|jalali }}</div>
                </div>
                <span class="badge {% if consent.allowed %}badge-ok{% else %}badge-danger{% endif %}">
                    {{ 'مجاز' if consent.allowed else 'لغوشده' }}
                </span>
            </div>
            <div class="muted text-xs" style="margin-top:var(--s2);">منبع: {{ consent.source_code }}{% if consent.reason_code %} · دلیل: {{ consent.reason_code }}{% endif %}</div>
            {% if permissions.get('sms.consent.manage') %}
            <form method="post" action="{{ url_for('patients.sms_consent_update', pid=patient.id) }}" style="margin-top:var(--s3);">
                <input type="hidden" name="purpose" value="{{ purpose }}">
                <input type="hidden" name="decision" value="{{ 'REVOKED' if consent.allowed else 'GRANTED' }}">
                <input type="hidden" name="expected_current_event_id" value="{{ consent.id }}">
                <div class="row">
                    <div class="fld" style="flex:1;"><label>یادداشت</label><input name="note" placeholder="درخواست بیمار یا مستند تغییر"></div>
                    <button class="btn btn-sm {% if consent.allowed %}btn-danger{% else %}btn-ok{% endif %}" type="submit">
                        {{ 'لغو این نوع پیام' if consent.allowed else 'ثبت رضایت این نوع پیام' }}
                    </button>
                </div>
            </form>
            {% endif %}
        </div>
        {% endfor %}
    </div>
</section>

<!-- ============ TAB BAR ============ -->
''',
)

# ---------------------------------------------------------------------------
# Honest delivery report.
# ---------------------------------------------------------------------------
replace_once(
    "specialist_clinic/src/templates/sms/messages.html",
    '''    <div class="message-summary-item is-ok"><span>تحویل‌شده</span><strong>{{ summary.delivered|fa_num }}</strong></div>
    <div class="message-summary-item is-info"><span>در جریان</span><strong>{{ summary.in_flight|fa_num }}</strong></div>
''',
    '''    <div class="message-summary-item is-info"><span>پذیرفته‌شده توسط پنل</span><strong>{{ summary.accepted|fa_num }}</strong></div>
    <div class="message-summary-item is-ok"><span>تحویل‌شده به گیرنده</span><strong>{{ summary.delivered|fa_num }}</strong></div>
    <div class="message-summary-item is-info"><span>در جریان</span><strong>{{ summary.in_flight|fa_num }}</strong></div>
''',
)
replace_once(
    "specialist_clinic/src/templates/sms/messages.html",
    '''                        {% if m.source_type=='engagement' %}<span class="badge badge-info">یادآوری</span>
''',
    '''                        {% if m.sms_purpose=='CARE' %}<span class="badge badge-info">مراقبتی</span>{% elif m.sms_purpose=='MARKETING' %}<span class="badge badge-violet">بازاریابی</span>{% else %}<span class="badge badge-muted">قدیمی/طبقه‌بندی‌نشده</span>{% endif %}
                        {% if m.source_type=='engagement' %}<span class="badge badge-info">یادآوری</span>
''',
)

# ---------------------------------------------------------------------------
# Hub navigation hides surfaces the current user cannot use.
# ---------------------------------------------------------------------------
hub = target("specialist_clinic/src/templates/sms/_hub_tabs.html")
text = hub.read_text(encoding="utf-8")
text = text.replace(
    '''        <a class="btn btn-sm hub-nav-btn {% if hub_tab=='campaigns' %}btn{% else %}btn-ghost{% endif %}"''',
    '''        {% if permissions.get('sms.view') %}<a class="btn btn-sm hub-nav-btn {% if hub_tab=='campaigns' %}btn{% else %}btn-ghost{% endif %}"''',
    1,
)
text = text.replace(
    '''<svg class="icon icon-sm"><use href="#i-megaphone"></use></svg> کمپین‌ها</a>
''',
    '''<svg class="icon icon-sm"><use href="#i-megaphone"></use></svg> کمپین‌ها</a>{% endif %}
''',
    1,
)
text = text.replace(
    '''        <a class="btn btn-sm hub-nav-btn {% if hub_tab=='approvals' %}btn{% else %}btn-ghost{% endif %}"''',
    '''        {% if permissions.get('sms.view') %}<a class="btn btn-sm hub-nav-btn {% if hub_tab=='approvals' %}btn{% else %}btn-ghost{% endif %}"''',
    1,
)
text = text.replace(
    '''{% if hub_pending %} <span class="pill pill-danger">{{ hub_pending|fa_num }}</span>{% endif %}</a>
''',
    '''{% if hub_pending %} <span class="pill pill-danger">{{ hub_pending|fa_num }}</span>{% endif %}</a>{% endif %}
''',
    1,
)
text = text.replace(
    '''        <a class="btn btn-sm hub-nav-btn {% if hub_tab=='messages' %}btn{% else %}btn-ghost{% endif %}"''',
    '''        {% if permissions.get('sms.view') %}<a class="btn btn-sm hub-nav-btn {% if hub_tab=='messages' %}btn{% else %}btn-ghost{% endif %}"''',
    1,
)
text = text.replace(
    '''<svg class="icon icon-sm"><use href="#i-list-checks"></use></svg> گزارش تحویل</a>
''',
    '''<svg class="icon icon-sm"><use href="#i-list-checks"></use></svg> گزارش تحویل</a>{% endif %}
''',
    1,
)
hub.write_text(text, encoding="utf-8")

Path(__file__).unlink()

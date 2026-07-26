from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A6 visibility anchor missing in {relative}: {old[:180]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "specialist_clinic/src/api/sms.py",
    '''from src.security.permissions import Permission, permission_required
''',
    '''from src.security.permissions import Permission, has_permission, permission_required
''',
)
replace_once(
    "specialist_clinic/src/api/sms.py",
    '''        status_label=status_label,
        active_page='sms',
''',
    '''        status_label=status_label,
        show_economics=has_permission(Permission.SMS_CAMPAIGN_ECONOMICS_VIEW),
        active_page='sms',
''',
)
replace_once(
    "specialist_clinic/src/templates/sms/campaign_detail.html",
    '''<section class="card" id="campaign-economics">
''',
    '''{% if show_economics %}
<section class="card" id="campaign-economics">
''',
)
replace_once(
    "specialist_clinic/src/templates/sms/campaign_detail.html",
    '''</section>

<section class="card" id="campaign-responses">
''',
    '''</section>
{% endif %}

<section class="card" id="campaign-responses">
''',
)
replace_once(
    "specialist_clinic/src/templates/sms/campaign_detail.html",
    '''    'JOURNEY_ATTRIBUTION_REQUIRED':'پاسخ مثبت به Journey منتسب نشده است'
''',
    '''    'JOURNEY_ATTRIBUTION_REQUIRED':'پاسخ مثبت به Journey منتسب نشده است',
    'STALE_RESPONSE_ATTRIBUTION_REVIEW_REQUIRED':'پاسخ بیمار پس از انتساب اصلاح شده و انتساب نیازمند بازبینی است'
''',
)

Path(__file__).unlink()

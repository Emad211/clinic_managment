"""RTL/Jalali presentation filters (the product is Persian throughout).

- fa_num: Latin digits -> Persian digits (with thousands separators for numbers)
- jalali: a Gregorian date/datetime -> Jalali string (digits localised)
- rial: money (BIGINT Rial) -> grouped Persian digits + ﷼
"""

import datetime

import jdatetime
from django import template
from django.utils import timezone

register = template.Library()

_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


@register.filter
def fa_num(value):
    """Persian digits; integers/whole-number strings get thousands separators."""
    if value is None or value == "":
        return ""
    s = str(value)
    # group digits if it's a plain integer
    try:
        n = int(float(s)) if s.replace(",", "").replace(".0", "").lstrip("-").isdigit() else None
    except (ValueError, TypeError):
        n = None
    if n is not None and "." not in s:
        s = f"{n:,}"
    return s.translate(_FA)


@register.filter
def jalali(value, fmt="%Y/%m/%d"):
    """Render a Gregorian date/datetime as a Jalali string (Persian digits)."""
    if not value:
        return "—"
    if isinstance(value, datetime.datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        jd = jdatetime.datetime.fromgregorian(datetime=value.replace(tzinfo=None))
    elif isinstance(value, datetime.date):
        jd = jdatetime.date.fromgregorian(date=value)
    else:
        return str(value)
    return jd.strftime(fmt).translate(_FA)


@register.filter
def get_item(mapping, key):
    """Dict lookup by a variable key (templates can't do mapping[key])."""
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def rial(value):
    if value is None or value == "":
        return ""
    try:
        n = int(value)
    except (ValueError, TypeError):
        return str(value)
    return f"{n:,}".translate(_FA) + " ﷼"

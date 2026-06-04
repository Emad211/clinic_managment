from datetime import datetime, timedelta, timezone
from src.common.jalali import Gregorian, Persian

# Iran is UTC+3:30
IRAN_UTC_OFFSET = timedelta(hours=3, minutes=30)
IRAN_TZ = timezone(IRAN_UTC_OFFSET)


def iran_now() -> datetime:
    """Return current Tehran time as a naive datetime.

    The DB stores timestamps as Tehran local time (via SQLite
    `datetime('now', '+3 hours', '+30 minutes')` or via Python).
    Using `utcnow() + offset` avoids dependence on the OS timezone.
    """
    return datetime.utcnow() + IRAN_UTC_OFFSET


def parse_datetime(dt):
    """Parse a 'YYYY-MM-DD HH:MM:SS' / 'YYYY-MM-DD' string (or datetime) to datetime."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt
    if isinstance(dt, str):
        if not dt or dt == '—':
            return None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(dt[:len(fmt) + 2], fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(dt)
        except Exception:
            return None
    return None


def gregorian_to_jalali(gy: int, gm: int, gd: int):
    """Convert Gregorian date to Jalali (Persian) tuple."""
    return Gregorian(gy, gm, gd).persian_tuple()


def jalali_to_gregorian_str(jalali_str: str):
    """Convert a Jalali date string ('1404/09/05' or '1404-09-05') to 'YYYY-MM-DD'.

    Returns None on failure.
    """
    if not jalali_str:
        return None
    try:
        s = jalali_str.replace('/', '-')
        gy, gm, gd = Persian(s).gregorian_tuple()
        return f"{gy}-{gm:02d}-{gd:02d}"
    except Exception:
        return None


def format_jalali_datetime(dt, include_seconds: bool = False) -> str:
    """Format datetime (or string) as Jalali date+time string."""
    parsed = parse_datetime(dt)
    if parsed is None:
        return '—'
    jy, jm, jd = gregorian_to_jalali(parsed.year, parsed.month, parsed.day)
    if include_seconds:
        return f"{jy}/{jm:02d}/{jd:02d} {parsed.hour:02d}:{parsed.minute:02d}:{parsed.second:02d}"
    return f"{jy}/{jm:02d}/{jd:02d} {parsed.hour:02d}:{parsed.minute:02d}"


def format_jalali_date(dt) -> str:
    """Format datetime (or 'YYYY-MM-DD' string) as Jalali date only."""
    parsed = parse_datetime(dt)
    if parsed is None:
        return '—'
    jy, jm, jd = gregorian_to_jalali(parsed.year, parsed.month, parsed.day)
    return f"{jy}/{jm:02d}/{jd:02d}"


def today_str() -> str:
    """Today's Gregorian date as 'YYYY-MM-DD' (Iran time)."""
    return iran_now().strftime('%Y-%m-%d')


def add_months(d: datetime, months: int) -> datetime:
    """Add a number of months to a datetime (clamping day to month end)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    # clamp day
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return d.replace(year=year, month=month, day=day)

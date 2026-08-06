"""Default configurable engagement events for growth playbooks.

INSERT OR IGNORE preserves every manager edit after the first installation.
"""
from __future__ import annotations

import sqlite3


_GROWTH_EVENTS = (
    (
        "growth_no_show_recovery",
        "بازیابی عدم حضور",
        "operational",
        "sms",
        "سلام {name} عزیز، نوبت قبلی شما انجام نشد. برای هماهنگی نوبت جایگزین با کلینیک تماس بگیرید. {detail}",
        0,
        7,
        None,
        11,
    ),
    (
        "growth_cancellation_recovery",
        "جایگزینی نوبت لغوشده",
        "operational",
        "sms",
        "سلام {name} عزیز، برای تعیین زمان جایگزین نوبت لغوشده با کلینیک تماس بگیرید. {detail}",
        0,
        7,
        None,
        12,
    ),
    (
        "growth_inactive_recall",
        "بازگشت بیمار غیرفعال",
        "operational",
        "sms",
        "سلام {name} عزیز، مدتی از آخرین مراجعه شما گذشته است. برای ادامه مراقبت و تعیین نوبت با کلینیک تماس بگیرید.",
        0,
        60,
        None,
        61,
    ),
    (
        "growth_waitlist_auto_booked",
        "اطلاع نوبت خودکار صف انتظار",
        "operational",
        "sms",
        "سلام {name} عزیز، یک نوبت زودتر از صف انتظار برای شما ثبت شد: {detail}",
        0,
        1,
        None,
        9,
    ),
    (
        "growth_waitlist_offer",
        "پیشنهاد ظرفیت خالی",
        "operational",
        "sms",
        "سلام {name} عزیز، یک ظرفیت زودتر برای شما آزاد شده است: {detail} برای تأیید با کلینیک تماس بگیرید.",
        0,
        1,
        None,
        10,
    ),
)


def ensure_growth_message_events(db: sqlite3.Connection) -> None:
    db.executemany(
        """INSERT OR IGNORE INTO engagement_events
           (event_key,label,category,channel,sms_template,lead_days,
            cooldown_days,source_action,priority,is_active)
           VALUES (?,?,?,?,?,?,?,?,?,1)""",
        _GROWTH_EVENTS,
    )
    db.commit()


__all__ = ["ensure_growth_message_events"]

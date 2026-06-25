"""
Read-only projection for the public patient card — halqe (خوشهٔ J، قدم ۴۴).

پورتِ وفادار از specialist_clinic/src/services/card_projection_service.py به
Django/Postgres با تفاوت‌های ضروری:
  - دموگرافیک از accounting Port (نه patient_links — ADR-0007).
  - threshold evaluation از rule_engine._evaluate_reading (live clinical_indicators).
  - نوبتِ بعدی از clinical.appointments.
  - zero-write: فقط SELECT — هیچ INSERT/UPDATE/DELETE/commit.

امنیت (قفل‌شده با security-privacy-advisor):
  هرگز: national_id، شمارهٔ تماسِ بیمار، نامِ کامل دارو/دوز، تشخیص/بیماری،
  HbA1cِ خام، یادداشتِ بالینی، درآمد/کیف‌پول.

  داده‌های مجاز:
    - first_name: فقط نامِ کوچک (نه نامِ کامل) از accounting Port.
    - آخرین fbs/bp_systolic/bp_diastolic با status (از clinical_indicators).
    - نوبتِ بعدی: تاریخ + نوع (بدونِ یادداشتِ بالینی).
    - clinic_name: از settings (نه اطلاعاتِ بیمار).

پیش‌شرط:
  caller باید set_tenant_guc(tenant_id) را قبل از فراخوانی ست کرده باشد.
  این تضمین می‌کند RLS روی همهٔ queryها اعمال می‌شود.

LAN-vs-internet gate:
  این سرویس فقط دادهٔ لازم برای کارتِ LAN (QR/tablet) را برمی‌گرداند.
  Internet exposure نیازِ TLS + rate-limitِ توزیع‌شده دارد (هنوز فعال نیست).
"""
from __future__ import annotations

from django.db import connection
from django.utils import timezone as dj_timezone

from accounting_port.port import get_patients_by_ids as _get_patients_by_ids
from clinical.models import ClinicalIndicator, Appointment
from clinical.rule_engine import _evaluate_reading as _eval_reading

# ویتال‌هایِ مجاز روی کارت (ADR-0004 §6 — no raw HbA1c)
CARD_VITALS = ("fbs", "bp_systolic", "bp_diastolic")

# وضعیت → (متنِ فارسیِ ساده برای بیمار، کلاسِ CSS)
_STATUS = {
    "ok":     ("در محدودهٔ هدف", "ok"),
    "warn":   ("نیاز به پیگیری", "warn"),
    "danger": ("لطفاً همین امروز با کلینیک تماس بگیرید", "danger"),
}
_ORDER = {"ok": 0, "warn": 1, "danger": 2}

# label/unit برای ویتال‌ها (mirror از VITAL_TYPES در specialist_clinic)
_VITAL_META = {
    "fbs":          {"label": "قند ناشتا",        "unit": "mg/dL"},
    "bp_systolic":  {"label": "فشارِ سیستولیک",   "unit": "mmHg"},
    "bp_diastolic": {"label": "فشارِ دیاستولیک",  "unit": "mmHg"},
}


def _build_indicator_map() -> dict:
    """
    ساختنِ نقشهٔ clinical_indicators برای CARD_VITALS.

    GUC-scoped (RLS اعمال می‌شود — tenant درست است).
    فقط indicator_keyهایِ مرتبط با کارت را load می‌کند.
    """
    rows = list(
        ClinicalIndicator.objects.filter(
            key__in=CARD_VITALS,
        ).values(
            "key", "warn", "danger", "direction",
            "goal_low", "goal_high",
        )
    )
    return {r["key"]: r for r in rows}


def _latest_vitals_for_card(patient_link_id: int, tenant_id: int) -> dict:
    """
    آخرین مقدارِ هر ویتالِ مجاز را برمی‌گرداند.

    از clinical.vital_readings مستقیم (نه VIEW observations) تا از
    هر تغییرِ ساختارِ VIEW مستقل باشیم.
    GUC-scoped: RLS روی vital_readings اعمال می‌شود.

    Returns: dict[vtype → {value, unit, measured_at}]
    """
    result = {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (type)
                type, value, unit, measured_at
            FROM clinical.vital_readings
            WHERE patient_link_id = %s
              AND tenant_id = %s
              AND type = ANY(%s)
              AND verified = TRUE
            ORDER BY type, measured_at DESC
            """,
            [patient_link_id, tenant_id, list(CARD_VITALS)],
        )
        # slice13 safety gate: AND verified = TRUE
        # Patient self-report (verified=FALSE) must NEVER appear on the public card
        # until a physician verifies the reading (step 47).
        for row in cursor.fetchall():
            result[row[0]] = {
                "value": row[1],
                "unit": row[2],
                "measured_at": row[3],
            }
    return result


def _next_appointment(patient_link_id: int, tenant_id: int) -> dict | None:
    """
    نوبتِ آیندهٔ scheduled بیمار.

    GUC-scoped: RLS روی clinical.appointments اعمال می‌شود.
    فقط تاریخ + نوع — بدونِ یادداشتِ بالینی.
    Returns: {'scheduled_at': ISO, 'appt_type': str} یا None.
    """
    now = dj_timezone.now()
    try:
        appt = (
            Appointment.objects.filter(
                patient_link_id=patient_link_id,
                tenant_id=tenant_id,
                status="scheduled",
                scheduled_at__gte=now,
            )
            .order_by("scheduled_at")
            .values("scheduled_at", "appt_type")
            .first()
        )
    except Exception:
        appt = None

    if not appt:
        return None

    scheduled_at = appt["scheduled_at"]
    if hasattr(scheduled_at, "isoformat"):
        scheduled_at = scheduled_at.date().isoformat()

    return {
        "scheduled_at": scheduled_at,
        "appt_type": appt.get("appt_type") or "ویزیتِ کنترل",
    }


def card_for_patient(patient_link_id: int, tenant_id: int) -> dict | None:
    """
    پروجکشنِ read-only کارتِ عمومی برای یک بیمار.

    پیش‌شرط: GUC (app.current_tenant) باید به tenant_id ست شده باشد.
    Caller (endpoint) این کار را از طریقِ set_tenant_guc انجام داده است.

    Returns: dict یا None (بیمار پیدا نشد).

    قرارداد خروجی (قفل‌شده — frontend موازی همین را مصرف می‌کند):
    {
      "first_name": "...",
      "clinic_name": null | "...",
      "vitals": [
        {"key": "fbs", "label": "قند ناشتا", "value": 130,
         "unit": "mg/dL", "status": "warn"}
      ],
      "next_appointment": "2026-07-15" | null,
      "framing": "..."
    }

    هرگز: national_id، تماسِ بیمار، نامِ دارو/دوز، تشخیص/بیماری، HbA1cِ خام،
            یادداشتِ بالینی، درآمد/کیف‌پول.
    """
    # دموگرافیک از accounting Port (فقط first_name لازم است — نه نامِ کامل)
    # PatientLink در halqe national_id ندارد (ADR-0007) — باید از Port بگیریم.
    # ابتدا patient_id را از patient_links می‌خوانیم (GUC-scoped).
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT patient_id FROM clinical.patient_links "
            "WHERE id = %s AND tenant_id = %s",
            [patient_link_id, tenant_id],
        )
        row = cursor.fetchone()

    if not row:
        return None

    patient_id = row[0]
    demos = _get_patients_by_ids([patient_id])
    demo = demos[0] if demos else None

    # فقط نامِ کوچک (نه نامِ کامل، نه national_id)
    first_name = ""
    if demo:
        first_name = (demo.name or "").strip()
        # اگر full_name چند کلمه است، فقط اولین کلمه (نامِ کوچک)
        if demo.full_name:
            first_name = (demo.full_name.strip().split(" ") or [""])[0]

    # indicator map (برای evaluate_reading با live thresholds)
    indicator_map = _build_indicator_map()

    # آخرین ویتال‌های مجاز
    latest_vitals = _latest_vitals_for_card(patient_link_id, tenant_id)

    vitals_out = []
    worst = "ok"
    for vt in CARD_VITALS:
        reading = latest_vitals.get(vt)
        if not reading:
            continue
        level = _eval_reading(vt, reading["value"], indicator_map)
        if _ORDER[level] > _ORDER[worst]:
            worst = level
        meta = _VITAL_META.get(vt, {})
        vitals_out.append({
            "key": vt,
            "label": meta.get("label", vt),
            "value": reading["value"],
            "unit": meta.get("unit", reading.get("unit", "")),
            "status": level,
        })

    # نوبتِ بعدی
    next_appt = _next_appointment(patient_link_id, tenant_id)
    next_appointment_date = (
        next_appt["scheduled_at"] if next_appt else None
    )

    # framing: جملهٔ انگیزشی ساده (بدونِ اطلاعاتِ بالینی)
    framing = "وضعیتِ سلامتِ شما"
    if worst == "danger":
        framing = "لطفاً هرچه زودتر با کلینیک تماس بگیرید"
    elif worst == "warn":
        framing = "برخی از شاخص‌های شما نیاز به پیگیری دارند"

    # clinic_name: از settings اگر موجود است (fallback: None)
    clinic_name: str | None = None
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT value FROM platform.settings "
                "WHERE key = 'clinic_name' AND tenant_id = %s",
                [tenant_id],
            )
            r = cursor.fetchone()
            if r:
                clinic_name = r[0]
    except Exception:
        pass

    return {
        "first_name": first_name,
        "clinic_name": clinic_name,
        "vitals": vitals_out,
        "next_appointment": next_appointment_date,
        "framing": framing,
    }

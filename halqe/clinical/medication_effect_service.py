"""
clinical/medication_effect_service.py — ردیابیِ اثرِ دارو (Step 38, cluster I).

اصلِ مقدس: هرگز عددِ ساختگی — دادهٔ ناکافی ⇒ data_insufficient با دلیل.

منطق:
  1. resolve دارو + drug_class + start_date (404 اگر نبود)
  2. indicator = CLASS_TO_INDICATOR[drug_class]  (None → no_indicator_for_class)
  3. اگر start_date نال → no_start_date
  4. اگر زودتر از post_start روز از شروع → post_window_not_elapsed
  5. obs query در پنجرهٔ pre (start-180..start) و post (start+post_start..start+post_end)
  6. اگر n_pre=0 یا n_post=0 → data_insufficient
  7. mean(pre) / mean(post) / delta / direction_of_change
  8. caveat همیشه

پنجرهٔ pre همیشه: start_date - 180 روز  ..  start_date (ثابت برای همه)
پنجرهٔ post متغیر بر اساس indicator (EFFECT_WINDOWS).

فقط read-only: هیچ INSERT/UPDATE ندارد.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from django.utils import timezone as dj_timezone

from clinical.models import (
    PatientMedication,
    ClinicalIndicator,
    Observation,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tehran timezone offset — برای now() (UTC+3:30)
# ---------------------------------------------------------------------------
from datetime import timezone as _pytz
_TEHRAN_TZ = _pytz(timedelta(hours=3, minutes=30))


# ---------------------------------------------------------------------------
# CLASS_TO_INDICATOR — نگاشتِ drug_class → obs_key اندیکاتورِ اثرِ primary
# فقط کلیدهای تأییدشده‌ٔ موجود در clinical_indicators seed (slice2)
# ---------------------------------------------------------------------------
CLASS_TO_INDICATOR: dict[str, Optional[str]] = {
    # دیابت
    "metformin":       "hba1c",
    "sglt2i":          "hba1c",
    "glp1_ra":         "hba1c",
    "dual_gip_glp1":   "hba1c",
    "dpp4i":           "hba1c",
    "su":              "hba1c",
    "meglitinide":     "hba1c",
    "tzd":             "hba1c",
    "insulin_basal":   "hba1c",
    "insulin_bolus":   "hba1c",
    # لیپید
    "statin":          "ldl",
    "ezetimibe":       "ldl",
    "fibrate":         "triglyceride",  # اگر seed نشده → None بازمی‌گردد (بررسی در سرویس)
    # فشار خون
    "acei":            "bp_systolic",
    "arb":             "bp_systolic",
    "ccb":             "bp_systolic",
    "thiazide":        "bp_systolic",
    "beta_blocker":    "bp_systolic",
    "mra":             "bp_systolic",
    # کلیه / تیروئید
    "finerenone":      "uacr",
    "thyroid_agent":   "tsh",
    "antithyroid":     "tsh",
    # اثرِ مستقیمِ قابل‌ردیابی ندارند → None ⇒ no_indicator_for_class
    "aspirin":         None,
    "other":           None,
    "loop_diuretic":   None,
}

# ---------------------------------------------------------------------------
# EFFECT_WINDOWS — روز؛ pre همیشه 180..0 قبلِ start، post = (post_start, post_end)
# ---------------------------------------------------------------------------
_PRE_WINDOW_DAYS = 180   # همیشه ثابت

EFFECT_WINDOWS: dict[str, tuple[int, int]] = {
    "hba1c":       (60, 180),
    "fbs":         (14, 180),
    "bp_systolic": (14, 180),
    "bp_diastolic":(14, 180),
    "ldl":         (30, 180),
    "triglyceride":(30, 180),
    "egfr":        (90, 365),
    "uacr":        (90, 365),
    "tsh":         (42, 365),
}
_DEFAULT_WINDOW = (30, 180)

# ---------------------------------------------------------------------------
# MEANINGFUL_THRESHOLD — MCID (کمترینِ تغییرِ بالینیِ معنادار)
# ---------------------------------------------------------------------------
MEANINGFUL_THRESHOLD: dict[str, float] = {
    "hba1c":       0.5,
    "ldl":         15.0,
    "triglyceride":50.0,
    "bp_systolic": 5.0,
    "bp_diastolic":5.0,
    "fbs":         10.0,
    "egfr":        5.0,
    "tsh":         0.5,
    # uacr: کاهشِ نسبیِ ۳۰٪ — مقدار absolute threshold را 0 می‌گذاریم و جداگانه بررسی می‌کنیم
}
_UACR_RELATIVE_THRESHOLD = 0.30   # 30% کاهشِ نسبی


# ---------------------------------------------------------------------------
# آمارِ ساده
# ---------------------------------------------------------------------------
def _mean(vals: list[float]) -> Optional[float]:
    if not vals:
        return None
    return sum(vals) / len(vals)


def _round2(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    return round(v, 2)


# ---------------------------------------------------------------------------
# تابعِ اصلیِ سرویس
# ---------------------------------------------------------------------------
def compute_medication_effect(
    med: PatientMedication,
    tenant_id: int,
) -> dict:
    """
    محاسبهٔ اثرِ دارو با مقایسهٔ pre/post observation.

    Parameters
    ----------
    med : PatientMedication — دارویِ resolve‌شده (باید برای این tenant/patient باشد)
    tenant_id : int

    Returns
    -------
    dict با کلیدهای کاملِ DTO (هم ok و هم data_insufficient)
    """
    now_date = dj_timezone.now().astimezone(_TEHRAN_TZ).date()

    # ── ۱. start_date ────────────────────────────────────────────────────────
    start_date: Optional[date] = med.start_date
    if start_date is None:
        return _insufficient(
            med, reason="no_start_date", now_date=now_date, tenant_id=tenant_id
        )

    # ── ۲. drug_class → indicator ────────────────────────────────────────────
    drug_class: Optional[str] = med.drug_class
    if not drug_class or drug_class not in CLASS_TO_INDICATOR:
        return _insufficient(
            med, reason="no_indicator_for_class", now_date=now_date,
            start_date=start_date, tenant_id=tenant_id
        )

    indicator_key = CLASS_TO_INDICATOR[drug_class]
    if indicator_key is None:
        return _insufficient(
            med, reason="no_indicator_for_class", now_date=now_date,
            start_date=start_date, tenant_id=tenant_id
        )

    # ── ۳. تأیید که indicator_key در DB seed شده ─────────────────────────────
    try:
        ind_obj = ClinicalIndicator.objects.get(
            tenant_id=tenant_id, key=indicator_key, is_active=True
        )
    except ClinicalIndicator.DoesNotExist:
        # کلیدِ indicator در DB این tenant نیست (مثلاً triglyceride seed نشده)
        return _insufficient(
            med, reason="no_indicator_for_class", now_date=now_date,
            start_date=start_date, tenant_id=tenant_id
        )

    # ── ۴. پنجرهٔ زمانی ────────────────────────────────────────────────────
    post_start_days, post_end_days = EFFECT_WINDOWS.get(indicator_key, _DEFAULT_WINDOW)
    days_since_start = (now_date - start_date).days

    if days_since_start < post_start_days:
        return _insufficient(
            med, reason="post_window_not_elapsed", now_date=now_date,
            start_date=start_date, indicator_key=indicator_key,
            ind_obj=ind_obj, post_start_days=post_start_days, tenant_id=tenant_id
        )

    # ── ۵. Query observations ────────────────────────────────────────────────
    # obs_key format (slice4a): 'vital:<type>' for vitals, 'lab:<key>' for labs
    # ما هر دو namespace را می‌پذیریم
    obs_key_vital = f"vital:{indicator_key}"
    obs_key_lab   = f"lab:{indicator_key}"

    pre_start  = start_date - timedelta(days=_PRE_WINDOW_DAYS)
    pre_end    = start_date  # exclusive: قبل از شروعِ دارو
    post_start = start_date + timedelta(days=post_start_days)
    post_end   = start_date + timedelta(days=post_end_days)

    # pre: از (start-180) تا start (exclusive)
    pre_qs = Observation.objects.filter(
        tenant_id=tenant_id,
        patient_link_id=med.patient_link_id,
        obs_key__in=[obs_key_vital, obs_key_lab],
        observed_at__date__gte=pre_start,
        observed_at__date__lt=pre_end,
        value__isnull=False,
    ).values_list("value", flat=True)

    # post: از (start+post_start_days) تا (start+post_end_days) inclusive
    post_qs = Observation.objects.filter(
        tenant_id=tenant_id,
        patient_link_id=med.patient_link_id,
        obs_key__in=[obs_key_vital, obs_key_lab],
        observed_at__date__gte=post_start,
        observed_at__date__lte=post_end,
        value__isnull=False,
    ).values_list("value", flat=True)

    pre_vals  = [float(v) for v in pre_qs  if v is not None]
    post_vals = [float(v) for v in post_qs if v is not None]
    n_pre  = len(pre_vals)
    n_post = len(post_vals)

    if n_pre == 0 or n_post == 0:
        reason = "no_pre" if n_pre == 0 else "no_post"
        if n_pre == 0 and n_post == 0:
            reason = "no_pre"   # اولویت
        return _insufficient(
            med, reason=reason, now_date=now_date,
            start_date=start_date, indicator_key=indicator_key,
            ind_obj=ind_obj,
            n_pre=n_pre, n_post=n_post,
            pre_start=pre_start, pre_end=pre_end,
            post_start=post_start, post_end=post_end,
            tenant_id=tenant_id,
        )

    # ── ۶. محاسبه ────────────────────────────────────────────────────────────
    pre_value  = _mean(pre_vals)
    post_value = _mean(post_vals)
    delta      = round(post_value - pre_value, 2)

    direction_of_change = _classify_direction(
        indicator_key=indicator_key,
        delta=delta,
        ind_obj=ind_obj,
        pre_value=pre_value,
        post_value=post_value,
    )

    # caveat همیشه حاضر
    caveat = _build_caveat(n_pre=n_pre, n_post=n_post)

    threshold = MEANINGFUL_THRESHOLD.get(indicator_key)

    return {
        "status": "ok",
        "reason": None,
        "suggestion_only": True,
        "drug_name": med.drug_name,
        "drug_class": drug_class,
        "indicator": ind_obj.label,
        "indicator_key": indicator_key,
        "unit": ind_obj.unit,
        "pre_value": _round2(pre_value),
        "post_value": _round2(post_value),
        "delta": _round2(delta),
        "direction_of_change": direction_of_change,
        "n_pre": n_pre,
        "n_post": n_post,
        "pre_window": {
            "from": str(pre_start),
            "to":   str(pre_end - timedelta(days=1)),  # inclusive display
        },
        "post_window": {
            "from": str(post_start),
            "to":   str(post_end),
        },
        "start_date":    str(start_date),
        "caveat": caveat,
        "meaningful_threshold": threshold,
    }


# ---------------------------------------------------------------------------
# تابعِ کمکی — ساختِ پاسخِ data_insufficient
# ---------------------------------------------------------------------------
def _insufficient(
    med: PatientMedication,
    reason: str,
    now_date: date,
    start_date: Optional[date] = None,
    indicator_key: Optional[str] = None,
    ind_obj=None,
    post_start_days: int = 0,
    n_pre: int = 0,
    n_post: int = 0,
    pre_start: Optional[date] = None,
    pre_end: Optional[date] = None,
    post_start: Optional[date] = None,
    post_end: Optional[date] = None,
    tenant_id: int = 1,
) -> dict:
    """پاسخِ data_insufficient استاندارد — همهٔ فیلدها حاضر، null‌ها صریح."""
    # اگر pre/post window هنوز محاسبه نشده ولی indicator و start_date داریم
    if start_date and indicator_key and pre_start is None:
        ps, pe = EFFECT_WINDOWS.get(indicator_key, _DEFAULT_WINDOW)
        pre_start  = start_date - timedelta(days=_PRE_WINDOW_DAYS)
        pre_end    = start_date
        post_start = start_date + timedelta(days=ps)
        post_end   = start_date + timedelta(days=pe)

    indicator_label = ind_obj.label if ind_obj else None
    unit = ind_obj.unit if ind_obj else None
    threshold = MEANINGFUL_THRESHOLD.get(indicator_key) if indicator_key else None

    return {
        "status": "data_insufficient",
        "reason": reason,
        "suggestion_only": True,
        "drug_name": med.drug_name,
        "drug_class": med.drug_class,
        "indicator": indicator_label,
        "indicator_key": indicator_key,
        "unit": unit,
        "pre_value": None,
        "post_value": None,
        "delta": None,
        "direction_of_change": None,
        "n_pre": n_pre,
        "n_post": n_post,
        "pre_window": {
            "from": str(pre_start) if pre_start else None,
            "to":   str(pre_end - timedelta(days=1)) if pre_end else None,
        } if pre_start else None,
        "post_window": {
            "from": str(post_start) if post_start else None,
            "to":   str(post_end)   if post_end   else None,
        } if post_start else None,
        "start_date":    str(start_date) if start_date else None,
        "caveat": None,
        "meaningful_threshold": threshold,
    }


# ---------------------------------------------------------------------------
# direction_of_change — طبقه‌بندیِ جهتِ تغییر
# ---------------------------------------------------------------------------
def _classify_direction(
    indicator_key: str,
    delta: float,
    ind_obj,
    pre_value: float,
    post_value: float,
) -> str:
    """
    تعیینِ direction_of_change بر اساسِ delta و ind_obj.direction.

    direction=high  → مقدارِ بالاتر بدتر است:
        delta < -threshold → improved (کاهش = بهبود)
        delta > +threshold → worsened (افزایش = بدتر)
        else               → unchanged

    direction=low   → مقدارِ پایین‌تر بدتر است (مثل eGFR):
        delta > +threshold → improved (افزایش = بهبود)
        delta < -threshold → worsened (کاهش = بدتر)
        else               → unchanged

    uacr: ارزیابیِ نسبی (30٪ کاهش = بهبود)؛ threshold absolute ملاک نیست
    tsh: هدف‌محدوده (0.4–4.0)؛ اگر مبهم → unchanged + delta ارائه می‌شود
    """
    threshold = MEANINGFUL_THRESHOLD.get(indicator_key)
    direction = getattr(ind_obj, "direction", "high") or "high"

    # uacr: کاهشِ نسبیِ ۳۰٪
    if indicator_key == "uacr":
        if pre_value and pre_value > 0:
            relative_change = (post_value - pre_value) / pre_value
            if relative_change <= -_UACR_RELATIVE_THRESHOLD:
                return "improved"
            elif relative_change >= _UACR_RELATIVE_THRESHOLD:
                return "worsened"
            else:
                return "unchanged"
        return "unchanged"

    # tsh: هدف‌محدوده‌ای
    if indicator_key == "tsh":
        goal_low  = getattr(ind_obj, "goal_low",  0.4) or 0.4
        goal_high = getattr(ind_obj, "goal_high", 4.0) or 4.0
        pre_in  = goal_low <= pre_value  <= goal_high
        post_in = goal_low <= post_value <= goal_high
        if post_in and not pre_in:
            return "improved"
        elif pre_in and not post_in:
            return "worsened"
        # هر دو در محدوده یا هر دو خارج — گزارشِ delta بدونِ ادعای قوی
        return "unchanged"

    # سایرِ indicatorها — بر اساسِ threshold absolute
    if threshold is None:
        return "unchanged"

    abs_delta = abs(delta)
    if abs_delta < threshold:
        return "unchanged"

    if direction == "high":
        return "improved" if delta < 0 else "worsened"
    else:  # direction == "low"
        return "improved" if delta > 0 else "worsened"


# ---------------------------------------------------------------------------
# caveat — همیشه حاضر در حالتِ ok
# ---------------------------------------------------------------------------
def _build_caveat(n_pre: int, n_post: int) -> str:
    base = (
        "مطالعهٔ تک‌گروهیِ پیش/پس؛ تغییر ممکن است ناشی از عواملِ همزمان، "
        "سبک‌زندگی، یا regression-to-mean باشد — نه اثباتِ علّیت."
    )
    if n_pre == 1 or n_post == 1:
        base += (
            f" تعدادِ اندازه‌گیری کم است (pre={n_pre}، post={n_post})"
            " — نتیجه‌گیریِ قوی توصیه نمی‌شود."
        )
    return base

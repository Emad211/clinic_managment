"""
clinical/outcome_trend_service.py — دو متریکِ توصیفیِ آنالیتیکسِ مدیر (Step 50, cluster K).

اصلِ مقدس (clinical-data-scientist، قفل‌شده — همان روحِ cohort_outcome_service):
  - on-the-fly، read-only مطلق، بدونِ slice/migration (مشتق از داده‌های موجود).
  - NULL نه عددِ ساختگی: مخرجِ کوچک (< min_n) → نرخ None، هرگز صفر/impute.
  - هیچ ادعای علّی: framing همیشه حاضر و غیرعلّی.
  - verified=True برای رویدادهای vital (هم lapsed-return هم control-trend).
  - GUC-scoped (tenant از پارامتر؛ RLS اعمال می‌شود). فقط read.

این ماژول دو تابعِ مستقل دارد:

  ۱) lapsed_return(tenant_id)
     نرخِ بازگشتِ کوهورتِ lapsed، با مرجعِ زمانیِ بسته (closed-window) برای رفعِ
     immortal-time/survivorship bias.

       «رویدادِ معنادار» (meaningful contact) = اجتماعِ:
         - Appointment با status='done'           (scheduled_at)
         - vital_readings با verified=TRUE          (measured_at)
         - FollowupTask با status='done'            (created_at)
       ⚠️ خروجیِ SMS/recall عمداً شامل نمی‌شود (tautology: «ما تماس گرفتیم پس برگشت»).

       T0 = now - 240d   (240 = lapse_window 120 + return_window 120 → پنجره کاملاً سپری).
       مخرج (lapsed cohort): بیمارانِ activeِ این tenant که
         (الف) حداقل یک رویدادِ معنادار پیش از T0 دارند، و
         (ب) آخرین رویدادِ پیش از T0 ≤ T0-120d است (یعنی در زمانِ T0، ۱۲۰+ روز بی‌رویداد).
       صورت (returned): از همان مخرج، آن‌ها که ≥۱ رویدادِ معنادار در (T0, T0+120d] دارند.
       return_rate = returned/denominator؛ NULL اگر denominator < 30.

  ۲) control_trend(tenant_id)
     ۱۲ باکتِ ماهانهٔ اخیر، per-condition + یک سریِ "all". برای هر ماه و هر بیمارِ active،
     آخرین قرائتِ verified هر vitalِ کنترلی با measured_at ≤ پایانِ ماه (as-of) طبقه‌بندیِ
     control می‌شود (uncontrolled/borderline/controlled/unknown). مخرج = assessable
     (هر باکت، بیمارانی با ≥۱ قرائت تا آن لحظه؛ unknown خارج)؛ صورت = controlled.
     pct_controlled = controlled/assessable؛ NULL اگر assessable < 30.
     ترکیبِ بیمارانِ هر ماه متفاوت است → secular trend، نه اثرِ مداخله.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from django.db import connection as _conn
from django.utils import timezone

from clinical.models import (
    PatientLink,
    PatientCondition,
    Condition,
    ClinicalIndicator,
)
from clinical.rule_engine import _evaluate_reading


# ---------------------------------------------------------------------------
# پارامترهای آماری — قفل‌شده با data-scientist
# ---------------------------------------------------------------------------
N_SUFFICIENT = 30                # حداقلِ denominator/assessable برای محاسبهٔ نرخ

LAPSE_WINDOW_DAYS = 120          # ۱۲۰+ روز بی‌رویداد در زمانِ T0 → lapsed
RETURN_WINDOW_DAYS = 120         # پنجرهٔ پسِ T0 برای شمارشِ بازگشت
T0_OFFSET_DAYS = LAPSE_WINDOW_DAYS + RETURN_WINDOW_DAYS   # 240 — closed-window

TREND_BUCKETS = 12               # تعدادِ باکت‌های ماهانه

# کلیدهای vitalِ کنترلی (بدونِ namespace prefix) — همان مجموعهٔ control_room_service.
# control-trend بیمار را بر اساسِ این‌ها طبقه‌بندی می‌کند.
CONTROL_VITALS = ["hba1c", "fbs", "bp_systolic", "bp_diastolic", "ldl", "egfr", "uacr"]

# conditionهایی که در control-trend per-condition گزارش می‌شوند (+ سریِ "all").
TREND_CONDITIONS = ["diabetes", "hypertension", "hyperlipidemia", "ckd", "thyroid"]


_LAPSED_FRAMING = (
    "نمای توصیفی بدونِ گروهِ کنترل؛ بازگشت می‌تواند ناشی از عواملِ بیرونی باشد "
    "(فصل، دارو، ارجاعِ بیرونی) نه اثرِ اقدامِ ما. مرجعِ زمانیِ بسته (T0=−۲۴۰روز) "
    "برای رفعِ سوگیریِ immortal-time/survivorship به‌کار رفته؛ تفسیرِ علّی مجاز نیست."
)

_TREND_FRAMING = (
    "روندِ زمانیِ توصیفی؛ ترکیبِ بیمارانِ هر ماه متفاوت است (هم‌گروهِ ثابت نیست) — "
    "این یک secular trend است نه اثرِ مداخله. as-of آخرین قرائتِ verified تا پایانِ "
    "هر ماه؛ تفسیرِ علّی مجاز نیست."
)


# ---------------------------------------------------------------------------
# کمکی: indicator map (live thresholds) + condition→control-vitals map
# ---------------------------------------------------------------------------
def _indicator_map(tenant_id: int) -> dict:
    """{bare_key: ClinicalIndicator} برای indicatorهای فعالِ این tenant."""
    return {
        row.key: row
        for row in ClinicalIndicator.objects.filter(
            tenant_id=tenant_id, is_active=True
        )
    }


def _condition_vitals_map(indicator_map: dict) -> dict[str, list[str]]:
    """
    نگاشتِ condition_code → لیستِ vitalهای کنترلیِ مربوط، از clinical_indicators.conditions
    (comma-separated codes یا 'all'). فقط کلیدهای داخلِ CONTROL_VITALS لحاظ می‌شوند.

    'all' در indicator.conditions یعنی این vital برای همهٔ conditionها کنترلی است.
    """
    out: dict[str, list[str]] = {c: [] for c in TREND_CONDITIONS}
    for key in CONTROL_VITALS:
        ind = indicator_map.get(key)
        # وقتی indicator row غایب است، با fallbackِ rule_engine ارزیابی می‌شود؛
        # برای نگاشتِ condition آن را به diabetes/hypertension نسبت نمی‌دهیم مگر
        # اطلاعِ صریح. بدونِ indicator row → فقط در سریِ "all" دیده می‌شود.
        conds_raw = (getattr(ind, "conditions", None) or "").strip() if ind else ""
        if conds_raw == "" or conds_raw.lower() == "all":
            for c in TREND_CONDITIONS:
                out[c].append(key)
            continue
        codes = {p.strip() for p in conds_raw.split(",") if p.strip()}
        for c in TREND_CONDITIONS:
            if c in codes:
                out[c].append(key)
    return out


# ---------------------------------------------------------------------------
# ۱) lapsed_return — نرخِ بازگشتِ کوهورتِ lapsed (closed-window)
# ---------------------------------------------------------------------------
def lapsed_return(tenant_id: int) -> dict:
    """
    نرخِ بازگشتِ کوهورتِ lapsed برای یک tenant.

    Returns
    -------
    {
      denominator       : int          — کوهورتِ lapsed در زمانِ T0
      returned          : int          — از مخرج، آن‌ها که در (T0, T0+120d] بازگشتند
      return_rate       : float | null — returned/denominator (درصد ۱ رقم)؛ NULL اگر <min_n
      lapse_window_days : int          — 120
      return_window_days: int          — 120
      min_n             : int          — 30
      framing           : str          — غیرعلّی، همیشه
    }
    """
    now = timezone.now()
    t0 = now - timedelta(days=T0_OFFSET_DAYS)
    lapse_cut = t0 - timedelta(days=LAPSE_WINDOW_DAYS)
    return_end = t0 + timedelta(days=RETURN_WINDOW_DAYS)

    # active link ids برای این tenant
    link_ids = list(
        PatientLink.objects.filter(
            tenant_id=tenant_id, is_active=True
        ).values_list("id", flat=True)
    )

    result = {
        "denominator": 0,
        "returned": 0,
        "return_rate": None,
        "lapse_window_days": LAPSE_WINDOW_DAYS,
        "return_window_days": RETURN_WINDOW_DAYS,
        "min_n": N_SUFFICIENT,
        "framing": _LAPSED_FRAMING,
    }
    if not link_ids:
        return result

    # «رویدادِ معنادار» per بیمار = اجتماعِ سه منبع. روی همان لینک‌ها، tenant-scoped.
    # برای هر بیمار دو عدد لازم است:
    #   last_before_t0  = MAX(event_at) که event_at < T0
    #   has_return      = آیا EXISTS رویدادی در (T0, T0+120d]
    # یک کوئریِ مجموعه‌ایِ set-based با UNION ALL از سه منبع، سپس GROUP BY.
    #
    # ⚠️ SMS/recall عمداً غایب است — منبعِ بازگشت نباید tautology بسازد.
    # ⚠️ vital فقط verified=TRUE.
    sql = """
        WITH events AS (
            -- Appointment done → scheduled_at
            SELECT a.patient_link_id AS plid, a.scheduled_at AS event_at
            FROM   clinical.appointments a
            WHERE  a.tenant_id = %(tid)s
              AND  a.patient_link_id = ANY(%(links)s)
              AND  a.status = 'done'
              AND  a.scheduled_at IS NOT NULL
            UNION ALL
            -- verified vital reading → measured_at
            SELECT v.patient_link_id AS plid, v.measured_at AS event_at
            FROM   clinical.vital_readings v
            WHERE  v.tenant_id = %(tid)s
              AND  v.patient_link_id = ANY(%(links)s)
              AND  v.verified = TRUE
              AND  v.measured_at IS NOT NULL
            UNION ALL
            -- followup task done → created_at
            SELECT f.patient_link_id AS plid, f.created_at AS event_at
            FROM   clinical.followup_tasks f
            WHERE  f.tenant_id = %(tid)s
              AND  f.patient_link_id = ANY(%(links)s)
              AND  f.status = 'done'
              AND  f.created_at IS NOT NULL
        ),
        per_patient AS (
            SELECT
                plid,
                MAX(event_at) FILTER (WHERE event_at < %(t0)s)                              AS last_before_t0,
                BOOL_OR(event_at > %(t0)s AND event_at <= %(return_end)s)                   AS has_return
            FROM events
            GROUP BY plid
        )
        SELECT
            COUNT(*) FILTER (
                WHERE last_before_t0 IS NOT NULL
                  AND last_before_t0 <= %(lapse_cut)s
            ) AS denominator,
            COUNT(*) FILTER (
                WHERE last_before_t0 IS NOT NULL
                  AND last_before_t0 <= %(lapse_cut)s
                  AND has_return
            ) AS returned
        FROM per_patient
    """
    params = {
        "tid": tenant_id,
        "links": link_ids,
        "t0": t0,
        "return_end": return_end,
        "lapse_cut": lapse_cut,
    }
    with _conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()

    denominator = int(row[0] or 0)
    returned = int(row[1] or 0)

    result["denominator"] = denominator
    result["returned"] = returned
    if denominator >= N_SUFFICIENT:
        result["return_rate"] = round(returned * 100.0 / denominator, 1)
    # else: return_rate بماند None — NULL نه صفر

    return result


# ---------------------------------------------------------------------------
# ۲) control_trend — ۱۲ باکتِ ماهانه، per-condition + "all"
# ---------------------------------------------------------------------------
def _month_buckets(now) -> list[dict]:
    """
    ۱۲ باکتِ ماهانهٔ اخیر (شاملِ ماهِ جاری). هر باکت {ym, end} که end لحظهٔ
    «ابتدای ماهِ بعد» است (as-of cutoff اکیداً قبل از end).
    ym برچسبِ 'YYYY-MM' میلادیِ ماهِ باکت است (بک‌اند ISO؛ نمایشِ جلالی در UI).
    """
    # ابتدای ماهِ جاری
    first_of_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    buckets: list[dict] = []
    cursor = first_of_this
    for _ in range(TREND_BUCKETS):
        # end باکت = ابتدای ماهِ بعد از cursor
        if cursor.month == 12:
            nxt = cursor.replace(year=cursor.year + 1, month=1)
        else:
            nxt = cursor.replace(month=cursor.month + 1)
        buckets.append({"ym": f"{cursor.year:04d}-{cursor.month:02d}", "end": nxt})
        # یک ماه عقب برو
        if cursor.month == 1:
            cursor = cursor.replace(year=cursor.year - 1, month=12)
        else:
            cursor = cursor.replace(month=cursor.month - 1)
    buckets.reverse()   # قدیمی‌ترین اول
    return buckets


def control_trend(tenant_id: int) -> dict:
    """
    روندِ ماهانهٔ ٪کنترل، per-condition + سریِ "all".

    Returns
    -------
    {
      buckets : [
        {ym:'YYYY-MM', condition:str, assessable_n:int, controlled_n:int,
         pct_controlled: float|null},
        ...
      ]
      min_n   : int    — 30
      framing : str    — غیرعلّی، همیشه
    }
    """
    now = timezone.now()
    buckets = _month_buckets(now)

    result = {
        "buckets": [],
        "min_n": N_SUFFICIENT,
        "framing": _TREND_FRAMING,
    }

    indicator_map = _indicator_map(tenant_id)
    cond_vitals = _condition_vitals_map(indicator_map)

    # active links + conditionهای فعالِ هر بیمار
    active_link_ids = list(
        PatientLink.objects.filter(
            tenant_id=tenant_id, is_active=True
        ).values_list("id", flat=True)
    )
    if not active_link_ids:
        # حتی بدونِ بیمار، شکلِ کامل را برگردان: ۱۲*۶ باکت با assessable_n=0, pct=null
        for b in buckets:
            for cond in (TREND_CONDITIONS + ["all"]):
                result["buckets"].append({
                    "ym": b["ym"],
                    "condition": cond,
                    "assessable_n": 0,
                    "controlled_n": 0,
                    "pct_controlled": None,
                })
        return result

    # condition code → set(plid)  برای فیلترِ per-condition
    cond_code_by_id: dict[int, str] = {
        c.id: c.code
        for c in Condition.objects.filter(tenant_id=tenant_id, is_active=True)
        if c.code in TREND_CONDITIONS
    }
    plids_by_condition: dict[str, set[int]] = {c: set() for c in TREND_CONDITIONS}
    for r in PatientCondition.objects.filter(
        tenant_id=tenant_id,
        patient_link_id__in=active_link_ids,
        is_active=True,
        condition_id__in=list(cond_code_by_id.keys()) or [-1],
    ).values("patient_link_id", "condition_id"):
        code = cond_code_by_id.get(r["condition_id"])
        if code:
            plids_by_condition[code].add(r["patient_link_id"])

    # تمامِ قرائت‌های verifiedِ کنترلی را یک‌بار بخوان (set-based؛ بدونِ per-month per-patient query).
    # سپس in-memory as-of را برای هر باکت محاسبه می‌کنیم.
    # ساختار: rows = [(plid, bare_key, value, observed_at), ...] مرتب بر اساس observed_at.
    control_obs_keys = (
        [f"vital:{k}" for k in CONTROL_VITALS]
        + [f"lab:{k}" for k in CONTROL_VITALS]
    )
    rows: list[tuple] = []
    with _conn.cursor() as cur:
        cur.execute(
            """
            SELECT patient_link_id, obs_key, value, observed_at
            FROM   clinical.observations
            WHERE  tenant_id = %(tid)s
              AND  patient_link_id = ANY(%(links)s)
              AND  obs_key = ANY(%(keys)s)
              AND  value IS NOT NULL
              AND  verified = TRUE
            ORDER  BY patient_link_id, observed_at
            """,
            {
                "tid": tenant_id,
                "links": active_link_ids,
                "keys": control_obs_keys,
            },
        )
        for plid, obs_key, value, observed_at in cur.fetchall():
            if obs_key.startswith("vital:"):
                bare = obs_key[len("vital:"):]
            elif obs_key.startswith("lab:"):
                bare = obs_key[len("lab:"):]
            else:
                bare = obs_key
            if bare not in CONTROL_VITALS:
                continue
            rows.append((plid, bare, value, observed_at))

    # readings_by_patient[plid] = list[(observed_at, bare_key, value)] مرتب صعودی
    readings_by_patient: dict[int, list[tuple]] = {}
    for plid, bare, value, observed_at in rows:
        readings_by_patient.setdefault(plid, []).append((observed_at, bare, value))

    def _classify_asof(plid: int, cutoff, allowed_keys: list[str]) -> Optional[str]:
        """
        طبقه‌بندیِ control برای یک بیمار as-of cutoff (آخرین قرائتِ هر vitalِ مجاز
        با observed_at ≤ cutoff). برمی‌گرداند 'uncontrolled'|'borderline'|'controlled'
        یا None (unknown — هیچ قرائتِ مجاز تا cutoff).
        """
        latest: dict[str, tuple] = {}   # bare_key → (observed_at, value)
        for observed_at, bare, value in readings_by_patient.get(plid, []):
            if bare not in allowed_keys:
                continue
            if observed_at >= cutoff:
                break   # مرتب صعودی؛ بقیه هم آینده‌اند
            prev = latest.get(bare)
            if prev is None or observed_at > prev[0]:
                latest[bare] = (observed_at, value)
        if not latest:
            return None
        levels = [
            _evaluate_reading(bare, val, indicator_map)
            for bare, (_, val) in latest.items()
        ]
        if "danger" in levels:
            return "uncontrolled"
        if "warn" in levels:
            return "borderline"
        return "controlled"

    # سریِ "all" از همهٔ vitalهای کنترلی استفاده می‌کند؛ per-condition از cond_vitals.
    series_defs: list[tuple[str, set[int], list[str]]] = []
    for cond in TREND_CONDITIONS:
        series_defs.append(
            (cond, plids_by_condition[cond], cond_vitals.get(cond, []))
        )
    series_defs.append(("all", set(active_link_ids), CONTROL_VITALS))

    for b in buckets:
        cutoff = b["end"]
        for cond, plids, allowed in series_defs:
            assessable = 0
            controlled = 0
            for plid in plids:
                level = _classify_asof(plid, cutoff, allowed)
                if level is None:
                    continue   # unknown — خارج از مخرج
                assessable += 1
                if level == "controlled":
                    controlled += 1
            pct = (
                round(controlled * 100.0 / assessable, 1)
                if assessable >= N_SUFFICIENT
                else None   # NULL نه صفر
            )
            result["buckets"].append({
                "ym": b["ym"],
                "condition": cond,
                "assessable_n": assessable,
                "controlled_n": controlled,
                "pct_controlled": pct,
            })

    return result

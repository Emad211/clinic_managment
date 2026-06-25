"""
clinical/cohort_outcome_service.py — سرویسِ outcomeِ کوهورت (Step 49, cluster K).

اصلِ مقدس (clinical-data-scientist، قفل‌شده):
  - on-the-fly، read-only مطلق، بدونِ slice/migration (مشتق از داده‌های موجود).
  - NULL نه عددِ ساختگی: کوهورتِ کوچک/پنجرهٔ کم‌داده → None + reason، هرگز impute.
  - verified=True در همهٔ queryها (⚠️ medication_effect این فیلتر را ندارد — آن باگ
    کپی نشده؛ اینجا verified صریحاً فیلتر می‌شود).
  - هیچ ادعای علّی: framing/caveat همیشه حاضر؛ holdoutِ قدم ۴۳ engagement-holdout است
    نه clinical — این جدول هرگز «اثرِ مراقبتِ ما» نیست.

منطق per-condition:
  1. نگاشتِ condition → indicatorِ کلیدی + متریک (uacr نسبی، tsh ٪ in-range، بقیه mean delta).
  2. baseline هر بیمار = اولین Observationِ verified از indicatorِ کلیدی در
     [enrolled_at-30d, enrolled_at+90d]. نبود → بیمار از کوهورت خارج.
  3. پنجره‌ها نسبت به تاریخِ baselineِ واقعی (نه enrolled_at):
       baseline = همان قرائت
       ۳ماه   = [baseline+45,  baseline+135]  (نزدیک‌ترین به مرکز +90)
       ۶ماه   = [baseline+120, baseline+240]  (نزدیک‌ترین به مرکز +180)
     یک رأی per بیمار per پنجره (نزدیک‌ترین به مرکز).
  4. تجمیع: میانگینِ across-patient هر پنجره + n. delta روی subsetِ paired + n_paired جدا.
  5. min n=۳۰ per-window و per-paired؛ کوهورتِ بدونِ baselineِ کافی → کلِ condition None.
  6. covariate = stratification مشروط به n_subgroup>=30 (diabetes→frailty، hyperlipidemia→ascvd).

GUC-scoped (tenant از پارامتر، RLS اعمال می‌شود). فقط read.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from statistics import median, mean
from typing import Optional

from django.utils import timezone as dj_timezone

from clinical.models import (
    PatientLink,
    Observation,
    PatientCondition,
    Condition,
    PatientFlag,
    ClinicalIndicator,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# پارامترهای آماری — قفل‌شده با data-scientist
# ---------------------------------------------------------------------------
N_SUFFICIENT = 30                # حداقلِ n per-window و per-paired و per-subgroup

# baseline anchoring window نسبت به enrolled_at
_BASELINE_PRE_DAYS = 30          # enrolled_at - 30d
_BASELINE_POST_DAYS = 90         # enrolled_at + 90d

# پنجره‌ها نسبت به تاریخِ baselineِ واقعی (روز)
_WINDOWS = {
    "m3": {"lo": 45,  "hi": 135, "center": 90},
    "m6": {"lo": 120, "hi": 240, "center": 180},
}

# نوعِ تجمیعِ متریک
METRIC_MEAN_DELTA = "mean_delta"          # میانگینِ تغییر (diabetes/htn/hld/ckd-egfr)
METRIC_RELATIVE_MEDIAN = "relative_median"  # کاهشِ نسبیِ میانه (uacr)
METRIC_PERCENT_IN_RANGE = "percent_in_range"  # ٪ in-range با goal_low/high (tsh)


# ---------------------------------------------------------------------------
# نگاشتِ condition → متریک‌ها
# هر condition یک indicatorِ "کلیدی" (anchor برای baseline) + لیستِ متریک‌ها دارد.
# secondary metrics فقط نمایشی‌اند (مثلِ diastolic در htn) — anchor با کلیدی است.
# ---------------------------------------------------------------------------
CONDITION_METRICS: dict[str, dict] = {
    "diabetes": {
        "anchor": "hba1c",
        "metrics": [
            {"key": "hba1c", "type": METRIC_MEAN_DELTA},
        ],
        "stratify_by": "frailty",   # frail vs non-frail (Simpson — هدفِ frail آسان‌گیرانه)
    },
    "hypertension": {
        "anchor": "bp_systolic",
        "metrics": [
            {"key": "bp_systolic",  "type": METRIC_MEAN_DELTA},
            {"key": "bp_diastolic", "type": METRIC_MEAN_DELTA},  # نمایشی؛ کنترل با systolic
        ],
        "stratify_by": None,
    },
    "hyperlipidemia": {
        "anchor": "ldl",
        "metrics": [
            {"key": "ldl", "type": METRIC_MEAN_DELTA},
        ],
        "stratify_by": "ascvd",     # ASCVD targetِ LDL سخت‌گیرانه‌تر (Simpson)
    },
    "ckd": {
        "anchor": "egfr",
        "metrics": [
            {"key": "egfr", "type": METRIC_MEAN_DELTA},
            {"key": "uacr", "type": METRIC_RELATIVE_MEDIAN},  # کاهشِ نسبیِ میانه، نه mean delta
        ],
        "stratify_by": None,
    },
    "thyroid": {
        "anchor": "tsh",
        "metrics": [
            {"key": "tsh", "type": METRIC_PERCENT_IN_RANGE},  # ٪ in-range — پر/کم خنثی می‌کنند
        ],
        "stratify_by": None,
    },
}


_FRAMING = (
    "نمای توصیفیِ تک‌گروهی بدونِ گروهِ کنترل؛ این تغییر اثباتِ اثربخشی نیست "
    "(regression-to-mean، سوگیریِ بقا/تکمیل‌کننده، روندِ سکولار، Simpson). "
    "تفسیرِ علّی فقط پس از holdout مجاز است."
)
_CAVEAT_HOLDOUT = (
    "⚠️ holdoutِ موجود در سامانه engagement-holdout است نه clinical-holdout؛ "
    "این جدول هرگز نباید «اثرِ مراقبتِ ما» تفسیر شود. حداکثر ادعای آینده: "
    "مقایسهٔ treated در برابر engagement-holdout."
)


# ---------------------------------------------------------------------------
# توابعِ کمکی
# ---------------------------------------------------------------------------
def _round2(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 2)


def _round1(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 1)


def _obs_keys(bare_key: str) -> list[str]:
    """هر دو namespaceِ obs_key را بپذیر: vital:<k> و lab:<k>."""
    return [f"vital:{bare_key}", f"lab:{bare_key}"]


def _pick_nearest(
    readings: list[tuple[date, float]],
    center_date: date,
) -> Optional[float]:
    """
    از چند قرائت در یک پنجره، نزدیک‌ترین به مرکزِ پنجره را برگردان — یک رأی per بیمار.
    readings: list of (observed_date, value)
    """
    if not readings:
        return None
    best = min(readings, key=lambda r: abs((r[0] - center_date).days))
    return best[1]


def _baseline_value(
    readings: list[tuple[date, float]],
    enrolled_date: date,
) -> Optional[tuple[date, float]]:
    """
    baseline = اولین (earliest) قرائتِ verified در [enrolled-30d, enrolled+90d].
    برمی‌گرداند (baseline_date, baseline_value) یا None.
    """
    lo = enrolled_date - timedelta(days=_BASELINE_PRE_DAYS)
    hi = enrolled_date + timedelta(days=_BASELINE_POST_DAYS)
    in_window = [r for r in readings if lo <= r[0] <= hi]
    if not in_window:
        return None
    in_window.sort(key=lambda r: r[0])   # earliest first
    return in_window[0]


# ---------------------------------------------------------------------------
# جمع‌آوریِ قرائت‌ها per (patient, indicator) — verified=True
# ---------------------------------------------------------------------------
def _collect_readings(
    tenant_id: int,
    link_ids: list[int],
    bare_key: str,
) -> dict[int, list[tuple[date, float]]]:
    """
    برمی‌گرداند {patient_link_id: [(observed_date, value), ...]} برای یک indicator.
    ⚠️ verified=True صریحاً فیلتر می‌شود (گیتِ self-report).
    """
    out: dict[int, list[tuple[date, float]]] = {}
    if not link_ids:
        return out
    rows = (
        Observation.objects.filter(
            tenant_id=tenant_id,
            patient_link_id__in=link_ids,
            obs_key__in=_obs_keys(bare_key),
            value__isnull=False,
            verified=True,                       # ← گیتِ verified (medication_effect این را ندارد)
        )
        .values_list("patient_link_id", "observed_at", "value")
    )
    for plid, observed_at, value in rows:
        if value is None or observed_at is None:
            continue
        out.setdefault(plid, []).append((observed_at.date(), float(value)))
    return out


# ---------------------------------------------------------------------------
# محاسبهٔ یک متریک (mean_delta / relative_median / percent_in_range) روی یک کوهورت
# ---------------------------------------------------------------------------
def _compute_metric(
    metric_key: str,
    metric_type: str,
    readings_by_patient: dict[int, list[tuple[date, float]]],
    baselines: dict[int, tuple[date, float]],
    ind_obj: Optional[ClinicalIndicator],
) -> dict:
    """
    محاسبهٔ یک متریک برای زیرمجموعهٔ بیمارانِ دارای baseline.

    baselines: {plid: (baseline_date, baseline_value)} — فقط بیمارانِ baseline‌دار.

    خروجی (همهٔ فیلدها همیشه حاضر، null‌ها صریح):
      metric_key, metric_type, unit, direction,
      n_baseline,
      m3: {n, mean, n_paired, delta, reason}
      m6: {n, mean, n_paired, delta, reason}
      reason (سطحِ متریک؛ None اگر OK)
    """
    direction = (getattr(ind_obj, "direction", "high") if ind_obj else "high") or "high"
    unit = getattr(ind_obj, "unit", None) if ind_obj else None
    goal_low = getattr(ind_obj, "goal_low", None) if ind_obj else None
    goal_high = getattr(ind_obj, "goal_high", None) if ind_obj else None

    n_baseline = len(baselines)

    # ── baselineِ این متریک per بیمار ───────────────────────────────────────
    # ⚠️ baselines[plid] تاریخ/مقدارِ indicatorِ کلیدی (anchor) است؛ تاریخِ baseline
    # برای تعریفِ پنجره‌ها درست است، اما baseline-VALUE باید از قرائت‌های همین متریک
    # (نزدیک‌ترین به تاریخِ baselineِ anchor، در همان پنجرهٔ anchor) گرفته شود — وگرنه
    # برای متریکِ ثانویه (uacr/diastolic) مقدارِ anchor به‌اشتباه baseline می‌شد.
    metric_baseline: dict[int, tuple[date, float]] = {}
    for plid, (anchor_b_date, _anchor_b_val) in baselines.items():
        m_readings = readings_by_patient.get(plid, [])
        lo_b = anchor_b_date - timedelta(days=_BASELINE_PRE_DAYS)
        hi_b = anchor_b_date + timedelta(days=_BASELINE_POST_DAYS)
        in_base = [r for r in m_readings if lo_b <= r[0] <= hi_b]
        bval = _pick_nearest(in_base, anchor_b_date)
        if bval is not None:
            metric_baseline[plid] = (anchor_b_date, bval)

    windows_out: dict[str, dict] = {}

    for win_key, win in _WINDOWS.items():
        center = win["center"]
        # per بیمار: مقدارِ پنجره (نزدیک‌ترین به مرکز) + paired با baselineِ همین متریک
        window_values: list[float] = []          # برای میانگینِ across-patient
        paired_baseline: list[float] = []         # baselineِ همین متریک برای subsetِ paired
        paired_window: list[float] = []           # window-value برای subsetِ paired

        for plid, (anchor_b_date, _anchor_b_val) in baselines.items():
            b_date = anchor_b_date   # پنجره‌ها نسبت به تاریخِ baselineِ anchor
            lo_d = b_date + timedelta(days=win["lo"])
            hi_d = b_date + timedelta(days=win["hi"])
            center_d = b_date + timedelta(days=center)
            patient_readings = readings_by_patient.get(plid, [])
            in_win = [r for r in patient_readings if lo_d <= r[0] <= hi_d]
            wval = _pick_nearest(in_win, center_d)
            if wval is None:
                continue
            window_values.append(wval)
            # paired delta فقط وقتی این متریک baselineِ خودش را هم دارد
            mb = metric_baseline.get(plid)
            if mb is not None:
                paired_baseline.append(mb[1])
                paired_window.append(wval)

        n_window = len(window_values)
        n_paired = len(paired_window)

        # ── میانگینِ across-patient پنجره (با گیتِ min n) ───────────────────
        win_mean: Optional[float] = None
        win_reason: Optional[str] = None
        if n_window < N_SUFFICIENT:
            win_reason = "window_n_insufficient"
        else:
            if metric_type == METRIC_PERCENT_IN_RANGE:
                # ٪ in-range با goal_low/high
                glo = goal_low if goal_low is not None else 0.4
                ghi = goal_high if goal_high is not None else 4.0
                in_range = sum(1 for v in window_values if glo <= v <= ghi)
                win_mean = round(in_range * 100.0 / n_window, 1)
            else:
                # mean و relative_median هر دو میانگینِ مقدارِ پنجره را نمایش می‌دهند
                win_mean = _round2(mean(window_values))

        # ── delta روی subsetِ paired (با گیتِ min n_paired) ────────────────
        delta: Optional[float] = None
        delta_reason: Optional[str] = None
        if n_paired < N_SUFFICIENT:
            delta_reason = "paired_n_insufficient"
        else:
            if metric_type == METRIC_MEAN_DELTA:
                # میانگینِ across-patient (post - baseline)
                diffs = [w - b for b, w in zip(paired_baseline, paired_window)]
                delta = _round2(mean(diffs))
            elif metric_type == METRIC_RELATIVE_MEDIAN:
                # uacr: کاهشِ نسبیِ میانه (٪) — median روی (post-base)/base
                rels = [
                    (w - b) / b
                    for b, w in zip(paired_baseline, paired_window)
                    if b and b > 0
                ]
                if rels:
                    delta = round(median(rels) * 100.0, 1)   # درصد؛ منفی = کاهش
                else:
                    delta_reason = "paired_n_insufficient"
            elif metric_type == METRIC_PERCENT_IN_RANGE:
                # tsh: تغییرِ ٪ in-range (post in-range minus baseline in-range, درصد واحد)
                glo = goal_low if goal_low is not None else 0.4
                ghi = goal_high if goal_high is not None else 4.0
                base_in = sum(1 for b in paired_baseline if glo <= b <= ghi)
                post_in = sum(1 for w in paired_window if glo <= w <= ghi)
                delta = round((post_in - base_in) * 100.0 / n_paired, 1)  # نقطه‌درصد

        windows_out[win_key] = {
            "n": n_window,
            "mean": win_mean,
            "n_paired": n_paired,
            "delta": delta,
            "reason": win_reason or delta_reason,
        }

    return {
        "metric_key": metric_key,
        "metric_type": metric_type,
        "unit": unit,
        "direction": direction,
        "n_baseline": n_baseline,
        "m3": windows_out["m3"],
        "m6": windows_out["m6"],
    }


# ---------------------------------------------------------------------------
# stratification — شکستنِ کوهورت به زیرگروه بر اساسِ covariate (مشروط به n)
# ---------------------------------------------------------------------------
def _is_frail(flag_value: Optional[str]) -> bool:
    """frailty enum: robust|intermediate|complex — frail = intermediate یا complex."""
    return (flag_value or "").strip().lower() in ("intermediate", "complex")


def _is_ascvd(flag_value: Optional[str]) -> bool:
    """ascvd bool flag — truthy."""
    return (flag_value or "").strip().lower() in ("1", "true", "yes", "on")


def _stratify(
    tenant_id: int,
    condition_code: str,
    stratify_by: str,
    baselines: dict[int, tuple[date, float]],
    readings_by_patient: dict[int, list[tuple[date, float]]],
    anchor_metric: dict,
    ind_obj: Optional[ClinicalIndicator],
) -> dict:
    """
    کوهورت را بر اساسِ flag (frailty/ascvd) به دو زیرگروه می‌شکند.
    فقط اگر n_subgroup>=30 برای هر زیرگروه؛ وگرنه stratification=None + reason.

    برمی‌گرداند dict یا {"stratification": None, "reason": "subgroup_too_small", "by": ...}
    """
    if not baselines:
        return {"by": stratify_by, "subgroups": None, "reason": "subgroup_too_small"}

    # flagهای این کوهورت را در یک query بخوان
    plids = list(baselines.keys())
    flag_key = "frailty" if stratify_by == "frailty" else "ascvd"
    flag_rows = (
        PatientFlag.objects.filter(
            tenant_id=tenant_id,
            patient_link_id__in=plids,
            flag_key=flag_key,
        )
        .values_list("patient_link_id", "value")
    )
    flag_map: dict[int, str] = {plid: val for plid, val in flag_rows}

    classifier = _is_frail if stratify_by == "frailty" else _is_ascvd

    group_a_plids: list[int] = []   # positive (frail / ascvd)
    group_b_plids: list[int] = []   # negative (non-frail / non-ascvd)
    for plid in plids:
        if classifier(flag_map.get(plid)):
            group_a_plids.append(plid)
        else:
            group_b_plids.append(plid)

    # گیتِ n برای هر زیرگروه (روی n_baseline زیرگروه)
    if len(group_a_plids) < N_SUFFICIENT or len(group_b_plids) < N_SUFFICIENT:
        return {
            "by": stratify_by,
            "subgroups": None,
            "reason": "subgroup_too_small",
            "n_positive": len(group_a_plids),
            "n_negative": len(group_b_plids),
        }

    def _subset(plids_subset: list[int]) -> dict:
        sub_baselines = {p: baselines[p] for p in plids_subset}
        return _compute_metric(
            metric_key=anchor_metric["key"],
            metric_type=anchor_metric["type"],
            readings_by_patient=readings_by_patient,
            baselines=sub_baselines,
            ind_obj=ind_obj,
        )

    pos_label = "frail" if stratify_by == "frailty" else "ascvd"
    neg_label = "non_frail" if stratify_by == "frailty" else "non_ascvd"

    return {
        "by": stratify_by,
        "reason": None,
        "subgroups": [
            {"key": pos_label, "metric": _subset(group_a_plids)},
            {"key": neg_label, "metric": _subset(group_b_plids)},
        ],
    }


# ---------------------------------------------------------------------------
# تابعِ اصلیِ سرویس
# ---------------------------------------------------------------------------
def cohort_outcomes(tenant_id: int) -> dict:
    """
    محاسبهٔ outcomeِ توصیفیِ تک‌گروهی per-condition برای یک tenant.

    on-the-fly، read-only، بدونِ slice. NULL نه عددِ ساختگی.

    Returns
    -------
    dict با کلیدها:
      tenant_id : int
      framing   : str   (غیرعلّی، همیشه)
      caveat    : str   (تمایزِ engagement-holdout، همیشه)
      n_sufficient : int  (آستانهٔ min-n)
      conditions : list[dict] — per condition
          هر condition:
            condition_code, condition_label,
            n_cohort        (کلِ بیمارانِ فعالِ این بیماری),
            n_baseline      (دارایِ baselineِ کافی),
            reason          (None یا 'cohort_too_small'),
            anchor          (indicatorِ کلیدی),
            metrics         (list یا None اگر cohort_too_small),
            stratification  (dict یا None).
    """
    now_date = dj_timezone.now().date()

    result = {
        "tenant_id": tenant_id,
        "framing": _FRAMING,
        "caveat": _CAVEAT_HOLDOUT,
        "n_sufficient": N_SUFFICIENT,
        "conditions": [],
    }

    # ── indicatorهای فعالِ این tenant (برای direction/unit/goal) ──────────────
    indicator_map: dict[str, ClinicalIndicator] = {
        row.key: row
        for row in ClinicalIndicator.objects.filter(
            tenant_id=tenant_id, is_active=True
        )
    }

    # ── conditionهای فعالِ این tenant (code → id + label) ────────────────────
    cond_map: dict[str, Condition] = {
        c.code: c
        for c in Condition.objects.filter(tenant_id=tenant_id, is_active=True)
        if c.code in CONDITION_METRICS
    }

    # ── enrolled_at + active links یک‌بار برای کلِ tenant ────────────────────
    link_enrolled: dict[int, date] = {}
    for lnk in PatientLink.objects.filter(
        tenant_id=tenant_id, is_active=True
    ).values("id", "enrolled_at"):
        ea = lnk["enrolled_at"]
        link_enrolled[lnk["id"]] = ea.date() if ea else now_date

    for cond_code, cfg in CONDITION_METRICS.items():
        cond_obj = cond_map.get(cond_code)
        cond_entry = {
            "condition_code": cond_code,
            "condition_label": cond_obj.name if cond_obj else cond_code,
            "anchor": cfg["anchor"],
            "n_cohort": 0,
            "n_baseline": 0,
            "reason": None,
            "metrics": None,
            "stratification": None,
        }

        if cond_obj is None:
            # این condition در tenant seed نشده → کوهورتِ خالی
            cond_entry["reason"] = "cohort_too_small"
            result["conditions"].append(cond_entry)
            continue

        # ── بیمارانِ فعالِ این بیماری ────────────────────────────────────────
        cohort_link_ids = list(
            PatientCondition.objects.filter(
                tenant_id=tenant_id,
                condition_id=cond_obj.id,
                is_active=True,
            ).values_list("patient_link_id", flat=True)
        )
        cohort_link_ids = [
            plid for plid in set(cohort_link_ids) if plid in link_enrolled
        ]
        cond_entry["n_cohort"] = len(cohort_link_ids)

        if not cohort_link_ids:
            cond_entry["reason"] = "cohort_too_small"
            result["conditions"].append(cond_entry)
            continue

        # ── anchor readings + baseline per بیمار ─────────────────────────────
        anchor_key = cfg["anchor"]
        anchor_readings = _collect_readings(tenant_id, cohort_link_ids, anchor_key)

        baselines: dict[int, tuple[date, float]] = {}
        for plid in cohort_link_ids:
            enrolled_date = link_enrolled[plid]
            bv = _baseline_value(anchor_readings.get(plid, []), enrolled_date)
            if bv is not None:
                baselines[plid] = bv
        cond_entry["n_baseline"] = len(baselines)

        # کوهورتِ بدونِ baselineِ کافی → کلِ condition None + reason
        if len(baselines) < N_SUFFICIENT:
            cond_entry["reason"] = "cohort_too_small"
            result["conditions"].append(cond_entry)
            continue

        # ── محاسبهٔ هر متریکِ این condition ──────────────────────────────────
        metrics_out = []
        for m in cfg["metrics"]:
            m_key = m["key"]
            m_type = m["type"]
            ind_obj = indicator_map.get(m_key)
            # readings: anchor را reuse کن وگرنه جدا بخوان
            if m_key == anchor_key:
                m_readings = anchor_readings
            else:
                m_readings = _collect_readings(tenant_id, cohort_link_ids, m_key)
            metrics_out.append(
                _compute_metric(
                    metric_key=m_key,
                    metric_type=m_type,
                    readings_by_patient=m_readings,
                    baselines=baselines,
                    ind_obj=ind_obj,
                )
            )
        cond_entry["metrics"] = metrics_out

        # ── stratification (مشروط به n) — روی anchor metric ──────────────────
        if cfg.get("stratify_by"):
            cond_entry["stratification"] = _stratify(
                tenant_id=tenant_id,
                condition_code=cond_code,
                stratify_by=cfg["stratify_by"],
                baselines=baselines,
                readings_by_patient=anchor_readings,
                anchor_metric={"key": anchor_key, "type": cfg["metrics"][0]["type"]},
                ind_obj=indicator_map.get(anchor_key),
            )

        result["conditions"].append(cond_entry)

    return result

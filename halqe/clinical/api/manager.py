"""
Manager analytics domain router (cleanup step 5 — god-file split).

Migrated out of the ``config/api.py`` god-file. Holds the five manager-only,
read-only analytics endpoints (population thresholds + suggestion stats +
descriptive cohort/outcome dashboards). Every endpoint enforces the same hard
manager gate (``request.auth.role != "manager"`` → 403).

URLs are preserved byte-for-byte: ``config.api`` wires this router with
``api.add_router("", manager_router)`` and this Router carries ``prefix="/manager"``,
so ``/api/v1`` (urls.py) + ``/manager`` (prefix) + the short sub-paths below ==
the same full paths as before:

  GET /api/v1/manager/population-thresholds  → draft/approved threshold overrides
  GET /api/v1/manager/suggestion-stats       → per-rule suggestion analytics
  GET /api/v1/manager/cohort-outcomes        → descriptive per-condition outcomes
  GET /api/v1/manager/lapsed-return          → lapsed-cohort return rate (closed-window)
  GET /api/v1/manager/control-trend          → 12 monthly %controlled buckets

Honesty principles preserved verbatim: NULL-not-fabricated when n < min_n,
framing/caveat always present, no causal claim, read-only (zero writes).

This module imports FROM ``config.api_base`` (shared ``_jwt_auth``); nothing in
``api_base`` imports a router, so the package stays free of import cycles.
"""
from typing import Optional
from datetime import datetime

from ninja import Router, Schema
from django.utils import timezone

from config.api_base import _jwt_auth
from config.errors import ErrorSchema
from clinical.api._shared import _assert_manager

from clinical.models import (
    SuggestionLog,
    SuggestionEvent,
    PopulationThreshold as _PopulationThreshold,
)
from clinical.cohort_outcome_service import cohort_outcomes as _cohort_outcomes
from clinical.outcome_trend_service import (
    lapsed_return as _lapsed_return,
    control_trend as _control_trend,
)

router = Router()


# ===========================================================================
# Population Threshold Management (Step 39)
# GET /manager/population-thresholds — list draft overrides for review/approval
# Manager-only: requires JWT with role='manager'.
# ===========================================================================

class PopulationThresholdDTO(Schema):
    """
    One population-specific threshold override row (read-only).

    approval_status is always shown so the UI can distinguish draft from approved.
    framing: fixed label indicating this is a draft awaiting physician review.
    """
    id: int
    tenant_id: int
    indicator_key: str
    population_key: str
    bound: str                              # 'high' | 'low'
    warn: Optional[float] = None
    danger: Optional[float] = None
    target: Optional[float] = None
    goal_low: Optional[float] = None
    goal_high: Optional[float] = None
    rationale: Optional[str] = None
    evidence: Optional[str] = None
    approval_status: str                    # 'draft' | 'approved'
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: datetime


class PopulationThresholdListDTO(Schema):
    """Response for GET /manager/population-thresholds."""
    items: list[PopulationThresholdDTO]
    total: int
    # Framing label for the UI — makes the draft/review status explicit
    framing: str


@router.get(
    "/population-thresholds",
    response={200: PopulationThresholdListDTO, 403: ErrorSchema},
    auth=_jwt_auth,
    tags=["manager"],
)
def list_population_thresholds(request):
    """
    لیستِ override‌های آستانهٔ زیرجمعیتی برای بازبینی و تأییدِ پزشک.

    فقط مدیر (manager) دسترسی دارد.
    همهٔ ردیف‌ها (draft و approved) برگردانده می‌شوند تا پزشک وضعیت را ببیند.

    framing="پیش‌نویس — نیازمندِ تأییدِ پزشک" همیشه در response است.

    اکشنِ approve در قدمِ بعد پیاده می‌شود.
    """
    # Manager-only gate — strict role check (shared gate, cleanup step 62)
    guard = _assert_manager(request)
    if guard:
        return guard

    tenant_id = request.tenant_id

    qs = _PopulationThreshold.objects.filter(
        tenant_id=tenant_id,
    ).order_by("population_key", "indicator_key", "bound")

    rows = list(qs)
    items = [
        PopulationThresholdDTO(
            id=row.id,
            tenant_id=row.tenant_id,
            indicator_key=row.indicator_key,
            population_key=row.population_key,
            bound=row.bound,
            warn=row.warn,
            danger=row.danger,
            target=row.target,
            goal_low=row.goal_low,
            goal_high=row.goal_high,
            rationale=row.rationale,
            evidence=row.evidence,
            approval_status=row.approval_status,
            approved_by=row.approved_by,
            approved_at=row.approved_at,
            created_at=row.created_at,
        )
        for row in rows
    ]

    return 200, PopulationThresholdListDTO(
        items=items,
        total=len(items),
        framing="پیش‌نویس — نیازمندِ تأییدِ پزشک",
    )


# ===========================================================================
# Suggestion Stats (Step 41) — GET /manager/suggestion-stats
# Manager-only: requires JWT with role='manager'.
# ===========================================================================

_MIN_N_FOR_RATE = 5
_MIN_IMPRESSIONS_FOR_RATE = 10


class SuggestionRuleStatsDTO(Schema):
    """
    Stats per rule_code — all rate fields are Optional (NULL when n < min_n).

    Framing principle: rates measure physician behaviour, not rule quality.
    Correlational, not causal (no holdout).
    """
    rule_code: str
    n_accepted: int
    n_dismissed: int
    n_pending: int
    n_acted: int                                    # = accepted + dismissed
    n_fired_patient_days: int                       # count of fired_daily events
    acceptance_rate_of_acted: Optional[float]       # NULL when n_acted < min_n
    rate_reliable: bool
    impression_acceptance_rate: Optional[float]     # NULL when n_fired_patient_days < 10
    impression_rate_reliable: bool
    last_action_at: Optional[datetime]


class SuggestionStatsResponseDTO(Schema):
    """
    Response for GET /manager/suggestion-stats.

    framing is mandatory and must be present in every response:
    it makes explicit that these numbers reflect physician choices,
    not a measurement of rule quality, and that correlation is not causation.
    """
    generated_at: datetime
    min_n_for_rate: int
    framing: str
    rules: list[SuggestionRuleStatsDTO]


@router.get(
    "/suggestion-stats",
    response={200: SuggestionStatsResponseDTO, 403: ErrorSchema},
    auth=_jwt_auth,
    tags=["manager"],
)
def suggestion_stats(request):
    """
    آمارِ پیشنهادهایِ بالینی به تفکیکِ قاعده — فقط مدیر.

    فیلدهای rate (acceptance_rate_of_acted، impression_acceptance_rate) در صورتی که
    تعدادِ اقدامات/impressions کمتر از حدِ نصاب باشد NULL برگردانده می‌شود (نه صفر).
    این اصلِ «NULL نه صفر هنگامِ داده‌ی ناکافی» را اجرا می‌کند.

    framing در هر پاسخ اجباری است:
      «نرخ‌ها از میانِ اقداماتِ پزشک — نه معیارِ کیفیتِ قاعده؛
       پیش از holdout همبستگی است نه اثر»

    منطقِ آمار:
      - suggestion_log: منبعِ n_accepted / n_dismissed / n_pending / last_action_at
      - suggestion_events WHERE event_type='fired_daily': منبعِ n_fired_patient_days
      - acceptance_rate_of_acted = accepted / (accepted+dismissed)
        فقط وقتی n_acted >= 5؛ در غیرِ این صورت NULL.
      - impression_acceptance_rate = accepted / n_fired_patient_days
        فقط وقتی n_fired_patient_days >= 10؛ در غیرِ این صورت NULL.

    Manager-only: staff → 403.
    """
    guard = _assert_manager(request)
    if guard:
        return guard

    tenant_id = request.tenant_id

    # ── ۱) جمعِ اقدامات از suggestion_log per rule_code ─────────────────────
    from django.db.models import (
        Count, Q, Max,
        Case, When, IntegerField, Sum,
    )

    log_qs = (
        SuggestionLog.objects
        .filter(tenant_id=tenant_id)
        .values("rule_code")
        .annotate(
            n_accepted=Count(Case(
                When(status="accepted", then=1),
                output_field=IntegerField(),
            )),
            n_dismissed=Count(Case(
                When(status="dismissed", then=1),
                output_field=IntegerField(),
            )),
            n_pending=Count(Case(
                When(status="pending", then=1),
                output_field=IntegerField(),
            )),
            last_action_at=Max("acted_at"),
        )
    )
    log_map: dict[str, dict] = {row["rule_code"]: row for row in log_qs}

    # ── ۲) شمارِ fired_daily از suggestion_events per rule_code ─────────────
    event_qs = (
        SuggestionEvent.objects
        .filter(tenant_id=tenant_id, event_type=SuggestionEvent.EVENT_FIRED_DAILY)
        .values("rule_code")
        .annotate(n_fired=Count("id"))
    )
    fired_map: dict[str, int] = {row["rule_code"]: row["n_fired"] for row in event_qs}

    # ── ۳) اتحادِ همهٔ rule_codeها (log + events) ───────────────────────────
    all_codes = set(log_map.keys()) | set(fired_map.keys())

    # ── ۴) ساختنِ ردیف‌های آمار ─────────────────────────────────────────────
    now = timezone.now()
    rule_stats: list[SuggestionRuleStatsDTO] = []

    for code in sorted(all_codes):
        log_row = log_map.get(code, {})
        n_accepted = log_row.get("n_accepted", 0)
        n_dismissed = log_row.get("n_dismissed", 0)
        n_pending = log_row.get("n_pending", 0)
        n_acted = n_accepted + n_dismissed
        n_fired = fired_map.get(code, 0)
        last_action_at = log_row.get("last_action_at")

        # acceptance_rate_of_acted: NULL وقتی n_acted < حدِ نصاب
        if n_acted >= _MIN_N_FOR_RATE:
            acceptance_rate_of_acted: Optional[float] = (
                n_accepted / n_acted if n_acted > 0 else None
            )
            rate_reliable = True
        else:
            acceptance_rate_of_acted = None
            rate_reliable = False

        # impression_acceptance_rate: NULL وقتی n_fired < حدِ نصاب
        if n_fired >= _MIN_IMPRESSIONS_FOR_RATE and n_fired > 0:
            impression_acceptance_rate: Optional[float] = n_accepted / n_fired
            impression_rate_reliable = True
        else:
            impression_acceptance_rate = None
            impression_rate_reliable = False

        rule_stats.append(
            SuggestionRuleStatsDTO(
                rule_code=code,
                n_accepted=n_accepted,
                n_dismissed=n_dismissed,
                n_pending=n_pending,
                n_acted=n_acted,
                n_fired_patient_days=n_fired,
                acceptance_rate_of_acted=acceptance_rate_of_acted,
                rate_reliable=rate_reliable,
                impression_acceptance_rate=impression_acceptance_rate,
                impression_rate_reliable=impression_rate_reliable,
                last_action_at=last_action_at,
            )
        )

    return 200, SuggestionStatsResponseDTO(
        generated_at=now,
        min_n_for_rate=_MIN_N_FOR_RATE,
        framing=(
            "نرخ‌ها از میانِ اقداماتِ پزشک — نه معیارِ کیفیتِ قاعده؛ "
            "پیش از holdout همبستگی است نه اثر"
        ),
        rules=rule_stats,
    )


# ===========================================================================
# Cohort Outcomes (Step 49, cluster K) — GET /manager/cohort-outcomes
# Manager-only: requires JWT with role='manager'.
#
# نمای توصیفیِ تک‌گروهیِ outcome per-condition. on-the-fly، read-only، NULL نه عددِ ساختگی.
# framing/caveat همیشه حاضر؛ تمایزِ engagement-holdout صریح. هیچ ادعای علّی.
# همهٔ فیلدها سریال می‌شوند (درسِ DTOِ قدم ۳۶/۳۸) — تستِ API-shape این را اثبات می‌کند.
# ===========================================================================

class CohortWindowDTO(Schema):
    """یک پنجره (۳ یا ۶ ماه) از یک متریک — همهٔ rateها Optional (NULL هنگامِ n کم)."""
    n: int                              # تعدادِ بیمارانِ دارای قرائت در پنجره
    mean: Optional[float] = None        # میانگین/٪ in-range across-patient؛ NULL اگر n<min_n
    n_paired: int                       # زیرمجموعهٔ paired (baseline + این پنجره)
    delta: Optional[float] = None       # تغییر روی subsetِ paired؛ NULL اگر n_paired<min_n
    reason: Optional[str] = None        # window_n_insufficient | paired_n_insufficient | None


class CohortMetricDTO(Schema):
    """یک متریکِ یک بیماری (hba1c/ldl/egfr/uacr/tsh/…)."""
    metric_key: str
    metric_type: str                    # mean_delta | relative_median | percent_in_range
    unit: Optional[str] = None
    direction: str                      # high | low
    n_baseline: int
    m3: CohortWindowDTO
    m6: CohortWindowDTO


class CohortSubgroupDTO(Schema):
    """یک زیرگروهِ stratification (frail/non_frail یا ascvd/non_ascvd)."""
    key: str
    metric: CohortMetricDTO


class CohortStratificationDTO(Schema):
    """نتیجهٔ stratification یک بیماری (مشروط به n_subgroup>=min_n)."""
    by: str                             # frailty | ascvd
    reason: Optional[str] = None        # subgroup_too_small | None
    subgroups: Optional[list[CohortSubgroupDTO]] = None
    n_positive: Optional[int] = None
    n_negative: Optional[int] = None


class CohortConditionDTO(Schema):
    """outcomeِ توصیفیِ یک بیماری."""
    condition_code: str
    condition_label: str
    anchor: str                         # indicatorِ کلیدیِ baseline
    n_cohort: int                       # کلِ بیمارانِ فعالِ این بیماری
    n_baseline: int                     # دارایِ baselineِ کافی
    reason: Optional[str] = None        # cohort_too_small | None
    metrics: Optional[list[CohortMetricDTO]] = None   # NULL اگر cohort_too_small
    stratification: Optional[CohortStratificationDTO] = None


class CohortOutcomesResponseDTO(Schema):
    """
    پاسخِ GET /manager/cohort-outcomes.

    framing و caveat اجباری‌اند و در هر پاسخ حاضرند:
      - framing: غیرعلّی بودنِ نمای تک‌گروهی (regression-to-mean، سوگیری، Simpson).
      - caveat: تمایزِ حیاتیِ engagement-holdout از clinical-holdout.
    """
    tenant_id: int
    framing: str
    caveat: str
    n_sufficient: int
    conditions: list[CohortConditionDTO]


@router.get(
    "/cohort-outcomes",
    response={200: CohortOutcomesResponseDTO, 403: ErrorSchema},
    auth=_jwt_auth,
    tags=["manager"],
)
def manager_cohort_outcomes(request):
    """
    نمای توصیفیِ outcomeِ کوهورت per-condition — فقط مدیر.

    on-the-fly، read-only مطلق، بدونِ slice. NULL نه عددِ ساختگی:
      - کوهورتِ کوچک (n_baseline<۳۰) → reason='cohort_too_small'، metrics=null.
      - پنجرهٔ کم‌داده (n<۳۰) → mean=null + reason='window_n_insufficient'.
      - paired کم (n_paired<۳۰) → delta=null + reason='paired_n_insufficient'.
      - زیرگروهِ کوچک → stratification.subgroups=null + reason='subgroup_too_small'.

    metricهای خاص: uacr کاهشِ نسبیِ میانه (٪)، tsh ٪ in-range (نه mean delta).
    verified=True در همهٔ queryها. هیچ ادعای علّی — framing/caveat همیشه.

    Manager-only: staff → 403.
    """
    guard = _assert_manager(request)
    if guard:
        return guard

    data = _cohort_outcomes(tenant_id=request.tenant_id)
    return 200, data


# ===========================================================================
# Outcome dashboard endpoints (Step 50, cluster K)
#   GET /manager/lapsed-return   — نرخِ بازگشتِ کوهورتِ lapsed (closed-window)
#   GET /manager/control-trend   — ۱۲ باکتِ ماهانهٔ ٪کنترل (per-condition + all)
#
# هر دو manager-only، on-the-fly، read-only، NULL-not-fabricated، غیرعلّی.
# روی seed (۱۰ بیمار) باید NULL برگردانند — اثباتِ گِیت، نه شکست.
# همهٔ فیلدها سریال (درسِ DTOِ قدم ۳۶/۳۸).
# ===========================================================================

class LapsedReturnResponseDTO(Schema):
    """
    پاسخِ GET /manager/lapsed-return.

    «رویدادِ معنادار» = Appointment(done) ∪ vital(verified) ∪ FollowupTask(done).
    خروجیِ SMS/recall عمداً شامل نیست (پرهیز از tautology).
    return_rate همیشه Optional — NULL وقتی denominator < min_n.
    """
    denominator: int                       # کوهورتِ lapsed در زمانِ T0
    returned: int                          # از مخرج، آن‌ها که در پنجرهٔ بازگشت برگشتند
    return_rate: Optional[float] = None     # درصد ۱ رقم؛ NULL اگر denominator<min_n
    lapse_window_days: int                 # 120
    return_window_days: int                # 120
    min_n: int                             # 30
    framing: str                           # غیرعلّی، همیشه


class ControlTrendBucketDTO(Schema):
    """یک باکتِ ماهانه از یک سری (per-condition یا 'all')."""
    ym: str                                # 'YYYY-MM' میلادی (نمایشِ جلالی در UI)
    condition: str                         # diabetes|hypertension|...|all
    assessable_n: int                      # بیمارانِ دارای ≥۱ قرائت تا پایانِ ماه
    controlled_n: int                      # از assessable، آن‌ها که controlled بودند
    pct_controlled: Optional[float] = None  # درصد ۱ رقم؛ NULL اگر assessable_n<min_n


class ControlTrendResponseDTO(Schema):
    """
    پاسخِ GET /manager/control-trend.

    روندِ زمانیِ توصیفی (secular trend، نه اثرِ مداخله). framing همیشه حاضر.
    """
    buckets: list[ControlTrendBucketDTO]
    min_n: int
    framing: str


@router.get(
    "/lapsed-return",
    response={200: LapsedReturnResponseDTO, 403: ErrorSchema},
    auth=_jwt_auth,
    tags=["manager"],
)
def manager_lapsed_return(request):
    """
    نرخِ بازگشتِ کوهورتِ lapsed — فقط مدیر.

    closed-window: T0 = now-240d (lapse 120 + return 120) تا پنجرهٔ بازگشت کاملاً
    سپری شده باشد (رفعِ immortal-time/survivorship). مخرج = بیمارانِ activeِ
    دارای رویدادِ معنادارِ پیش از T0 که آخرین رویدادشان ≤ T0-120d بوده. صورت =
    آن‌ها که در (T0, T0+120d] رویدادِ معنادار داشتند. SMS/recall شمرده نمی‌شود.
    return_rate = NULL اگر denominator < 30 (NULL نه عددِ ساختگی).

    Manager-only: staff → 403.
    """
    guard = _assert_manager(request)
    if guard:
        return guard
    return 200, _lapsed_return(tenant_id=request.tenant_id)


@router.get(
    "/control-trend",
    response={200: ControlTrendResponseDTO, 403: ErrorSchema},
    auth=_jwt_auth,
    tags=["manager"],
)
def manager_control_trend(request):
    """
    روندِ ماهانهٔ ٪کنترل (۱۲ باکت)، per-condition + سریِ 'all' — فقط مدیر.

    as-of: برای هر ماه، آخرین قرائتِ verified هر vitalِ کنترلی تا پایانِ ماه؛
    طبقه‌بندیِ control (uncontrolled/borderline/controlled/unknown). مخرجِ هر باکت =
    assessable (unknown خارج)؛ صورت = controlled. pct_controlled = NULL اگر
    assessable < 30. روندِ توصیفی — secular trend، نه اثرِ مداخله.

    Manager-only: staff → 403.
    """
    guard = _assert_manager(request)
    if guard:
        return guard
    return 200, _control_trend(tenant_id=request.tenant_id)

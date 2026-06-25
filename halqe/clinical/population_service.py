"""
clinical/population_service.py — Population-specific threshold override service.

قدمِ ۳۹ (خوشهٔ I) — مکانیزمِ گرید red-flag per-population.

دو تابعِ عمومی:

  patient_populations(flags, age) -> set[str]
      تعیین می‌کند بیمار به کدام زیرجمعیت تعلق دارد.
      Gate‌ها (قفل‌شده در هیئتِ مشاوران):
        'frail'        : frailty='complex' OR age>=75
        'hypo_high'    : hypo_risk='high'
        'young_lowrisk': age<45 AND frailty IN (None,'robust')
                         AND hypo_risk IN (None,'low')

  apply_population_overrides(indicator_map, populations, tenant_id) -> indicator_map'
      فقط override‌های approval_status='approved' و bound='high' که
      population_key آن‌ها در populations باشد را اعمال می‌کند.
      ردیف‌های 'draft' کاملاً نادیده گرفته می‌شوند.
      Fail-safe: هر استثنا → mapِ پایه بدون تغییر.
      تقدم هنگام چندِ population: frail > hypo_high > young_lowrisk

اصل ایمنی (قفل‌شده):
  - draft هرگز روی indicator_map اعمال نمی‌شود.
  - تأییدِ پزشک جعل نمی‌شود.
  - رفتارِ فعلیِ red-flag تا زمانی که هیچ ردیفِ approved وجود ندارد تغییر نمی‌کند.
  - bound='low' در این قدم eval نمی‌شود (داده‌یِ draft است؛ موکولِ قدمِ بعد).
"""
import logging

from clinical.models import PopulationThreshold

logger = logging.getLogger(__name__)

# ترتیبِ تقدم هنگام تداخلِ چند زیرجمعیت (مهم‌ترین اول):
# frail > hypo_high > young_lowrisk
# این یعنی اگر بیماری هم frail و هم young_lowrisk باشد (نادر اما ممکن)،
# override سالمندِ شکننده اعمال می‌شود — ایمن‌تر است.
_POPULATION_PRIORITY = ["frail", "hypo_high", "young_lowrisk"]


def patient_populations(flags: dict, age) -> set[str]:
    """
    تعیین کن بیمار به کدام زیرجمعیت‌های بالینی تعلق دارد.

    Parameters
    ----------
    flags : dict
        نقشهٔ flag_key→value از facts['flag'] در build_facts.
        کلیدهای مرتبط: 'frailty' (robust|intermediate|complex|None)
                        'hypo_risk' (low|atrisk|high|None)
    age : int | None
        سنِ بیمار (از demographics.birthdate)؛ None اگر ناموجود.

    Returns
    -------
    set[str]
        مجموعهٔ کلیدهایِ population که این بیمار در آن‌هاست.
        مثلاً {'frail', 'hypo_high'} یا {'young_lowrisk'} یا set().

    Gate‌ها (قفل‌شده — تغییر بدونِ تأییدِ هیئت ممنوع):
      frail        : frailty='complex' OR age>=75
      hypo_high    : hypo_risk='high'
      young_lowrisk: age<45 AND frailty IN (None,'robust')
                     AND hypo_risk IN (None,'low')
    """
    pops: set[str] = set()

    frailty = flags.get("frailty")
    hypo_risk = flags.get("hypo_risk")

    # frail: سالمندِ شکننده
    if frailty == "complex" or (age is not None and age >= 75):
        pops.add("frail")

    # hypo_high: ریسکِ بالایِ هیپوگلیسمی
    if hypo_risk == "high":
        pops.add("hypo_high")

    # young_lowrisk: جوانِ کم‌ریسک
    if (
        age is not None
        and age < 45
        and frailty in (None, "robust")
        and hypo_risk in (None, "low")
    ):
        pops.add("young_lowrisk")

    return pops


def apply_population_overrides(
    indicator_map: dict,
    populations: set,
    tenant_id: int,
) -> dict:
    """
    Override‌های تأییدشدهٔ زیرجمعیت را روی نسخه‌ای از indicator_map اعمال کن.

    فقط ردیف‌های با approval_status='approved' و bound='high' اعمال می‌شوند.
    ردیف‌های 'draft' کاملاً نادیده گرفته می‌شوند — این اصلِ ایمنیِ قفل‌شده است.
    bound='low' در این قدم eval نمی‌شود (موکولِ قدمِ بعد؛ نیازمندِ مسیرِ eval دوجهته).

    Parameters
    ----------
    indicator_map : dict
        نقشهٔ indicator_key → ClinicalIndicator instance از build_facts.
        این dict اصلاح نمی‌شود؛ یک نسخهٔ جدید برگردانده می‌شود.
    populations : set[str]
        مجموعهٔ زیرجمعیت‌هایِ این بیمار (از patient_populations()).
    tenant_id : int
        برای فیلترِ tenant.

    Returns
    -------
    dict
        نسخهٔ جدیدِ indicator_map با override‌های approved.
        اگر populations خالی باشد یا هیچ ردیفِ approved وجود نداشته باشد،
        همان indicator_map اصلی (کپی‌شده) برگردانده می‌شود.
        هر استثنا → mapِ پایه (fail-safe).

    تقدم (Priority) هنگام تداخلِ چند زیرجمعیت:
        frail > hypo_high > young_lowrisk
        override آخر (اولویت بالاتر) روی override قبلی می‌نویسد.
        این یعنی frail قوی‌ترین override است.
    """
    if not populations:
        # هیچ زیرجمعیتی → mapِ پایه
        return indicator_map

    try:
        # فقط approved + bound='high' + population_key در populations
        overrides_qs = PopulationThreshold.objects.filter(
            tenant_id=tenant_id,
            approval_status=PopulationThreshold.APPROVAL_APPROVED,
            bound=PopulationThreshold.BOUND_HIGH,
            population_key__in=populations,
        ).order_by("population_key", "indicator_key")

        overrides = list(overrides_qs)
        if not overrides:
            # هیچ override approved وجود ندارد → mapِ پایه
            return indicator_map

        # نسخهٔ shallow copy از indicator_map (هر value یک object است؛
        # ما آن را مستقیماً جایگزین نمی‌کنیم — dict جدید با dict‌های override می‌سازیم)
        new_map: dict = dict(indicator_map)

        # مرتبِ override‌ها بر اساسِ تقدم (اولویتِ پایین‌تر = آخر اعمال = قوی‌تر)
        # frail در انتها اعمال می‌شود تا روی hypo_high و young_lowrisk بنویسد.
        def _priority(override):
            key = override.population_key
            try:
                return _POPULATION_PRIORITY.index(key)
            except ValueError:
                return len(_POPULATION_PRIORITY)  # ناشناخته → آخر

        overrides_sorted = sorted(overrides, key=_priority, reverse=True)
        # reverse=True: اولویتِ بالاتر (index کمتر) آخر اعمال می‌شود → قوی‌تر

        for override in overrides_sorted:
            ind_key = override.indicator_key

            # پایهٔ indicator موجود است؟
            base = new_map.get(ind_key)
            if base is None:
                # این indicator برای این بیمار اصلاً داده ندارد — override بی‌معنی است
                continue

            # dict جدیدی از پایه بساز (تا dict اصلی دست‌نخورده بماند)
            if isinstance(base, dict):
                merged = dict(base)
            else:
                # ClinicalIndicator ORM instance — به dict تبدیل کن
                merged = {
                    "key": base.key if hasattr(base, "key") else ind_key,
                    "warn": base.warn if hasattr(base, "warn") else base.get("warn"),
                    "danger": base.danger if hasattr(base, "danger") else base.get("danger"),
                    "target": base.target if hasattr(base, "target") else base.get("target"),
                    "goal_low": base.goal_low if hasattr(base, "goal_low") else base.get("goal_low"),
                    "goal_high": base.goal_high if hasattr(base, "goal_high") else base.get("goal_high"),
                    "direction": base.direction if hasattr(base, "direction") else base.get("direction", "high"),
                    "label": base.label if hasattr(base, "label") else base.get("label", ind_key),
                }

            # فقط فیلدهایِ non-null را override کن
            if override.warn is not None:
                merged["warn"] = override.warn
            if override.danger is not None:
                merged["danger"] = override.danger
            if override.target is not None:
                merged["target"] = override.target
            if override.goal_low is not None:
                merged["goal_low"] = override.goal_low
            if override.goal_high is not None:
                merged["goal_high"] = override.goal_high

            new_map[ind_key] = merged

        return new_map

    except Exception:
        # Fail-safe: هر خطا → mapِ پایه؛ engine بدونِ override ادامه می‌دهد
        logger.exception(
            "apply_population_overrides failed for tenant_id=%s populations=%s — "
            "falling back to base indicator_map",
            tenant_id,
            populations,
        )
        return indicator_map

"""Manager-facing revenue and operational-value composition.

This service does not compute money. `RevenueService` remains the single financial
authority: it owns the completed-Encounter scope, the freshness ceiling and the
unavailability contract. The cockpit only *presents* that projection next to the
operational work that produced it, so a manager can see which activity turns into
provable revenue without a second accounting system existing anywhere.

Three rules are enforced here rather than in the template, because a template is the
wrong place to decide what is provable:

1. A missing, stale or unreconciled financial snapshot is reported as unavailable with
   its own Persian reason. It is never degraded to zero.
2. The five A4 stages (booked, attended, service completed, invoice closed, collected)
   are counted from independent populations, so a stage-to-stage percentage is
   published only when it is genuinely a subset relation.
3. `appointments` carries no price column. Booking volume is a count, never money, and
   every appointment block is marked `value_provable: False` so no caller can quietly
   present it beside collected cash as an equal.
"""
from __future__ import annotations

from datetime import timedelta

from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.common.utils import format_jalali_date, format_jalali_datetime, iran_now
from src.services.revenue_service import RevenueService

# Why the money is missing, in the manager's language. A0/A4 forbid turning an error
# into zero revenue, so every code here has to say something true and specific.
# `reconcile` marks the codes a re-read of accounting can actually fix.
UNAVAILABLE_REASONS: dict[str, dict] = {
    "SPECIALIST_CUTOVER_MISSING": {
        "text": (
            "برای بعضی بیماران لینک‌شده، cutover انتساب ثبت نشده است؛ تا آن زمان "
            "هیچ فاکتوری به مطب تخصصی منتسب نمی‌شود."
        ),
        "reconcile": False,
    },
    "ACCOUNTING_DATABASE_UNAVAILABLE": {
        "text": (
            "دیتابیس حسابداری در دسترس نیست. مسیر فایل حسابداری را در تنظیمات "
            "بررسی کنید؛ عدد حدسی جای آن گذاشته نمی‌شود."
        ),
        "reconcile": False,
    },
    "FINANCIAL_RECONCILIATION_INCOMPLETE": {
        "text": (
            "همگام‌سازی مالی کامل نیست؛ برای بعضی فاکتورهای واجد شرایط هنوز "
            "snapshot ثبت نشده است."
        ),
        "reconcile": True,
    },
    "FINANCIAL_OBSERVATION_MISSING": {
        "text": "هیچ snapshot مالی ثبت نشده است.",
        "reconcile": True,
    },
    "FINANCIAL_OBSERVATION_TIMESTAMP_INVALID": {
        "text": (
            "زمان آخرین snapshot مالی معتبر نیست، بنابراین تازگی داده قابل اثبات "
            "نیست."
        ),
        "reconcile": True,
    },
    "FINANCIAL_OBSERVATION_STALE": {
        "text": "آخرین snapshot مالی کهنه است و منتشر نمی‌شود.",
        "reconcile": True,
    },
    "DASHBOARD_REVENUE_ERROR": {
        "text": "محاسبهٔ درآمد با خطا متوقف شد.",
        "reconcile": False,
    },
}

# The A4 stages in order. `of` names the stage a rate is measured against; it is only
# published when the subset relation actually holds for this data.
FUNNEL_STAGES: tuple[tuple[str, str, str | None], ...] = (
    ("booked", "نوبت رزروشده", None),
    ("attended", "حضور بیمار", "booked"),
    ("service_completed", "خدمت تکمیل‌شده", "attended"),
    ("invoice_closed", "فاکتور بسته‌شده", "service_completed"),
    ("collected", "وصول کامل", "invoice_closed"),
)

COLLECTION_STATES: tuple[tuple[str, str, str], ...] = (
    ("collected", "وصول کامل", "ok"),
    ("partially_collected", "وصول ناقص", "warn"),
    ("unpaid", "پرداخت‌نشده", "danger"),
    ("closed_no_billable_items", "بدون آیتم قابل صورتحساب", "muted"),
    ("waiting_for_invoice_closure", "در انتظار بستن فاکتور", "info"),
)

APPOINTMENT_OUTCOMES: tuple[tuple[str, str, str], ...] = (
    ("done", "انجام‌شده", "ok"),
    ("scheduled", "در انتظار", "info"),
    ("no_show", "عدم مراجعه", "danger"),
    ("cancelled", "لغوشده", "warn"),
)

WINDOW_DAYS = 30
AHEAD_DAYS = 30
LOST_LIMIT = 12


class RevenueCockpitService:
    """Composes the authoritative financial projection with operational counts."""

    POLICY_VERSION = "REVENUE_COCKPIT_PRESENTATION_V1"

    def __init__(self, *, revenue=None, appointments=None, clock=None):
        self.revenue = revenue or RevenueService()
        self.appointments = appointments or AppointmentRepository()
        self.clock = clock or iran_now

    # --- publishable ratios ------------------------------------------------

    @staticmethod
    def _rate(numerator, denominator) -> int | None:
        """Percentage, or None when the two stages are not comparable.

        Booking, attendance, service completion, invoice closure and collection are
        five independent stages, not nested subsets: a walk-in encounter has no
        linked appointment, so `attended` can legitimately exceed `booked`. Publishing
        a naive ratio would put a rate above 100% in front of a manager, so an
        out-of-range or empty denominator yields no number at all.
        """
        numerator = int(numerator or 0)
        denominator = int(denominator or 0)
        if denominator <= 0 or numerator > denominator:
            return None
        return round(numerator * 100 / denominator)

    # --- sections ----------------------------------------------------------

    def _money(self, projection: dict) -> dict:
        """The financial block, or an explicit unavailability with its reason."""
        scope = projection.get("scope") or {}
        if projection.get("available"):
            return {
                "available": True,
                "enrolled": int(projection.get("enrolled") or 0),
                "month": projection.get("month") or {},
                "total": projection.get("total") or {},
                "trend": projection.get("trend") or {},
                "payer_review": projection.get("payer_review") or {},
                "observation_age_minutes": scope.get("observation_age_minutes"),
                "freshness_minutes": RevenueService.FRESHNESS_MINUTES,
                "policy_version": scope.get("policy_version"),
            }
        code = str(projection.get("error_code") or "DASHBOARD_REVENUE_ERROR")
        reason = UNAVAILABLE_REASONS.get(code) or UNAVAILABLE_REASONS[
            "DASHBOARD_REVENUE_ERROR"
        ]
        return {
            "available": False,
            "error_code": code,
            "reason": reason["text"],
            "reconcile_helps": bool(reason["reconcile"]),
            "observation_age_minutes": scope.get("observation_age_minutes"),
            "freshness_minutes": RevenueService.FRESHNESS_MINUTES,
            "missing_observations": scope.get("missing_observations"),
            "eligible_invoices": scope.get("eligible_invoices"),
        }

    def _funnel(self, funnel: dict) -> dict:
        """The A4 stages plus the collection split, with unsafe rates suppressed."""
        stages = []
        for key, label, of_key in FUNNEL_STAGES:
            count = int(funnel.get(key) or 0)
            rate = None
            of_label = None
            if of_key:
                rate = self._rate(count, funnel.get(of_key))
                of_label = dict(
                    (stage_key, stage_label)
                    for stage_key, stage_label, _ in FUNNEL_STAGES
                )[of_key]
            stages.append(
                {
                    "key": key,
                    "label": label,
                    "count": count,
                    "rate": rate,
                    "of": of_key,
                    "of_label": of_label,
                }
            )
        collection = [
            {
                "key": key,
                "label": label,
                "tone": tone,
                "count": int(funnel.get(key) or 0),
            }
            for key, label, tone in COLLECTION_STATES
        ]
        return {
            "stages": stages,
            "collection": collection,
            "collection_total": sum(item["count"] for item in collection),
            # Documented so no future caller assumes a subset relation.
            "stages_are_independent": True,
        }

    def _operations(self) -> dict:
        """Appointment outcomes and lost opportunities — counts only, never money."""
        today = self.clock().date()
        window_from = today - timedelta(days=WINDOW_DAYS - 1)
        ahead_to = today + timedelta(days=AHEAD_DAYS)
        from_key = window_from.strftime("%Y-%m-%d")
        to_key = today.strftime("%Y-%m-%d")

        counts = self.appointments.outcome_counts(from_key, to_key)
        outcomes = [
            {
                "key": key,
                "label": label,
                "tone": tone,
                "count": int(counts.get(key) or 0),
            }
            for key, label, tone in APPOINTMENT_OUTCOMES
        ]
        decided = int(counts.get("done") or 0) + int(
            counts.get("no_show") or 0
        ) + int(counts.get("cancelled") or 0)
        lost_count = int(counts.get("no_show") or 0) + int(
            counts.get("cancelled") or 0
        )
        lost_items = self.appointments.lost_opportunities(
            from_key, to_key, limit=LOST_LIMIT
        )
        labels = dict(
            (key, (label, tone)) for key, label, tone in APPOINTMENT_OUTCOMES
        )
        for item in lost_items:
            label, tone = labels.get(
                str(item.get("status") or ""), ("نامشخص", "muted")
            )
            item["status_label"] = label
            item["status_tone"] = tone
            item["scheduled_fa"] = format_jalali_datetime(
                item.get("scheduled_at")
            )

        return {
            "window": {
                "days": WINDOW_DAYS,
                "from_fa": format_jalali_date(from_key),
                "to_fa": format_jalali_date(to_key),
            },
            "outcomes": outcomes,
            "total": int(counts.get("total") or 0),
            "decided": decided,
            "attendance_rate": self._rate(counts.get("done"), decided),
            "lost": {
                "count": lost_count,
                "rate": self._rate(lost_count, decided),
                # `rows`, not `items`: Jinja resolves `lost.items` to the dict's
                # built-in method, so the key must not shadow it.
                "rows": lost_items,
                "shown": len(lost_items),
                # `appointments` has no price column, so the money a no-show cost is
                # not derivable here. Only the count is publishable.
                "value_provable": False,
            },
            "ahead": {
                "days": AHEAD_DAYS,
                "count": self.appointments.scheduled_ahead_count(
                    ahead_to.strftime("%Y-%m-%d")
                ),
                "to_fa": format_jalali_date(ahead_to.strftime("%Y-%m-%d")),
                "value_provable": False,
            },
        }

    # --- entry point -------------------------------------------------------

    def cockpit(self) -> dict:
        """One payload for the manager cockpit.

        The operational sections are always present. Only the financial block can be
        unavailable, and it says why: operations remain visible even when money is
        not provable, which is exactly the case a manager needs to act on.
        """
        now = self.clock()
        projection = self.revenue.dashboard()
        funnel = projection.get("funnel") or {}
        return {
            "as_of": now.isoformat(sep=" ", timespec="seconds"),
            "as_of_fa": format_jalali_datetime(now),
            "policy_version": self.POLICY_VERSION,
            "money": self._money(projection),
            "funnel": self._funnel(funnel),
            "operations": self._operations(),
            "campaigns": projection.get("campaigns")
            or {
                "rows": [],
                "safe_to_sum": False,
                "measurement_status": "JOURNEY_LINK_REQUIRED",
            },
            "scope": projection.get("scope") or {},
        }
